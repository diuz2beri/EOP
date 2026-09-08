import json
from collections.abc import Iterator
from urllib.parse import quote, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from pacificeo.auth import Principal, principal_from_headers, user_from_authorization
from pacificeo.db import SessionLocal, tenant_session
from pacificeo.recipe_config import load_catalog
from pacificeo.scheduler import AoiScheduler
from pacificeo.settings import get_settings

router = APIRouter(prefix="/api")


def scoped_session(principal: Principal = Depends(principal_from_headers)) -> Iterator[Session]:
    with tenant_session(principal.tenant_id, principal.user_id) as session:
        member = session.execute(
            text("select role from tenant_members where tenant_id=:tenant and user_id=:user"),
            {"tenant": principal.tenant_id, "user": principal.user_id},
        ).scalar_one_or_none()
        if member is None:
            raise HTTPException(403, "Not a tenant member")
        session.info["principal"] = principal
        session.info["role"] = member
        yield session


def _product_query(where: str = "") -> str:
    return f"""
        select p.id::text,p.aoi_id::text,a.name aoi_name,p.recipe,p.model_name,p.model_version,
               p.scene_ids,p.accuracy,p.drift,p.status,p.asset_href,p.cloud_threshold,
               p.processed_at,p.created_at,p.approved_by::text,p.approved_at,p.published_at,
               st_asgeojson(a.geometry)::jsonb geometry
        from products p join aois a on a.id=p.aoi_id and a.tenant_id=p.tenant_id
        where p.tenant_id=:tenant {where}
    """


@router.get("/me/tenants")
def list_my_tenants(user_id: str = Depends(user_from_authorization)):
    """Discover every tenant assigned to the signed-in user."""
    with SessionLocal.begin() as session:
        session.execute(
            text("select set_config('app.user_id', :user_id, true)"),
            {"user_id": user_id},
        )
        rows = session.execute(
            text("""
                select t.id::text,t.name,t.slug,tm.role
                from tenant_members tm
                join tenants t on t.id=tm.tenant_id
                where tm.user_id=:user
                order by t.name
            """),
            {"user": user_id},
        ).mappings()
        return [dict(row) for row in rows]


@router.get("/products")
def list_products(status: str | None = None, session: Session = Depends(scoped_session)):
    principal = session.info["principal"]
    extra = "and p.status=:status" if status else ""
    rows = session.execute(text(_product_query(extra) + " order by p.created_at desc"), {"tenant":principal.tenant_id,"status":status}).mappings()
    return [dict(row) for row in rows]


@router.get("/products/{product_id}")
def get_product(product_id: str, session: Session = Depends(scoped_session)):
    principal = session.info["principal"]
    row = session.execute(text(_product_query("and p.id=:id")), {"tenant":principal.tenant_id,"id":product_id}).mappings().one_or_none()
    if not row:
        raise HTTPException(404, "Product not found")
    return dict(row)


@router.get("/products/{product_id}/provenance")
def provenance(product_id: str, session: Session = Depends(scoped_session)):
    product = get_product(product_id, session)
    return {key:product[key] for key in ("id","aoi_id","recipe","model_name","model_version","scene_ids","cloud_threshold","processed_at","accuracy","drift","approved_by","approved_at","published_at")}


@router.get("/runs")
def list_runs(session: Session = Depends(scoped_session)):
    tenant = session.info["principal"].tenant_id
    return [dict(row) for row in session.execute(text("select id::text,aoi_id::text,product_id::text,run_type,runner,status,action,details,auto_fix,started_at,finished_at,created_at from runs where tenant_id=:tenant order by created_at desc limit 500"), {"tenant":tenant}).mappings()]


@router.get("/analytics/summary")
def analytics_summary(
    aoi_id: UUID | None = None,
    days: int = Query(365, ge=1, le=3650),
    session: Session = Depends(scoped_session),
):
    """Return tenant-scoped operational analytics from reviewed products only."""
    tenant = session.info["principal"].tenant_id
    aoi_filter = "and p.aoi_id=:aoi" if aoi_id else ""
    configured_aoi_filter = "and id=:aoi" if aoi_id else ""
    params = {"tenant": tenant, "aoi": aoi_id, "days": days}
    summary = session.execute(text(f"""
        select count(*)::int reviewed_products,
               count(*) filter (where p.status='published')::int published_products,
               count(*) filter (where p.accuracy is not null)::int validated_products,
               count(distinct p.aoi_id)::int aois_with_products,
               max(p.processed_at) latest_product_at
        from products p
        where p.tenant_id=:tenant and p.status in ('approved','published')
          and p.processed_at >= now() - make_interval(days => :days)
          {aoi_filter}
    """), params).mappings().one()
    configured_aois = session.execute(text(f"""
        select count(*)::int from aois
        where tenant_id=:tenant and enabled {configured_aoi_filter}
    """), params).scalar_one()
    activity = session.execute(text(f"""
        select p.id::text,p.aoi_id::text,a.name aoi_name,p.recipe,p.status::text,
               p.accuracy,p.drift,p.processed_at,p.approved_at,p.published_at
        from products p join aois a on a.id=p.aoi_id and a.tenant_id=p.tenant_id
        where p.tenant_id=:tenant and p.status in ('approved','published')
          and p.processed_at >= now() - make_interval(days => :days)
          {aoi_filter}
        order by p.processed_at desc limit 100
    """), params).mappings()
    latest_scene = session.execute(text(f"""
        select s.id scene_id,s.sensor,s.acquired_at,s.cloud_pct::float,
               s.stac_collection,p.id::text product_id,a.name aoi_name
        from products p
        join aois a on a.id=p.aoi_id and a.tenant_id=p.tenant_id
        cross join lateral unnest(p.scene_ids) linked(scene_id)
        join scenes s on s.tenant_id=p.tenant_id and s.id=linked.scene_id
        where p.tenant_id=:tenant and p.status in ('approved','published')
          and p.processed_at >= now() - make_interval(days => :days)
          {aoi_filter}
        order by s.acquired_at desc limit 1
    """), params).mappings().one_or_none()
    return {
        **dict(summary),
        "configured_aois": configured_aois,
        "latest_scene": dict(latest_scene) if latest_scene else None,
        "activity": [dict(row) for row in activity],
    }


