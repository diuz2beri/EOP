# PacificEO Monitor

Multi-tenant, configuration-driven Earth Observation monitoring for Pacific institutions.

The service shell keeps the existing science behind a manifest-based adapter. It schedules acquisitions, records provenance, validates outputs when reference coverage is sufficient, gates official publication on a human decision, and falls back to a cloud worker when the primary misses its window.

## Architecture

- `supabase/migrations/0001_core.sql`: PostGIS model, Supabase membership, RLS, immutable publication rules, approval ledger, and audit/outbox tables.
- `src/pacificeo/scheduler.py`: cadence-aware, cloud-filtered STAC discovery. AOIs are read exclusively from Postgres.
- `src/pacificeo/runner.py`: primary/cloud queue dispatcher. The cloud mode only claims work older than the configured grace window.
- `src/pacificeo/worker.py`: isolated worker orchestration and provenance creation. Official outputs are always drafts.
- `src/pacificeo/pipeline.py`: stable JSON manifest contract for the existing preprocess → GeoFM → head pipeline.
- `src/pacificeo/api.py`: tenant-scoped products, provenance, logs, AOI creation, approval, and publication.
- `src/pacificeo/notifier.py`: email/iMessage outbox delivery after publication.
- `web`: React/Vite + MapLibre map, review queue, approval/publish actions, and provenance drawer.
- `docker-compose.yml`: API, notification worker, and cloud fallback runner.

## Pacific recipe profile

`config/recipes.yaml` uses IBM/NASA Prithvi-EO-2.0 100M TL as the common embedding backend, with recipe-specific classical heads:

- coastal change — LightGBM pixel classifier; macro IoU
- mangrove extent — LightGBM pixel classifier; F1
- flood extent — logistic-regression pixel classifier; F1
- vegetation stress — isolation forest; balanced accuracy

JRC Global Surface Water, Global Mangrove Watch, and ESA WorldCover are bootstrap/reference-context sources. Per-AOI `reference_config` values override them and should point to authoritative local ministry, survey, or community datasets. Insufficient or absent reference coverage produces `accuracy: null`; the service never synthesizes a value.

The `pacific-v1` head versions are deployment identifiers, not fabricated model artifacts. Their actual artifact locations remain secret references (`PACIFICEO_HEAD_*`) supplied to the existing science adapter.

## Local setup

1. Copy `.env.example` to `.env` and set the database and Supabase values.
2. Apply `supabase/migrations/0001_core.sql` through the Supabase CLI or SQL migration runner.
3. Install with `uv sync --all-groups`.
4. Run `uv run uvicorn pacificeo.main:app --reload`.
5. Run tests with `uv run pytest`.

## Add an AOI without code

Authenticate as a tenant admin and `POST /api/aois` with `config/aoi.example.json`. The `X-Tenant-ID` header selects the tenant, while membership is checked against the JWT subject and enforced again by RLS. The scheduler discovers the record automatically.

## Science adapter contract

Set `PACIFICEO_PIPELINE_COMMAND` to a secret-managed executable. The worker appends one argument: a JSON manifest containing tenant/AOI IDs, scene IDs, recipe, exact model/head versions, reference location, cloud threshold, and `result_path`. The executable performs the already-working science and atomically writes:

```json
{
  "asset_href": "s3://tenant-product-store/product.tif",
  "validation": {"metric": "f1", "value": 0.87, "reference_pixels": 1842}
}
```

Omit `validation` when no valid reference intersection exists. Product assets should be written with a tenant-scoped, least-privilege push token resolved using `tenant_push_tokens.secret_ref`—never stored in this database or repository.

## QA and notification invariant

Official processing creates `draft`. A reviewer must call `approve`, which writes both the reviewer identity and an immutable approval ledger entry. A separate `publish` call verifies that ledger entry in the database trigger before changing status and populating the notification outbox. Notifications therefore cannot be queued for an unapproved official product. AOIs explicitly configured as `internal_only` may be published by the worker and are not sent through the stakeholder notification path.

## Fallback

Run the Apple Silicon dispatcher with `uv run python -m pacificeo.runner --mode primary`. The Docker `cloud-runner` polls the identical queue and invokes the identical worker in a `uv --isolated` environment, but only after `PACIFICEO_PRIMARY_GRACE_MINUTES`. Row locks and the scheduler advisory lock prevent duplicate claims.

## Verification

- Backend: `uv run pytest` and `uv run ruff check src tests`
- Dashboard: `cd web && pnpm install && pnpm build`
- Containers: `docker compose up --build`
