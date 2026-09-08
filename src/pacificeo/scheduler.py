import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from pacificeo.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DueAoi:
    id: str
    tenant_id: str
    name: str
    geometry: dict[str, Any]
    cadence_days: int
    cloud_threshold: float
    product_recipes: list[str]
    stac_collections: list[str]
    last_scheduled_at: datetime | None


class StacClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=60)

    def search(self, aoi: DueAoi, since: datetime, until: datetime) -> list[dict[str, Any]]:
        response = self.client.post(
            f"{self.base_url}/search",
            json={
                "collections": aoi.stac_collections,
                "intersects": aoi.geometry,
                "datetime": f"{since.isoformat()}/{until.isoformat()}",
                "query": {"eo:cloud_cover": {"lte": aoi.cloud_threshold}},
                "limit": 100,
            },
        )
        response.raise_for_status()
        return response.json().get("features", [])


def extract_cog_href(item: dict[str, Any]) -> str | None:
    assets = item.get("assets", {})
    preferred = ("visual", "rendered_preview", "B04", "red", "data")
    for name in preferred:
        asset = assets.get(name)
        if asset and asset.get("href"):
            return str(asset["href"])
    for asset in assets.values():
        media_type = str(asset.get("type", "")).lower()
        roles = asset.get("roles", [])
        if asset.get("href") and ("geotiff" in media_type or "data" in roles):
            return str(asset["href"])
    return None


