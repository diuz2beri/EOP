import argparse
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from pacificeo.db import SessionLocal
from pacificeo.pipeline import ExternalScienceAdapter, normalize_validation
from pacificeo.recipe_config import load_catalog


def process_run(run_id: str, adapter: ExternalScienceAdapter | None = None) -> list[str]:
    adapter, catalog, product_ids = adapter or ExternalScienceAdapter(), load_catalog(), []
    with SessionLocal.begin() as session:
        run = session.execute(text("""
            select r.id::text, r.tenant_id::text, r.aoi_id::text, r.details,
                   a.cloud_threshold::float, a.reference_config, a.internal_only
            from runs r join aois a on a.id=r.aoi_id and a.tenant_id=r.tenant_id
            where r.id=:id and r.status in ('queued','running') for update of r skip locked
        """), {"id": run_id}).mappings().one_or_none()
        if not run:
            return []
        session.execute(
            text("""
                update runs
                set status='running', started_at=coalesce(started_at, now())
                where id=:id
            """),
            {"id": run_id},
        )
        try:
            for recipe_name in run["details"]["recipes"]:
                recipe = catalog.require(recipe_name)
                refs = run["reference_config"] or {}
                reference = refs.get(recipe["reference"]["override_key"], recipe["reference"]["default_uri"])
                result = adapter.run({"run_id": run_id, "tenant_id": run["tenant_id"], "aoi_id": run["aoi_id"], "scene_ids": run["details"]["scene_ids"], "recipe": recipe_name, "backend": catalog.backend, "head": recipe["head"], "reference": reference, "cloud_threshold": run["cloud_threshold"]})
                cfg = recipe["validation"]
                accuracy = normalize_validation(result.validation, cfg["metric"], cfg["minimum_reference_pixels"])
                drift = _drift(session, run["tenant_id"], run["aoi_id"], recipe_name, accuracy, cfg["drift_drop"])
                status = "published" if run["internal_only"] else "draft"
                product_id = session.execute(text("""
                    insert into products (tenant_id,aoi_id,recipe,model_name,model_version,scene_ids,accuracy,drift,change_summary,status,asset_href,cloud_threshold,processed_at,published_at)
                    values (:tenant_id,:aoi_id,:recipe,:model_name,:model_version,:scene_ids,cast(:accuracy as jsonb),cast(:drift as jsonb),cast(:change_summary as jsonb),:status,:asset_href,:cloud_threshold,:processed_at,case when :status='published' then :processed_at else null end)
                    returning id::text
                """), {"tenant_id":run["tenant_id"],"aoi_id":run["aoi_id"],"recipe":recipe_name,"model_name":catalog.backend["name"],"model_version":catalog.backend["version"],"scene_ids":run["details"]["scene_ids"],"accuracy":json.dumps(accuracy) if accuracy else None,"drift":json.dumps(drift) if drift else None,"change_summary":json.dumps(result.change_summary) if result.change_summary else None,"status":status,"asset_href":result.asset_href,"cloud_threshold":run["cloud_threshold"],"processed_at":datetime.now(UTC)}).scalar_one()
                product_ids.append(product_id)
            session.execute(text("update runs set status='succeeded',action='products_created',details=details||cast(:extra as jsonb),finished_at=now(),lease_expires_at=null where id=:id"), {"id":run_id,"extra":json.dumps({"product_ids":product_ids})})
        except Exception as exc:
            session.rollback()
            with SessionLocal.begin() as failure_session:
                failure_session.execute(text("update runs set status='failed',action='processing_failed',details=details||cast(:error as jsonb),finished_at=now(),lease_expires_at=null where id=:id"), {"id":run_id,"error":json.dumps({"error_type":type(exc).__name__,"message":str(exc)[:2000]})})
            raise
    return product_ids


def _drift(session, tenant_id: str, aoi_id: str, recipe: str, accuracy: dict[str, Any] | None, threshold: float):
    if accuracy is None:
        return None
    previous = session.execute(text("select accuracy from products where tenant_id=:tenant and aoi_id=:aoi and recipe=:recipe and accuracy is not null order by created_at desc limit 1"), {"tenant":tenant_id,"aoi":aoi_id,"recipe":recipe}).scalar_one_or_none()
    if not previous or previous.get("metric") != accuracy["metric"]:
        return {"flagged":False,"reason":"no_comparable_baseline"}
    drop = float(previous["value"]) - float(accuracy["value"])
    return {"flagged":drop >= threshold,"drop":drop,"threshold":threshold}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    process_run(parser.parse_args().run_id)
