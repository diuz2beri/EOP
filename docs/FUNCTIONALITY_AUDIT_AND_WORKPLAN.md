# PacificEO Monitor — Functionality Audit and Completion Workplan

**Audit date:** 8 September 2026  
**Target:** A review-ready, multi-tenant Pacific Earth Observation service whose displayed values are source-backed, whose official products cannot bypass human approval, and whose scheduled cycles continue when the primary Apple Silicon node is unavailable.

## Executive finding

PacificEO is now a **review-ready service shell**, with production activation still dependent on the existing model artifacts, authoritative reference assets, provider credentials, and a persistent cloud runtime. Authentication, tenant-scoped API queries, AOI creation, STAC discovery, protected raster playback, reviewed-product analytics, immutable provenance, human approval/publication, notification retries, and primary/cloud queue leases are implemented and locally verified.

The largest gaps are operational rather than scientific:

1. The production science adapter is not yet connected to the existing model/head artifacts.
2. Per-recipe authoritative reference files and their versions/hashes still need to be supplied.
3. The Docker cloud runner, private TiTiler, and scheduler need deployment to a persistent cloud runtime; a serverless API process is not a scheduler.
4. Community intake is still an interface prototype and requires its moderated persistence/upload workflow.
5. Email and Apple-hosted iMessage provider commands, tenant storage identities, and observability credentials remain to be configured.

No scientific accuracy value should be displayed until a recipe's configured reference intersection passes its minimum-reference-pixel rule. `accuracy: null` must remain a first-class, visible state.

## Implementation progress

Started on 8 September 2026:

- Production topology recorded in `docs/adr/0001-production-topology.md`.
- Pacific source policy and registry added in `config/data_sources.yaml`.
- GitHub CI added for Python tests/lint/compile, frontend build and container build.
- Import-time scheduler configuration failure fixed so unit tests can run without a database setting.
- Tenant-scoped reviewed-product analytics endpoint added at `GET /api/analytics/summary`.
- Analytics UI changed from hard-coded example values to live approved/published product activity with working AOI and period filters.
- Missing dashboard Publish action added as a separate step after human approval.
- Satellite-context imagery, persistent AOI boundaries, selected-AOI zoom, registered-scene footprints and latest-scene thumbnail/metadata were added. Context imagery is explicitly labelled as separate from dated operational products.
- Tenant-scoped registered-scene API added at `GET /api/aois/{aoi_id}/scenes`; non-HTTPS preview links are rejected.
- Protected product tiles now use short-lived product/tenant tokens, a private TiTiler, and an exact HTTPS source-host allowlist.
- Published rows are immutable, every product scene must exist in the same tenant, and the provenance endpoint includes scenes, approval ledger entries, and product audit runs.
- Primary and cloud dispatchers now use an atomic claim plus recoverable leases; notification delivery retries transient failures with bounded exponential backoff.
- Current verification: frontend builds passed, all local containers started, 13 Python tests passed, Ruff passed (ignoring only the Windows bind-mount executable-bit artifact), and the full local release gates passed.

## Evidence collected

| Check | Result | Evidence |
|---|---|---|
| Live API health | Pass | `https://eop-peach.vercel.app/healthz` returned HTTP 200. |
| Live API contract | Pass, limited | AOI, product, provenance, run, approval, publish and timeline routes are deployed. No analytics, alerts, source-health, notification-admin, community or scene-preview routes exist. |
| Frontend production build | Pass with warning | TypeScript and Vite build succeeded. Main JavaScript bundle is about 1.51 MB before gzip and should be split. |
| Python syntax compilation | Pass | `python -m compileall -q src` completed successfully. |
| Python automated tests | Pass | Nine tests passed inside the built production container, including tenant-scoped scene-preview parameters and unsafe preview-URL filtering. |
| Docker Compose runtime | Pass | PostGIS, FastAPI, React/Vite and the private TiTiler started locally; the release smoke gate passed. |
| Satellite catalogue | Pass | Earth Search returned a real Sentinel-2 L2A scene over the Rewa test AOI acquired 7 September 2026 with 12.507947% catalogue cloud cover. |
| Satellite visualization | Pass locally | That public COG rendered through PacificEO's signed tile broker and private TiTiler as a 28,366-byte image tile. |
| Analytics | Pass for reviewed EO products | AOI and period filters query approved/published tenant products; missing environmental feeds remain visibly unavailable instead of showing examples. |
| Community intake | Fail | Form resets locally and shows a success message, but no report or attachment is persisted. |