class AoiScheduler:
    def __init__(self, settings: Settings | None = None, stac: StacClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.stac = stac or StacClient(self.settings.stac_api_url)

    def tick(self) -> int:
        """Schedule every due AOI once. Advisory lock prevents primary/fallback duplication."""
        from pacificeo.db import SessionLocal

        scheduled = 0
        with SessionLocal.begin() as session:
            if not session.execute(text("select pg_try_advisory_xact_lock(hashtext('pacificeo-scheduler'))")).scalar():
                return 0
            for aoi in self._due_aois(session):
                try:
                    scheduled += self._schedule_aoi(session, aoi)
                except Exception as exc:
                    logger.exception("Scheduler failed for AOI %s", aoi.id)
                    self._log_failure(session, aoi, exc)
        return scheduled

    def run_now(self, session: Session, tenant_id: str, aoi_id: str) -> dict[str, Any]:
        """Run a tenant-scoped discovery window immediately and leave an audit record."""
        locked = session.execute(
            text("select pg_try_advisory_xact_lock(hashtext(:lock_name))"),
            {"lock_name": f"pacificeo-manual-{tenant_id}-{aoi_id}"},
        ).scalar()
        if not locked:
            raise RuntimeError("A discovery workflow is already running for this AOI")
        row = session.execute(
            text("""
                select id::text, tenant_id::text, name, st_asgeojson(geometry)::jsonb geometry,
                       cadence_days, cloud_threshold::float, product_recipes, stac_collections,
                       null::timestamptz as last_scheduled_at
                from aois
                where id=:aoi_id and tenant_id=:tenant_id and enabled
            """),
            {"aoi_id": aoi_id, "tenant_id": tenant_id},
        ).mappings().one_or_none()
        if row is None:
            raise LookupError("AOI not found or disabled")
        aoi = DueAoi(**dict(row))
        try:
            scheduled = self._schedule_aoi(session, aoi)
        except Exception as exc:
            self._log_failure(session, aoi, exc)
            raise
        if scheduled:
            run = session.execute(
                text("""
                    select id::text, status::text, action,
                           jsonb_array_length(details->'scene_ids') scene_count
                    from runs
                    where tenant_id=:tenant_id and aoi_id=:aoi_id and run_type='processing'
                    order by created_at desc limit 1
                """),
                {"tenant_id": tenant_id, "aoi_id": aoi_id},
            ).mappings().one()
            return dict(run)
        run = session.execute(
            text("""
                insert into runs
                  (tenant_id,aoi_id,run_type,runner,status,action,details,started_at,finished_at)
                values
                  (:tenant_id,:aoi_id,'scheduler',:runner,'succeeded','no_qualifying_scenes',
                   jsonb_build_object('cloud_threshold',:cloud_threshold,
                                      'window_days',:window_days),now(),now())
                returning id::text,status::text,action,0 scene_count
            """),
            {"tenant_id": tenant_id, "aoi_id": aoi_id, "runner": self.settings.runner_name,
             "cloud_threshold": aoi.cloud_threshold, "window_days": aoi.cadence_days},
        ).mappings().one()
        return dict(run)

    def _due_aois(self, session: Session) -> list[DueAoi]:
        rows = session.execute(
            text("""
                select id::text, tenant_id::text, name, st_asgeojson(geometry)::jsonb geometry,
                       cadence_days, cloud_threshold::float, product_recipes, stac_collections,
                       last_scheduled_at
                from aois
                where enabled
                  and (last_scheduled_at is null
                       or last_scheduled_at + make_interval(days => cadence_days) <= now())
                order by coalesce(last_scheduled_at, '-infinity'::timestamptz)
                for update skip locked
            """)
        ).mappings()
        return [DueAoi(**dict(row)) for row in rows]

    def _schedule_aoi(self, session: Session, aoi: DueAoi) -> int:
        now = datetime.now(UTC)
        since = aoi.last_scheduled_at or now - timedelta(days=aoi.cadence_days)
        items = self.stac.search(aoi, since, now)
        scene_ids: list[str] = []
        for item in items:
            properties = item.get("properties", {})
            cloud_pct = properties.get("eo:cloud_cover")
            cog_href = extract_cog_href(item)
            if cloud_pct is None or float(cloud_pct) > aoi.cloud_threshold or not cog_href:
                continue
            scene_id = str(item["id"])
            session.execute(
                text("""
                    insert into scenes
                      (id, tenant_id, sensor, acquired_at, cloud_pct, cog_href, stac_collection, stac_item)
                    values
                      (:id, :tenant_id, :sensor, :acquired_at, :cloud_pct, :cog_href, :collection, cast(:item as jsonb))
                    on conflict (tenant_id, id) do update set
                      cloud_pct = excluded.cloud_pct, cog_href = excluded.cog_href,
                      stac_item = excluded.stac_item
                """),
                {
                    "id": scene_id,
                    "tenant_id": aoi.tenant_id,
                    "sensor": properties.get("platform", item.get("collection", "unknown")),
                    "acquired_at": properties["datetime"],
                    "cloud_pct": float(cloud_pct),
                    "cog_href": cog_href,
                    "collection": item.get("collection", "unknown"),
                    "item": __import__("json").dumps(item),
                },
            )
            scene_ids.append(scene_id)

        if scene_ids:
            session.execute(
                text("""
                    insert into runs (tenant_id, aoi_id, run_type, runner, action, details)
                    values (:tenant_id, :aoi_id, 'processing', :runner, 'scenes_registered',
                            jsonb_build_object('scene_ids', cast(:scene_ids as text[]),
                                               'recipes', cast(:recipes as text[]),
                                               'cloud_threshold', :cloud_threshold))
                """),
                {
                    "tenant_id": aoi.tenant_id,
                    "aoi_id": aoi.id,
                    "runner": self.settings.runner_name,
                    "scene_ids": scene_ids,
                    "recipes": aoi.product_recipes,
                    "cloud_threshold": aoi.cloud_threshold,
                },
            )
        session.execute(
            text("update aois set last_scheduled_at = :now where id = :id and tenant_id = :tenant_id"),
            {"now": now, "id": aoi.id, "tenant_id": aoi.tenant_id},
        )
        return 1 if scene_ids else 0

    def _log_failure(self, session: Session, aoi: DueAoi, exc: Exception) -> None:
        session.execute(
            text("""
                insert into runs (tenant_id, aoi_id, run_type, runner, status, action, details, finished_at)
                values (:tenant_id, :aoi_id, 'scheduler', :runner, 'failed', 'stac_query_failed',
                        jsonb_build_object('error_type', :error_type, 'message', :message), now())
            """),
            {
                "tenant_id": aoi.tenant_id,
                "aoi_id": aoi.id,
                "runner": self.settings.runner_name,
                "error_type": type(exc).__name__,
                "message": str(exc)[:2000],
            },
        )
