# ADR 0001: Production topology for PacificEO Monitor

- **Status:** Proposed for staging implementation
- **Date:** 2026-09-08

## Decision

Use a small-operator topology that keeps the current application stack:

1. **Sites** serves the React/MapLibre dashboard.
2. **Supabase** provides Google-backed authentication, PostGIS and tenant-prefixed object storage.
3. **Cloud Run service** hosts the Dockerized FastAPI operational API. Vercel remains a temporary API host only until cutover.
4. **Cloud Scheduler** invokes an authenticated scheduler job; scheduling does not depend on a serverless application lifespan.
5. The **Apple Silicon primary dispatcher** processes the same Postgres queue and records heartbeats.
6. A **Cloud Run Job fallback** claims overdue runs after the configured grace window and uses the identical worker image.
7. A private **TiTiler Cloud Run service** renders allowlisted COG assets through a tenant-authorized API tile broker.
8. Email uses a transactional provider adapter. iMessage uses a least-privilege webhook to the operator's Apple-hosted bridge.

## Why

- It preserves FastAPI, PostGIS, Docker, React/MapLibre, Supabase and the local worker.
- Scheduled work and raster rendering need longer-lived or job-oriented compute than the current Vercel lifecycle provides.
- One worker image prevents primary/fallback science drift.
- Supabase keeps identity, spatial data and tenant storage within the existing operational footprint.
- Cloud Run Jobs and Cloud Scheduler minimize idle infrastructure for a single-operator studio.

## Security boundaries

- The browser receives Supabase user tokens but never database, object-store or TiTiler service credentials.
- The API validates membership and role, sets tenant transaction context and uses a least-privilege database role.
- The tile broker accepts product/scene identifiers, not arbitrary source URLs.
- Worker upload credentials are scoped to one tenant prefix and resolved from a secret manager.
- Official notifications are created only by a publish transaction backed by a human approval ledger row.

## Consequences

- The Sites proxy origin must change from the temporary Vercel URL during cutover.
- Cloud Scheduler, Run services/jobs, IAM and secret references require infrastructure-as-code.
- Sites access and Supabase tenant membership remain separate controls and must both be provisioned for institutional users.
- A staging environment is required before production model artifacts or stakeholder recipients are connected.

## Open inputs that cannot be invented

- Exact executable and artifact location for each downstream head.
- Versioned national/reference datasets and access permissions per initial AOI.
- Production stakeholder recipient list.
- Domain and data-residency requirements from the first participating institution.