@router.get("/aois")
def list_aois(session: Session = Depends(scoped_session)):
    tenant = session.info["principal"].tenant_id
    rows = session.execute(text("""
        select id::text,name,cadence_days,cloud_threshold::float,product_recipes,
               stac_collections,internal_only,enabled,last_scheduled_at,
               st_asgeojson(geometry)::jsonb geometry
        from aois where tenant_id=:tenant order by name
    """), {"tenant": tenant}).mappings()
    return [dict(row) for row in rows]


@router.get("/aois/{aoi_id}/scenes")
def list_aoi_scenes(
    aoi_id: UUID,
    limit: int = Query(12, ge=1, le=50),
    session: Session = Depends(scoped_session),
):
    """List real scenes registered by this AOI's acquisition runs for internal preview."""
    tenant = session.info["principal"].tenant_id
    rows = session.execute(text("""
        select * from (
          select distinct on (s.id) s.id scene_id,s.sensor,s.acquired_at,
                 s.cloud_pct::float,s.stac_collection,s.stac_item->'geometry' geometry,
                 s.stac_item->'bbox' bbox,
                 s.stac_item#>>'{assets,thumbnail,href}' preview_href
          from runs r
          cross join lateral jsonb_array_elements_text(r.details->'scene_ids') linked(scene_id)
          join scenes s on s.tenant_id=r.tenant_id and s.id=linked.scene_id
          where r.tenant_id=:tenant and r.aoi_id=:aoi and r.run_type='processing'
          order by s.id,s.acquired_at desc
        ) registered_scenes
        order by acquired_at desc limit :limit
    """), {"tenant": tenant, "aoi": aoi_id, "limit": limit}).mappings()
    scenes = [dict(row) for row in rows]
    for scene in scenes:
        preview = scene["preview_href"]
        if preview and urlparse(preview).scheme != "https":
            scene["preview_href"] = None
    return scenes


@router.get("/aois/{aoi_id}/timeline")
def product_timeline(aoi_id: str, session: Session = Depends(scoped_session)):
    """Return real scene frames from human-approved products for one tenant AOI."""
    tenant = session.info["principal"].tenant_id
    rows = session.execute(text("""
        select p.id::text product_id,p.recipe,p.status::text,p.asset_href,
               p.model_name,p.model_version,p.accuracy,p.drift,p.approved_at,p.published_at,
               s.id scene_id,s.sensor,s.acquired_at,s.cloud_pct::float,s.cog_href,
               s.stac_collection
        from products p
        cross join lateral unnest(p.scene_ids) with ordinality linked(scene_id, scene_order)
        join scenes s on s.tenant_id=p.tenant_id and s.id=linked.scene_id
        where p.tenant_id=:tenant and p.aoi_id=:aoi
          and p.status in ('approved','published')
          and p.approved_by is not null and p.approved_at is not null
        order by s.acquired_at, p.created_at, linked.scene_order
    """), {"tenant": tenant, "aoi": aoi_id}).mappings()
    titiler = get_settings().titiler_url.rstrip("/")
    result = []
    for row in rows:
        item = dict(row)
        source_href = item["asset_href"] or item["cog_href"]
        item["tile_url"] = (
            f"{titiler}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png"
            f"?url={quote(source_href, safe='')}"
            if titiler and source_href else None
        )
        item["source_href"] = source_href
        result.append(item)
    return result