## Functional audit by subsystem

### 1. Authentication and tenant isolation — foundation present, hardening required

Present:

- Supabase Google OAuth and tenant membership discovery.
- Tenant ID is required by protected API routes.
- Product, AOI, run and timeline queries include tenant predicates.
- Postgres RLS is enabled and a cross-tenant smoke-test script exists.

Gaps and risks:

- Production database connections must use a least-privilege `NOBYPASSRLS` role; table-owner or service roles can bypass normal RLS unless policies and ownership are designed explicitly.
- `is_tenant_member()` also trusts `app.tenant_id`; that trust must remain exclusive to the authenticated backend role and must be covered by database tests.
- Sites access is currently owner-private while Supabase is also enforcing application login. Institutional reviewers will require an explicit Sites access policy as well as a tenant membership.
- The tenant-discovery screen has no timeout, retry button or actionable error state and can remain on “Checking your organisation access…”.
- No automated API authorization matrix covers viewer, reviewer, admin and cross-tenant attempts.

Review gate:

- Two seeded tenants pass read/write/update denial tests at both API and direct database-policy layers.
- Viewer cannot create/run/approve/publish; reviewer cannot create/run but can approve/publish; admin can configure and operate only its tenant.

### 2. AOI configuration — basic creation works, lifecycle incomplete

Present:

- Admin can draw a polygon and configure cadence, cloud threshold, collections, recipes, internal-only mode and stakeholder emails.
- Scheduler reads AOIs from Postgres; no AOI is hard-coded.

Gaps:

- No AOI edit, disable, archive or delete API/UI.
- Geometry is not validated for polygon type, validity, self-intersection, coordinate bounds, antimeridian crossing, vertex count or maximum area.
- AOIs now render after creation and the map fits a selected AOI; edit/disable lifecycle controls remain outstanding.
- AOI metadata lacks Pacific country/territory code, island group, timezone, local authority, display bounds and reference-data readiness.
- Reference locations cannot be configured in the dashboard.
- No confirmation or dry-run shows the expected STAC footprint before saving.

Review gate:

- Add, edit, disable and re-enable an AOI without code; it remains visible on the map and the scheduler honors the changed configuration.
- Invalid and cross-dateline polygons have documented, tested behavior.

### 3. Scene discovery and preview — catalogue works, reviewer experience incomplete

Present:

- AOI-intersection, collection, date-window and cloud-cover filters are sent to Earth Search.
- Qualifying scenes and their STAC records are persisted with acquisition time, sensor, cloud percentage and COG URL.

Gaps:

- A protected scene-list API and latest-scene preview now expose registered footprints, timestamps, sensor, collection and cloud values; a full selectable scene catalogue is still outstanding.
- Excluded-scene reasons are not persisted or shown.
- Scene asset selection is generic. Each collection needs an explicit asset/band policy and signed-URL refresh strategy.
- No paging beyond the first 100 results and no deduplication policy beyond the database scene key.
- STAC network retry, backoff, rate-limit handling and source-health monitoring are absent.

Review gate:

- A reviewer can see qualifying and rejected scenes, footprints, dates, cloud values, collection, STAC link and a true-colour preview before processing.

### 4. Raster visualization and storage — local path verified; cloud deployment pending

Present:

- Timeline objects can include a TiTiler URL and MapLibre can add it as a raster source.

Gaps:

