"""End-to-end release gate for the disposable local Docker stack."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import jwt
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pacificeo.db import engine
from pacificeo.runner import claim_next_run
from pacificeo.settings import get_settings


TENANT_A = UUID("10000000-0000-0000-0000-000000000001")
TENANT_B = UUID("20000000-0000-0000-0000-000000000002")
USER_A = UUID("30000000-0000-0000-0000-000000000003")
USER_B = UUID("40000000-0000-0000-0000-000000000004")
AOI_A = UUID("50000000-0000-0000-0000-000000000005")
PRODUCT_A = UUID("60000000-0000-0000-0000-000000000006")
RUN_PRIMARY = UUID("70000000-0000-0000-0000-000000000007")
RUN_CLOUD = UUID("80000000-0000-0000-0000-000000000008")


def seed() -> None:
    with engine.begin() as db:
        db.execute(text("insert into auth.users(id,email) values (:id,'reviewer@local.test') on conflict do nothing"), {"id": USER_A})
        db.execute(text("insert into auth.users(id,email) values (:id,'other@local.test') on conflict do nothing"), {"id": USER_B})
        db.execute(text("insert into tenants(id,name,slug) values (:id,'Fiji Coastal Unit','fiji-coastal') on conflict do nothing"), {"id": TENANT_A})
        db.execute(text("insert into tenants(id,name,slug) values (:id,'Tonga Environment','tonga-environment') on conflict do nothing"), {"id": TENANT_B})
        db.execute(text("insert into tenant_members(tenant_id,user_id,role) values (:tenant,:user,'admin') on conflict do nothing"), {"tenant": TENANT_A, "user": USER_A})
        db.execute(text("insert into tenant_members(tenant_id,user_id,role) values (:tenant,:user,'admin') on conflict do nothing"), {"tenant": TENANT_B, "user": USER_B})
        db.execute(text("delete from runs where tenant_id=:tenant"), {"tenant": TENANT_A})
        db.execute(text("delete from products where id=:id"), {"id": PRODUCT_A})
        db.execute(text("""
            insert into aois(id,tenant_id,name,geometry,cadence_days,cloud_threshold,product_recipes)
            values (:id,:tenant,'Rewa Delta',st_multi(st_geomfromtext('POLYGON((178.35 -18.20,178.55 -18.20,178.55 -18.05,178.35 -18.05,178.35 -18.20))',4326)),5,20,array['mangrove-extent'])
            on conflict do nothing
        """), {"id": AOI_A, "tenant": TENANT_A})
        db.execute(
            text("""
                insert into scenes
                  (id,tenant_id,sensor,acquired_at,cloud_pct,cog_href,stac_collection,stac_item)
                values
                  ('S2_LOCAL_FIXTURE',:tenant,'sentinel-2',:now,12.5,
                   'https://sentinel-cogs.s3.us-west-2.amazonaws.com/local-fixture.tif',
                   'sentinel-2-l2a','{}')
                on conflict do nothing
            """),
            {"tenant": TENANT_A, "now": datetime.now(UTC)},
        )
        db.execute(text("""
            insert into products(id,tenant_id,aoi_id,recipe,model_name,model_version,scene_ids,status,cloud_threshold,processed_at,asset_href)
            values (:id,:tenant,:aoi,'mangrove-extent','Prithvi-EO-2.0-100M-TL','pacific-v1',array['S2_LOCAL_FIXTURE'],'draft',20,:now,'s3://local-fixture/rewa-delta.tif')
        """), {"id": PRODUCT_A, "tenant": TENANT_A, "aoi": AOI_A, "now": datetime.now(UTC)})


def token(user_id: UUID) -> str:
    secret = get_settings().supabase_jwt_secret
    assert secret is not None
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "aud": "authenticated", "iat": now, "exp": now + timedelta(minutes=10)},
        secret.get_secret_value(),
        algorithm="HS256",
    )


def main() -> None:
    seed()
    client = httpx.Client(base_url="http://localhost:8080", timeout=10)
    headers_a = {"authorization": f"Bearer {token(USER_A)}", "x-tenant-id": str(TENANT_A)}
    headers_cross = {"authorization": f"Bearer {token(USER_A)}", "x-tenant-id": str(TENANT_B)}

    assert client.get("/healthz").json() == {"status": "ok"}
    products = client.get("/api/products", headers=headers_a)
    products.raise_for_status()
    assert [row["id"] for row in products.json()] == [str(PRODUCT_A)]
    assert client.get("/api/products", headers=headers_cross).status_code == 403
    assert client.post(f"/api/products/{PRODUCT_A}/publish", headers=headers_a).status_code == 409

    approved = client.post(
        f"/api/products/{PRODUCT_A}/approve",
        headers=headers_a,
        json={"comment": "Local release-gate approval"},
    )
    approved.raise_for_status()
    published = client.post(f"/api/products/{PRODUCT_A}/publish", headers=headers_a)
    published.raise_for_status()

    mutation_blocked = False
    try:
        with engine.begin() as db:
            db.execute(
                text("update products set model_version='tampered' where id=:id"),
                {"id": PRODUCT_A},
            )
    except SQLAlchemyError:
        mutation_blocked = True
    assert mutation_blocked

    provenance = client.get(f"/api/products/{PRODUCT_A}/provenance", headers=headers_a).json()
    assert provenance["scene_ids"] and provenance["model_name"] and provenance["model_version"]
    assert provenance["approved_by"] == str(USER_A) and provenance["published_at"]
    assert provenance["scenes"][0]["id"] == "S2_LOCAL_FIXTURE"
    assert provenance["approvals"][0]["decision"] == "approved"
    assert {run["action"] for run in provenance["audit_runs"]} >= {
        "human_approved",
        "published_after_human_approval",
    }
    runs = client.get("/api/runs", headers=headers_a).json()
    assert {run["action"] for run in runs} >= {"human_approved", "published_after_human_approval"}

    with engine.begin() as db:
        db.execute(
            text("""
                insert into runs
                  (id,tenant_id,aoi_id,run_type,runner,status,action,details)
                values
                  (:id,:tenant,:aoi,'processing','scheduler','queued','scenes_registered','{}')
            """),
            {"id": RUN_PRIMARY, "tenant": TENANT_A, "aoi": AOI_A},
        )
    assert claim_next_run("primary") == str(RUN_PRIMARY)
    assert claim_next_run("primary") is None

    with engine.begin() as db:
        db.execute(
            text("""
                insert into runs
                  (id,tenant_id,aoi_id,run_type,runner,status,action,details,created_at)
                values
                  (:id,:tenant,:aoi,'processing','scheduler','queued','scenes_registered','{}',
                   now() - interval '2 hours')
            """),
            {"id": RUN_CLOUD, "tenant": TENANT_A, "aoi": AOI_A},
        )
    assert claim_next_run("cloud") == str(RUN_CLOUD)
    assert claim_next_run("cloud") is None
    print("LOCAL_RELEASE_GATE=PASS")


if __name__ == "__main__":
    main()