@router.post("/aois/{aoi_id}/run", status_code=202)
def run_aoi_now(aoi_id: str, session: Session = Depends(scoped_session)):
    if session.info["role"] != "admin":
        raise HTTPException(403, "Admin role required")
    principal = session.info["principal"]
    try:
        return AoiScheduler().run_now(session, principal.tenant_id, aoi_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        if "already running" in str(exc):
            raise HTTPException(409, str(exc)) from exc
        raise


class ApprovalRequest(BaseModel):
    comment: str | None = None


class AoiCreate(BaseModel):
    name: str
    geometry: dict
    cadence_days: int
    cloud_threshold: float
    product_recipes: list[str]
    stac_collections: list[str] = ["sentinel-2-l2a"]
    internal_only: bool = False
    stakeholder_emails: list[str] = []
    stakeholder_imessage_handles: list[str] = []
    reference_config: dict | None = None


@router.post("/aois", status_code=201)
def create_aoi(body: AoiCreate, session: Session = Depends(scoped_session)):
    if session.info["role"] != "admin":
        raise HTTPException(403, "Admin role required")
    for recipe in body.product_recipes:
        load_catalog().require(recipe)
    principal = session.info["principal"]
    aoi_id = session.execute(text("""
        insert into aois(tenant_id,name,geometry,cadence_days,cloud_threshold,product_recipes,
          stac_collections,internal_only,stakeholder_emails,stakeholder_imessage_handles,reference_config)
        values(:tenant,:name,st_multi(st_setsrid(st_geomfromgeojson(:geometry),4326)),:cadence,:cloud,
          :recipes,:collections,:internal,:emails,:imessages,cast(:references as jsonb)) returning id::text
    """), {"tenant":principal.tenant_id,"name":body.name,"geometry":json.dumps(body.geometry),
      "cadence":body.cadence_days,"cloud":body.cloud_threshold,"recipes":body.product_recipes,
      "collections":body.stac_collections,"internal":body.internal_only,"emails":body.stakeholder_emails,
      "imessages":body.stakeholder_imessage_handles,"references":json.dumps(body.reference_config) if body.reference_config else None}).scalar_one()
    return {"id":aoi_id,"name":body.name}


def _require_reviewer(session: Session) -> None:
    if session.info["role"] not in ("reviewer", "admin"):
        raise HTTPException(403, "Reviewer role required")


@router.post("/products/{product_id}/approve")
def approve(product_id: str, body: ApprovalRequest, session: Session = Depends(scoped_session)):
    _require_reviewer(session)
    principal = session.info["principal"]
    updated = session.execute(text("""
        update products set status='approved',approved_by=:user,approved_at=now()
        where id=:id and tenant_id=:tenant and status='draft' returning id::text
    """), {"id":product_id,"tenant":principal.tenant_id,"user":principal.user_id}).scalar_one_or_none()
    if not updated:
        raise HTTPException(409, "Only a draft product can be approved")
    session.execute(text("insert into product_approvals(tenant_id,product_id,reviewer_id,decision,comment) values(:tenant,:product,:user,'approved',:comment)"), {"tenant":principal.tenant_id,"product":product_id,"user":principal.user_id,"comment":body.comment})
    session.execute(text("insert into runs(tenant_id,product_id,run_type,runner,status,action,details,started_at,finished_at) values(:tenant,:product,'approval','human','succeeded','human_approved',cast(:details as jsonb),now(),now())"), {"tenant":principal.tenant_id,"product":product_id,"details":json.dumps({"reviewer_id":principal.user_id,"comment":body.comment})})
    return {"id": product_id, "status": "approved"}


@router.post("/products/{product_id}/publish")
def publish(product_id: str, session: Session = Depends(scoped_session)):
    _require_reviewer(session)
    principal = session.info["principal"]
    product = session.execute(text("""
        update products p set status='published',published_at=now()
        from aois a where p.id=:id and p.tenant_id=:tenant and p.status='approved'
          and p.approved_by is not null and p.approved_at is not null
          and a.id=p.aoi_id and a.tenant_id=p.tenant_id
        returning p.id::text,p.recipe,p.accuracy,a.stakeholder_emails,a.stakeholder_imessage_handles
    """), {"id":product_id,"tenant":principal.tenant_id}).mappings().one_or_none()
    if not product:
        raise HTTPException(409, "Product requires logged human approval")
    summary = {"recipe":product["recipe"],"accuracy":product["accuracy"]}
    for recipient in product["stakeholder_emails"]:
        _queue_notification(session, principal.tenant_id, product_id, "email", recipient, summary)
    for recipient in product["stakeholder_imessage_handles"]:
        _queue_notification(session, principal.tenant_id, product_id, "imessage", recipient, summary)
    session.execute(text("insert into runs(tenant_id,product_id,run_type,runner,status,action,details,started_at,finished_at) values(:tenant,:product,'publish','api','succeeded','published_after_human_approval',cast(:details as jsonb),now(),now())"), {"tenant":principal.tenant_id,"product":product_id,"details":json.dumps({"publisher_id":principal.user_id})})
    return {"id": product_id, "status": "published"}


def _queue_notification(session: Session, tenant: str, product: str, channel: str, recipient: str, summary: dict):
    session.execute(text("insert into notifications(tenant_id,product_id,channel,recipient) values(:tenant,:product,:channel,:recipient)"), {"tenant":tenant,"product":product,"channel":channel,"recipient":recipient})
