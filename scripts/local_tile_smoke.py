"""Render one real Sentinel-2 COG through the protected local tile route."""

import json
import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy import text

from pacificeo.db import engine
from pacificeo.settings import get_settings
from pacificeo.tiles import issue_tile_token

from local_smoke import AOI_A, TENANT_A, USER_A, seed


PRODUCT_TILE = UUID("90000000-0000-0000-0000-000000000009")


def web_mercator_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    count = 2**zoom
    x = math.floor((lon + 180) / 360 * count)
    latitude = math.radians(lat)
    y = math.floor((1 - math.asinh(math.tan(latitude)) / math.pi) / 2 * count)
    return x, y


def main() -> None:
    seed()
    settings = get_settings()
    now = datetime.now(UTC)
    aoi = {
        "type": "Polygon",
        "coordinates": [[
            [178.35, -18.20],
            [178.55, -18.20],
            [178.55, -18.05],
            [178.35, -18.05],
            [178.35, -18.20],
        ]],
    }
    with httpx.Client(timeout=60) as client:
        response = client.post(
            f"{settings.stac_api_url.rstrip('/')}/search",
            json={
                "collections": ["sentinel-2-l2a"],
                "intersects": aoi,
                "datetime": f"{(now - timedelta(days=30)).isoformat()}/{now.isoformat()}",
                "query": {"eo:cloud_cover": {"lte": 100}},
                "limit": 10,
                "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            },
        )
        response.raise_for_status()
        items = response.json().get("features", [])
        assert items, "Earth Search returned no recent Sentinel-2 scene over the Rewa test AOI"
        item = items[0]
        asset_href = item["assets"]["visual"]["href"]
        scene_id = str(item["id"])
        properties = item["properties"]
        with engine.begin() as db:
            db.execute(text("delete from products where id=:id"), {"id": PRODUCT_TILE})
            db.execute(
                text("""
                    insert into scenes
                      (id,tenant_id,sensor,acquired_at,cloud_pct,cog_href,
                       stac_collection,stac_item)
                    values
                      (:id,:tenant,:sensor,:acquired,:cloud,:href,:collection,cast(:item as jsonb))
                    on conflict (tenant_id,id) do update set
                      cloud_pct=excluded.cloud_pct,cog_href=excluded.cog_href,
                      stac_item=excluded.stac_item
                """),
                {
                    "id": scene_id,
                    "tenant": TENANT_A,
                    "sensor": properties.get("platform", "sentinel-2"),
                    "acquired": properties["datetime"],
                    "cloud": properties["eo:cloud_cover"],
                    "href": asset_href,
                    "collection": item["collection"],
                    "item": json.dumps(item),
                },
            )
            db.execute(
                text("""
                    insert into products
                      (id,tenant_id,aoi_id,recipe,model_name,model_version,scene_ids,status,
                       asset_href,cloud_threshold,processed_at,approved_by,approved_at)
                    values
                      (:id,:tenant,:aoi,'tile-integration-smoke','none','source-cog',:scenes,
                       'approved',:href,100,:now,:reviewer,:now)
                """),
                {
                    "id": PRODUCT_TILE,
                    "tenant": TENANT_A,
                    "aoi": AOI_A,
                    "scenes": [scene_id],
                    "href": asset_href,
                    "now": now,
                    "reviewer": USER_A,
                },
            )
            db.execute(
                text("""
                    insert into product_approvals
                      (tenant_id,product_id,reviewer_id,decision,comment)
                    values
                      (:tenant,:product,:reviewer,'approved','Local tile integration test')
                """),
                {"tenant": TENANT_A, "product": PRODUCT_TILE, "reviewer": USER_A},
            )

        secret = settings.tile_signing_secret
        assert secret is not None
        tile_token = issue_tile_token(
            str(PRODUCT_TILE), str(TENANT_A), secret.get_secret_value(), 5,
        )
        x, y = web_mercator_tile(178.45, -18.12, 10)
        tile = client.get(
            f"http://localhost:8080/api/tiles/{PRODUCT_TILE}/10/{x}/{y}.png",
            params={"token": tile_token},
            timeout=90,
        )
        tile.raise_for_status()
        assert tile.headers["content-type"].startswith("image/")
        assert len(tile.content) > 100
        print(
            f"LOCAL_TILE_GATE=PASS scene={scene_id} acquired={properties['datetime']} "
            f"cloud={properties['eo:cloud_cover']} bytes={len(tile.content)}"
        )


if __name__ == "__main__":
    main()