- A labelled satellite-context basemap is available and is kept visually/semantically separate from dated operational products.
- The local private TiTiler and protected tile broker are implemented and verified; the equivalent private cloud service is not deployed yet.
- Product storage, tenant-scoped upload credentials, object checksums, retention, COG validation and signed read URLs are not implemented in the service shell.
- Timeline responses no longer expose the product asset URL; authenticated provenance still exposes source records to the owning tenant.
- The map zooms to a selected AOI; product selection/zoom remains outstanding.

Recommended deployment:

- Supabase Storage or S3-compatible object storage with one tenant prefix and least-privilege upload identity per tenant.
- TiTiler deployed as a private Cloud Run service, fronted by a PacificEO tile endpoint that authorizes tenant/product access and only permits approved asset hosts.
- A labelled satellite-context basemap for navigation plus a separate, clearly dated **acquisition/product** layer. The basemap must never be presented as the monitored observation.

Review gate:

- Draw AOI → discover scene → open true-colour preview → process → review output → approve → publish → replay the approved raster with real timestamp, scene ID, cloud value and provenance.

### 5. Processing, validation and provenance — contract present, runtime missing

Present:

- External science adapter preserves the existing modelling stack rather than rebuilding it.
- Recipe catalogue defines backend, downstream head, validation metric, drift threshold and fallback reference source.
- Worker writes official products as draft and leaves accuracy null when validation is unavailable or insufficient.

Gaps:

- `PACIFICEO_PIPELINE_COMMAND` is not connected to the real GeoFM/head executable in production.
- Head artifact secrets named in `recipes.yaml` are not resolved or verified.
- The current fallback reference URLs are catalogue/landing locations, not versioned, machine-readable reference assets ready for spatial evaluation.
- Product output is trusted without COG structural validation, checksum, bounds, CRS, resolution, nodata or object-existence checks.
- Provenance omits recipe/config version, source STAC URLs, input asset names/hashes, preprocessing parameters, reference dataset version/hash, code commit, container digest, runner identity and output checksum.
- A failure in one recipe rolls back the whole run; retry/partial-success semantics are not defined.
- No stale `running` lease recovery or controlled retry policy exists.

Pacific recipe decisions for the first review:

| Recipe | Operational input | Reference priority | Required review output |
|---|---|---|---|
| Coastal change | Sentinel-2 L2A first; Landsat for longer baseline | Surveyed ministry shoreline → validated local/community shoreline → JRC water history as context | Change polygon/line, area or distance summary, validation availability and uncertainty note |
| Mangrove extent | Sentinel-2 L2A; Landsat baseline | National forestry inventory → Global Mangrove Watch versioned layer | Extent area, change from approved baseline, F1 only with adequate reference coverage |
| Flood extent | Sentinel-2 where cloud permits; add Sentinel-1 as the next sensor extension | Event agency/field polygons; JRC occurrence only as context | Event extent, affected-area summary, explicit optical-cloud limitation |
| Vegetation stress | Sentinel-2 temporal stack | Local crop/forestry surveys; ESA WorldCover only as a land-cover mask | Anomaly area and trend; no “accuracy” unless the configured validation design supports it |

Review gate:

- Every published product has immutable, downloadable provenance sufficient to reproduce the run, and no missing validation is converted into an invented score.

### 6. Human QA and publishing — core gate complete

Present:

- Official direct draft-to-published transition is blocked.
- Approval records reviewer identity and an audit run.
- Publish endpoint requires an approved state and approval ledger evidence.

Gaps:

- Dashboard provides separate Approve and Publish actions.
- No reject/request-changes action, review comment editor, side-by-side source/output view or approval confirmation summary.
- No explicit role label or separation-of-duties option.
- Internal-only auto-publication has no distinct UI treatment and can be confused with official publication.
- Published-product immutability now covers the complete product row.

Review gate:

- UI demonstrates Draft → Approve (human + comment) → Publish as separate logged actions.
- Attempts to publish draft, publish cross-tenant, mutate a published product or trigger stakeholder notification without approval all fail.

### 7. Analytics — reviewed-product analytics functional; broader indicators planned

Current condition:

- Reviewed/published product counts, recipe activity, AOI filters, period filters and latest source-scene facts are live and tenant-scoped.
- The broader sea-level, temperature, cyclone, coral and forest indicator ingestion model remains planned and must not display invented example values.

Required data model:

- `data_sources`: owner, URL, licence, update policy, spatial/temporal coverage and health.
- `metric_definitions`: stable metric key, units, method/version and valid aggregation rules.
- `metric_observations`: tenant/AOI/region, time, value, uncertainty/quality, source and provenance.
- `product_metrics`: product-linked areas, class counts, change-from-approved-baseline and coverage.
- `alerts`: source, geometry, severity, issued/valid times, status and official bulletin URL.

Required API:

- `GET /api/analytics/summary?region=&from=&to=`
- `GET /api/analytics/series?metric=&aoi=&region=&from=&to=`
- `GET /api/analytics/comparisons?metric=&from=&to=`
- `GET /api/alerts?active=true`
- `GET /api/sources/health`

Pacific source hierarchy:

- EO-derived forest/coastal/mangrove/flood metrics: approved PacificEO products.
- Cyclone history: NOAA IBTrACS; operational alerts must link to the responsible official warning authority, with Fiji Meteorological Service/RSMC Nadi prioritized for the South Pacific.
- Regional catalogue/indicators: Pacific Data Hub CKAN and SDMX APIs, with SPC/SPREP attribution.
- Sea level: local tide-gauge authority records first, then PSMSL/UHSLC station series and Copernicus Marine altimetry for regional context.
- Surface/ocean temperature: an explicitly selected, versioned authoritative product such as ERA5/ERA5-Land and NOAA OISST, with land/ocean distinctions visible.
- Coral/ocean health: do not fabricate one composite “health” number. Show separately sourced indicators and their coverage until a scientifically governed composite is approved.

Review gate:

- Every chart changes with real region/time filters, has units and provenance, handles missing data honestly, and contains no illustrative production values.

### 8. Community observations — currently non-functional

Gaps:

- No `community_reports`, attachments, consent, moderation or verification schema/API.
- Photos are not uploaded; geolocation is free text; example pins/reports/leaderboard are static.
- No offline queue, resumable upload, malware/content validation, EXIF consent or privacy controls.
- Multilingual labels are partial and scientific content remains English-only.

Review gate:

- Submit a report and photo, retain explicit location/photo consent, store under tenant scope, moderate it, display only the allowed precision, and link verified observations to a product-validation record where appropriate.

### 9. Notifications — queue present, delivery not production-ready

Present:

- Publish queues tenant recipients only after an approved product is published.

Gaps:

- Email and iMessage provider commands are not configured.
- Notification summary does not calculate or clearly state the product change.
- One failure becomes terminal; there is no retry schedule, attempt count, dead-letter queue or operator replay.
- No delivery status UI/API or recipient validation.
- iMessage requires an Apple-hosted bridge; it should not be assumed available from a Linux cloud worker.

Recommended split:

- Email: transactional provider adapter such as SES or Resend, with tenant-branded template and delivery events.
- iMessage: least-privilege webhook to the operator's Apple Silicon bridge; if unavailable, keep email authoritative and show channel failure transparently.

Review gate:

- A published, human-approved test product sends a non-production sandbox email and iMessage test, records provider IDs, retries transient errors and never queues a message for an unapproved official product.

### 10. Reliability, deployment and operations — release blocker

Gaps:

- APScheduler inside Vercel is not a dependable persistent scheduler.
- Docker cloud runner only processes queued work; if the primary scheduler is down before enqueue, fallback cannot create the cycle.
- The fallback container is defined locally but not deployed to a cloud runtime.
- No heartbeat, cadence-miss detector, alerting, structured metrics, tracing, backup/restore rehearsal or incident runbook.
- No CI workflow exists. Build artifacts and Sites deployment archives are present as untracked workspace files.

Recommended small-studio topology:

1. Keep Supabase Auth, PostGIS and tenant-scoped Storage.
2. Keep Sites for the dashboard.
3. Move/duplicate the FastAPI operational service into a Docker-based Cloud Run service; retire the Vercel scheduler lifecycle.
4. Use Cloud Scheduler to invoke an authenticated scheduler job.
5. Run the primary Apple Silicon dispatcher with heartbeat records.
6. Run the same Docker worker as a Cloud Run Job when a cycle has no heartbeat or completion after the grace window.
7. Deploy private TiTiler on Cloud Run and restrict its source allowlist.

Review gate:

- Stop the primary node before a due cadence. The cloud scheduler discovers scenes, cloud worker processes the run, and the dashboard shows the draft without duplicate products.

## Prioritized completion workplan

The plan assumes one operator and preserves the existing science. Estimates are working days and should be re-estimated after the real model artifacts and reference files are mounted in a staging environment.

### Phase 0 — Freeze operational decisions (1–2 days)

- [ ] Confirm the four recipe artifact locations, executable invocation, expected input bands and output COG contract.
- [ ] Inventory national/reference datasets, owners, licences, versions and access method; record missing local sources as explicit gaps.
- [ ] Select production region, object store, email provider and Apple iMessage bridge.
- [ ] Define staging tenant, two isolation-test tenants and non-production stakeholder recipients.
- [ ] Approve the Cloud Run + Supabase + Sites topology or record an equivalent supported topology.

**Exit:** signed architecture decision record and a secret inventory containing references—not plaintext values.

### Phase 1 — CI, migrations and security baseline (2–3 days)

- [ ] Add GitHub Actions for Python lint/test, migration tests, frontend typecheck/build, dependency audit and container build.
- [ ] Add incremental migrations for source/metric/community/alert/heartbeat/retry data.
- [ ] Create a least-privilege application database role and force/test RLS where appropriate.
- [ ] Add request validation, pagination, typed status filters and structured API errors.
- [ ] Add role/tenant authorization integration tests and published-product immutability tests.
- [ ] Add secrets scanning and remove deployment archives from normal Git/workspace status through ignore/retention rules.

**Exit:** CI green and the tenant/QA security matrix passes automatically.

### Phase 2 — Operational imagery path (3–4 days)

- [ ] Add licensed satellite-context basemap and explicit “context only” labelling.
- [ ] Add scene-list/preview endpoints with accepted/rejected reasons and footprints.
- [ ] Deploy protected TiTiler and a tenant-authorized tile broker.
- [ ] Configure object storage prefixes, short-lived read URLs, checksums and COG validation.
- [ ] Render saved AOIs and zoom to selected AOI/product.
- [ ] Add raster loading/error/empty states and source attribution.

**Exit:** real Fiji/Pacific Sentinel-2 and Landsat scene previews display for a configured AOI.

### Phase 3 — Production processing and provenance (4–6 days)

- [ ] Connect the existing GeoFM executable through `PACIFICEO_PIPELINE_COMMAND`; do not rewrite model science.
- [ ] Resolve downstream head artifacts from the secret manager and pin their versions/hashes.
- [ ] Stage versioned, machine-readable reference assets per AOI/recipe.
- [ ] Validate output COGs and record expanded immutable provenance.
- [ ] Implement run lease, heartbeat, retry, partial-failure and idempotency behavior.
- [ ] Add validation/drift tests that preserve null accuracy when references are absent or insufficient.

**Exit:** each recipe creates a real draft from real scenes with reproducible provenance; accuracy is computed only when valid reference coverage exists.

### Phase 4 — Complete human review and notifications (2–3 days)

- [ ] Build a full review screen with source preview, output preview, provenance, validation, drift and reviewer comment.
- [ ] Add Reject/Request changes, Approve and separate Publish controls.
- [ ] Make internal-only status visually distinct and audit its automation.
- [ ] Implement email and Apple bridge adapters, retry/dead-letter handling and delivery status.
- [ ] Verify no stakeholder delivery can occur without an approval ledger record.

**Exit:** official end-to-end release and notification test passes with logged human identity.

### Phase 5 — Live analytics (4–6 days)

- [ ] Implement analytics/source tables and API contracts.
- [ ] Extract product metrics at processing time and backfill approved staging products.
- [ ] Ingest the selected Pacific regional, sea-level, temperature and cyclone sources with licences and freshness metadata.
- [ ] Replace all hard-coded cards/charts; wire region and date filters.
- [ ] Display units, coverage, source, method, update time, uncertainty/quality and missing-data states.
- [ ] Add data freshness and regression tests.

**Exit:** analytics contains no illustrative production values and every number resolves to provenance.

### Phase 6 — Community module and localization (3–5 days)

- [ ] Add tenant-scoped report, attachment, consent, moderation and verification workflows.
- [ ] Use structured coordinates/map selection and configurable location precision.
- [ ] Add protected uploads, image validation and offline/resumable queue.
- [ ] Connect verified reports to relevant AOIs/products/reference assessments.
- [ ] Complete English, Fijian, Samoan and Tongan translation resources with community review.

**Exit:** moderated community observations work end to end on desktop and mobile without exposing unintended personal/location data.

### Phase 7 — Failover, observability and release review (3–4 days)

- [ ] Deploy authenticated cloud scheduler, worker fallback and primary heartbeat.
- [ ] Test primary outage before enqueue and during processing.
- [ ] Add dashboards/alerts for cadence misses, queue age, failures, source freshness, tile errors and notification delivery.
- [ ] Rehearse database backup/restore and write operator incident/runbooks.
- [ ] Run accessibility, responsive, performance, security and browser end-to-end tests.
- [ ] Conduct acceptance review with one representative AOI per initial institution.

**Exit:** review evidence pack is complete and all acceptance criteria below pass.

## Final acceptance checklist

- [ ] A new AOI is added and changed entirely through configuration/UI.
- [ ] Sentinel-2/Landsat scenes are discovered on cadence and can be previewed with real metadata.
- [ ] Each production recipe uses its pinned existing model/head artifact and versioned reference configuration.
- [ ] No accuracy is shown unless it was computed from sufficient, recorded reference coverage.
- [ ] Every published product has complete immutable provenance and a valid asset checksum.
- [ ] No official product reaches any stakeholder without a logged human approval and separate publish action.
- [ ] Internal-only automation is visibly and technically separated from official publication.
- [ ] Analytics filters operate on real data and every value has source, units and freshness.
- [ ] Community reports persist, are moderated and honor consent/privacy settings.
- [ ] Email/iMessage status is auditable and failures retry safely.
- [ ] A primary outage still produces exactly one completed cycle through the cloud fallback.
- [ ] Two tenants cannot read or modify each other's AOIs, scenes, products, runs, metrics, reports, assets or notifications.
- [ ] CI, backup/restore, monitoring, security and accessibility release gates pass.

## Review package to produce at completion

1. Architecture and data-flow diagram with trust boundaries.
2. Data-source register with licence, owner, freshness and geographic coverage.
3. Per-recipe model card addendum recording artifact hash, reference design and known Pacific limitations.
4. Automated test report and tenant-isolation evidence.
5. Provenance example for one published product per recipe.
6. Primary-outage/fallback test evidence.
7. Accessibility and performance report.
8. Operator runbook, incident response, backup/restore and stakeholder notification procedure.

## External source notes

- Pacific Data Hub exposes CKAN and SDMX APIs suitable for source discovery and regional indicators: <https://docs.pacificdata.org/catalogue/api> and <https://docs.pacificdata.org/dotstat/api>.
- NOAA IBTrACS is appropriate for historical cyclone tracks and includes active/recent subsets, but operational warnings must remain tied to the responsible warning authority: <https://www.ncei.noaa.gov/products/international-best-track-archive>.
- Pacific Data Hub identifies Digital Earth Pacific, PacificMap and the Pacific Environment Portal as relevant regional platforms that should be assessed for interoperability rather than duplicated: <https://pacificdata.org/platforms>.
