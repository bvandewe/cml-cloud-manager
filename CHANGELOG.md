# Changelog

All notable changes to this project will be documented in this file.

The format follows the recommendations of Keep a Changelog (https://keepachangelog.com) and the project aims to follow Semantic Versioning (https://semver.org).

## [Unreleased]

### Fixed — LabRecord↔LabletSession Link Not Shown in Real-Time

- **SSE `lab.bound`/`lab.unbound` id normalization** (control-plane-api/UI): Fixed `sseAdapter.js` to normalize `lab_record_id → id` before dispatching to the labRecords store — previously `upsertLabRecord` silently ignored payloads lacking an `id` field.
- **Cross-store binding update** (control-plane-api/UI): `LAB_RECORD_BOUND` SSE handler now also dispatches `lab_record_id` to the sessions store (and clears it on `LAB_RECORD_UNBOUND`), keeping both sides of the 1:1 link in sync without page reload.
- **LabDetailModal reactive binding** (control-plane-api/UI): Added `LAB_RECORD_BOUND`/`LAB_RECORD_UNBOUND` subscriptions to invalidate and re-render the "Linked Lablets" tab when the currently viewed lab is bound or unbound.
- **SessionDetailsModal reactive binding** (control-plane-api/UI): Added `LAB_RECORD_BOUND`/`LAB_RECORD_UNBOUND` subscriptions to update the overview tab's "Lab Record" field in real-time when a lab binds to or unbinds from the viewed session.

### Fixed — Fleet Capacity Panel Shows Stopped Worker Capacity

- **`selectFleetCapacity` selector** (control-plane-api/UI): Only running workers now contribute to fleet capacity totals. Stopped/pending/terminated workers are counted in `totalWorkers` but their `declared_capacity` and `allocated_capacity` are excluded — a fully stopped fleet correctly shows zero capacity.
- **`CapacityDashboard._loadData` aggregation** (control-plane-api/UI): Applied the same running-only capacity gating to the standalone Capacity Dashboard page.
- **Tests**: 9 new vitest unit tests for `selectFleetCapacity` covering empty fleet, running-only, stopped/pending/terminated exclusion, mixed fleet, null capacity, case-insensitive status, and undefined status.

### Fixed — Sessions Page Summary Metrics

- **Tab-context-aware metric cards** (control-plane-api/UI): Summary metrics now switch between session stats (Lablets tab) and definition stats (Definitions tab) — previously always showed session counts regardless of active tab.
- **LcmTabView DOM event dispatch** (control-plane-api/UI): Fixed `tab-change` event to use `dispatchEvent()` (DOM CustomEvent) instead of `emit()` (EventBus-only), enabling `addEventListener`-based tab-change handlers in SessionsPageV2 and WorkersPageV2.

### Fixed — SSE Race Condition (ADR-039)

- **Timestamp-guarded `mergeAll` reducer** (control-plane-api/UI): Replaced destructive `replaceAll` with `mergeAll` that protects SSE-updated fields (`status`, `pipeline_progress`, `worker_id`, `desired_status`) using `_sseUpdatedAt` timestamp guard (5-second window). Prevents stale HTTP polling data from overwriting real-time SSE-driven state updates.
- **HTTP 201 response upsert** (control-plane-api/UI): Session creation modal now immediately populates the store from the HTTP response, providing instant UI feedback before SSE events arrive.
- **Deferred reload** (control-plane-api/UI): Changed `UI_SESSION_CREATED` reload delay from 500ms to 3000ms, allowing the PENDING→SCHEDULED→INSTANTIATING chain (~1–1.5s) to complete before HTTP poll.
- **Enriched `created` SSE payload** (control-plane-api): `lablet.session.created` event now includes `status`, `definition_name`, `definition_version`, `timeslot_start`, `timeslot_end`, and `reservation_id`.
- **Timeslot extended data shape** (control-plane-api/UI): Fixed SSE handler field name from `data.timeslot` to `data.new_timeslot_end`.
- **Score recorded field names** (control-plane-api/UI): Fixed SSE handler field names from `data.score`/`data.grading_result` to `data.score_report_id`/`data.grade_result`.
- **Dead eventMap cleanup** (control-plane-api/UI): Commented out 9 per-status wire types that backend never emits — backend uses single `lablet.session.status.changed` wire type.

### Added — LDS CloudEvent Direct Ingestion (ADR-040)

- **LDS integration events** (control-plane-api): Three `@cloudevent`-decorated integration events — `io.lablet.lds.session.running.v1`, `session.paused.v1`, `session.ended.v1` — consumed by CPA's `CloudEventIngestor`.
- **LDS event handler** (control-plane-api): `LdsSessionRunningHandler` transitions sessions READY→RUNNING when user logs in via LDS. Includes `EventDeduplicationService`, `InvalidStateTransitionError` handling, and settings toggle.
- **LDS CloudEvent settings** (control-plane-api): `lds_cloudevent_source`, `lds_cloudevent_type_prefix`, `lds_cloudevent_enabled` — configurable per environment.
- **Tests**: 9 new unit tests covering happy path, state guards, deduplication, disable toggle, invalid transition, session_id fallback.

### Fixed — Lab Provisioning Test Remediation (Track 1)

- **Stale reuse tests** (lablet-controller): Rewrote `TestTryReuseExistingLab` class — 4 stale tests replaced with 10 comprehensive tests. Fixed `based_on_definition_id` matching (was using obsolete `node_count`), added `get_lab()` ghost detection mocks, verified ORPHANED marking via `update_lab_record_status`. All 10 tests passing.
- **Ghost guard tests** (lablet-controller): Added `TestStepLabStart` class in `test_instantiation_pipeline.py` — 5 new tests covering ghost lab detection (`get_lab_state` returns `None` → fail + ORPHANED), no-worker-id skip, BOOTED immediate completion, missing `cml_lab_id` failure, and CML exception handling. Relocated from skipped G5 class per ADR-034.
- **LabRecord definition_id assertion** (lablet-controller): Added `based_on_definition_id` payload assertion to `TestRegisterLabRecord::test_registers_lab_and_returns_record_id`, verifying `_register_lab_record()` includes `instance.definition_id` in the discovery payload.
- **Production code**: All 4 Track 1 bugs (definition_id matching, ghost lab verification, LabRecord definition_id, lab_start ghost guard) confirmed already fixed in `lablet_reconciler.py` — no production changes needed, only test remediation.

### Added — Pipeline Run Recording (Sprint F, ADR-034)

- **PipelineRunRecord value object** (control-plane-api): Frozen dataclass capturing pipeline execution outcome — `run_id`, `pipeline_name`, `status`, step counts, timing, `step_results`, provenance fields. Full `to_dict()`/`from_dict()` serialization.
- **PipelineRunRecordedDomainEvent** (control-plane-api): New domain event with `@cloudevent("lab_record.pipeline_run_recorded.v1")` decorator. Triggers `@dispatch` handler on LabRecordState to append bounded history (max 50 entries).
- **LabRecord aggregate methods**: `append_pipeline_run()` (event-sourced via domain event) and `pipeline_run_history_vo` property accessor on LabRecord entity.
- **AppendPipelineRunCommand** (control-plane-api): Self-contained CQRS command + handler following RecordLabRunCommand pattern. OTel-traced, returns 201 with run summary.
- **Internal API endpoint**: `POST /api/internal/lab-records/{id}/pipeline-run` — accepts pipeline execution data from lablet-controller with API key auth.
- **ControlPlaneApiClient.append_pipeline_run()** (lcm-core): HTTP client method for cross-service pipeline run recording.
- **Reconciler wiring** (lablet-controller): All 4 pipeline types (instantiate, teardown, collect_evidence, compute_grading) wired with `on_complete` callback to record pipeline runs via CPA. Fire-and-forget — errors logged but don't affect pipeline outcome.
- **Tests**: 19 new unit tests — PipelineRunRecord VO (8), LabRecord domain integration (6), AppendPipelineRunCommandHandler (5).

### Added — TimeslotManager Documentation (Sprint H6)

- **ADR-037**: TimeslotManager architectural decision record — documents separate hosted service rationale, leader election, expiry detection, configuration, admin endpoints.
- **resource-scheduler README**: TimeslotManagerHostedService section with description, configuration table (4 env vars), expanded admin endpoint table (10 entries).

### Removed — UI Dead Code Cleanup (M3-CLEANUP)

- **SessionsPage V1** (1,411 lines): Removed legacy `SessionsPage.js` web component, superseded by store-driven `SessionsPageV2.js` (StoreConnectedPage pattern). Removed `?sessions=v1` URL fallback from `app.js`. Bundle reduced from 790 KB → 750 KB.

### Added — Instantiation Pipeline (ADR-031, Phases 1–5)

- **Scheduler simplification** (resource-scheduler, Phase 4): Removed static port allocation from `_handle_assign()` — scheduler now passes `allocated_ports={}`. Port allocation is deferred to the lablet-controller pipeline (`ports_alloc` step). Placement engine port check is count-only (no change needed).
- **InstantiationProgress value object** (lcm-core): DAG-based 9-step progress tracker with `to_dict()`/`from_dict()` serialization, step dependency resolution, and capability-aware skip logic
- **CPA internal endpoints**: `update_instantiation_progress`, `allocate_lab_record_ports`, `sync_lab_tags`, `bind_lab_to_session`, `expire_session` — 5 new session lifecycle endpoints
- **CQRS commands** (control-plane-api): `UpdateInstantiationProgressCommand`, `AllocateLabRecordPortsCommand`, `SyncLabTagsCommand`, `BindLabToSessionCommand`, `ExpireLabletSessionCommand` with handler logic
- **CQRS query** (control-plane-api): `GetLabletSessionReadModelQuery` — enriched read model with `instantiation_progress`, `lab_record`, and `allocated_ports`
- **ControlPlaneApiClient methods** (lcm-core): `update_instantiation_progress()`, `allocate_lab_record_ports()`, `sync_lab_tags()`, `bind_lab_to_session()`, `expire_session()` — HTTP client wrappers
- **CML SPI** (lablet-controller): `patch_node_tags()` — PATCH `/api/v0/labs/{lab_id}/nodes/{node_id}` for tag sync after port allocation
- **Pipeline executor** (lablet-controller): DAG-based `_handle_instantiating()` replacement with `_build_default_progress()`, `_next_executable_step()`, `_is_pipeline_complete()`, and 9 step methods (`content_sync` → `variables` → `lab_resolve` → `ports_alloc` → `tags_sync` → `lab_binding` → `lab_start` → `lds_provision` → `mark_ready`)
- **Timeslot expiry** (lablet-controller): Early expiry detection in `reconcile()` before status routing, with `_handle_expired()` calling CPA `expire_session()`
- **Lab discovery port registration** (lablet-controller, Phase 5): After discovering BOOTED/STARTED labs, `LabDiscoveryService` registers ports on LabRecord via CPA `allocate_lab_record_ports()` (idempotent, keyed by `lab_record_id`) and syncs CML node tags if missing via `patch_node_tags()`. Added `PortRegistrationResult`, stats counters, 21 new tests.
- **Tests**: 53 new pipeline tests in `test_instantiation_pipeline.py` covering helpers, executor, all 9 steps, and expiry logic; 15 existing tests updated for pipeline flow

### Added — Resource & Port Observation — "Learn from Live" (ADR-030)

- **Resource observation value objects** (lcm-core): `ResourceObservation`, `NodeObservation`, `InterfaceObservation` frozen dataclasses with `to_dict()`/`from_dict()` serialization
- **LabletSession observation fields**: `observed_resources`, `observed_ports`, `observation_count`, `observed_at`, `port_drift_detected` on aggregate state
- **Domain events**: `ResourcesObserved`, `PortDriftDetected`, `ObserveResourcesRequested` (events 16–18) with `@cloudevent` + `@dispatch` handlers
- **CQRS commands**: `RecordResourceObservationCommand` (internal, from lablet-controller), `RequestResourceObservationCommand` (admin, manual trigger via etcd)
- **CQRS query**: `GetDefinitionResourceObservationsQuery` — aggregates observations across sessions (max/avg/latest CPU/memory/nodes/storage, drift count)
- **CPA admin API**: `GET /api/lablet-definitions/{id}/resource-observations` endpoint with auth
- **CPA internal API**: `POST /api/internal/lablet-sessions/{id}/resource-observations` endpoint for lablet-controller
- **lablet-controller ResourceObserver**: CML runtime introspection (nodes, interfaces, simulation_stats, port extraction from tags)
- **etcd reactive trigger**: Manual observation request projected to etcd, lablet-controller watches and reacts
- **Frontend — SessionDetailPage**: Observation panel with port comparison table (allocated vs observed), drift badge, "Observe Now" button
- **Frontend — LabletDefinitionCard**: Observation indicators (🔍/⚠️), aggregated resource comparison (configured vs max/avg/latest), "Apply Max"/"Apply Latest" buttons, session history
- **Tests**: 52 new unit tests — lcm-core value objects (16), CPA domain aggregate (11), CPA command handlers (9), CPA query handler (8), LC observer (8)
- **Configuration**: `RESOURCE_OBSERVATION_ENABLED` and `RESOURCE_OBSERVATION_TIMEOUT_SECONDS` settings

### Added — Session Entity Model Migration (Phase 7)

- **LabletSession aggregate**: New consolidated aggregate replacing LabletInstance, absorbing LabletLabBinding and LabletRecordRun runtime fields (ADR-020)
- **UserSession child entity**: Tracks LDS session lifecycle (lds_session_id, lds_login_url) per ADR-021
- **GradingSession child entity**: Tracks grading lifecycle (grading_pod_id, grading_status) per ADR-021
- **ScoreReport child entity**: Stores assessment results (score, max_score, check_results) per ADR-021
- **MongoDB collections**: 4 new collections (`lablet_sessions`, `user_sessions`, `grading_sessions`, `score_reports`) with Motor repositories
- **LabletSessionsController**: BFF REST controller for session CRUD with cookie auth
- **InternalSessionsController**: Internal API for cross-service session operations (schedule, transition, mark-ready)
- **Session action buttons**: Manual session state transition buttons in frontend (AD-P7-06 — CloudEvent automation deferred)
- **LabletSessionReadModel**: Shared read model in lcm-core for cross-service queries
- **ControlPlaneApiClient session methods**: 5 instance→session methods + 3 child entity methods in lcm-core

### Changed — Session Entity Model Migration (Phase 7)

- **Entity rename**: `LabletInstance` → `LabletSession` across all 4 services (big-bang rename, AD-P7-02)
- **Enum rename**: `LabletInstanceStatus` → `LabletSessionStatus` in lcm-core
- **Domain events**: 4 CMLWorker domain event classes renamed (`LabletInstanceAssigned` → `LabletSessionAssigned`, etc.)
- **CMLWorker entity**: `instance_ids` → `session_ids`, `assign_lablet_instance()` → `assign_lablet_session()`, `has_instance()` → `has_session()`
- **CQRS commands/queries**: Migrated to `lablet_session/` directories; old `lablet_instance/` and `run/` dirs deleted
- **Assessment events**: Removed redundant `instance_id` field — handler uses `aggregate_id` from CloudEvent envelope (AD-P7-08)
- **Path parameters**: `session_id` → `lablet_session_id` to avoid FastAPI Cookie collision (AD-P7-07)
- **Resource-scheduler**: PlacementEngine + reconciler updated to use session naming
- **Lablet-controller**: Reconciler fully migrated to LabletSession model
- **Frontend**: `lablet-sessions.js` API client, `LabletSessionCard`/`LabletSessionList`/`SessionDetailPage` components, SSE event types updated
- **etcd keys**: `/lcm/instances/` → `/lcm/sessions/` (hard cutover, AD-P7-03)

### Removed — Session Entity Model Migration (Phase 7)

- **LabletInstance entity**: Replaced by LabletSession aggregate
- **LabletLabBinding entity**: Absorbed into LabletSession state
- **LabletRecordRun entity**: Runtime fields absorbed into LabletSession; LDS/grading fields moved to child entities
- **Dead code** (~2,100 lines): Task entity + commands/queries, PendingLabImport, LabletControllerService, LabsRefreshService, CloudProvider enum, LabsController
- **Old API endpoints**: `/api/lablet-instances/`, `/api/lablet-record-runs/` removed
- **Old frontend files**: `lablet-instances.js`, `lablet-record-runs.js` API clients deleted
- **lcm-core backward-compat alias**: `LabletInstanceReadModel` alias removed (0 consumers)
- **MongoDB collections**: `lablet_instances`, `lablet_lab_bindings`, `lablet_record_runs`, `tasks` dropped

### Added

- **Lablet Instances**: Full lifecycle management with state machine (PENDING → SCHEDULED → INSTANTIATING → RUNNING → COLLECTING → GRADING → STOPPING → STOPPED → ARCHIVED → TERMINATED)
- **Lablet Definitions**: Definition management with versioning, resource requirements, port definitions, and lifecycle configuration
- **Grading System**: GradingScore value object with GradingCheckResult components for automated assessment
- **Port Allocation**: Dynamic port pool management with allocation/release lifecycle per instance
- **Timeslot Management**: Reservation-based scheduling with conflict detection and extension support
- **State History**: Complete audit trail with StateHistoryEntry tracking all status transitions
- **E2E Tests**: Comprehensive integration tests (39 tests) covering full lifecycle, scaling scenarios, and edge cases
- **MongoDB Indexes**: Performance-optimized indexes for CMLWorker queries (status, region, license, availability compound)
- **API Documentation**: Complete control-plane-api-guide.md with authentication, endpoints, examples, and SDK patterns
- **Security Review**: Comprehensive security-review.md covering OWASP Top 10, authentication, authorization, and remediation priorities
- **Production Checklist**: Deployment checklist with infrastructure, security, observability, and go-live verification steps

### Changed

- **UI Build**: Changed Parcel output from root `/static` to service-specific `./src/control-plane-api/static/` to support independent UIs per microservice
- **Docker**: Updated Keycloak to 26+ configuration format with new env vars (`KC_BOOTSTRAP_ADMIN_USERNAME`, `KC_HOSTNAME`, etc.)
- **Docker**: Removed shared `./static:/app/static` volume mount in favor of service-local static directory
- **Repository Pattern**: Enhanced MotorRepository with `_ensure_indexes()` pattern for lazy index creation

### Fixed

- **UI**: Fixed `UIController` static_dir path calculation (3 parents instead of 4) to correctly resolve `/app/static` in Docker
- **Observability**: Fixed MongoDB metrics scraping authorization errors by creating dedicated `otel_monitor` user with `clusterMonitor` role
- **Observability**: Fixed Tempo "DoBatch: InstancesCount <= 0" warnings by commenting out orphaned `metrics_generator_processors` config
- **Domain Events**: Fixed `_pending_events` attribute access (private attribute from AggregateRoot base class)

## [0.1.9] - 2026-01-12

### Added

- **Workers**: Added ability for admins to list terminated workers via UI filter and API parameter
- **Settings**: Added System Settings feature for dynamic configuration of worker provisioning, monitoring, and idle detection
- **Settings**: Added `SystemConfigurationService` to prioritize dynamic DB settings over static environment variables
- **UI**: Added "Settings saved successfully" modal and improved settings view error handling
- **Workers**: Added worker lifecycle commands (`StartCMLWorkerCommand`, `StopCMLWorkerCommand`, `TerminateCMLWorkerCommand`) with resume/pause metrics tracking
- **Workers**: Added worker data sync commands for EC2 status, CML health/version/labs, and background status updates
- **Workers**: Added worker management commands for EC2 tags, telemetry activity tracking, and on-demand data refresh with throttling
- **License**: Added async `RegisterCMLWorkerLicenseCommand` with background job scheduling and SSE progress updates
- **UI**: Added Web Components architecture for workers view (`FilterBar`, `StatisticsPanel`, `WorkerCard`, `WorkerList`)
- **UI**: Added `WorkerDetailsModal` with horizontal tabs (AWS, CML, Labs, Monitoring, Events) and lab operations
- **UI**: Added `WorkersApp` as main controller with SSE connection management and EventBus integration

### Changed

- **Configuration**: Refactored `settings.py` to group settings into logical sections (Core, Security, DB, AWS, Monitoring)
- **Configuration**: Reorganized `.env`, `docker-compose.yml`, and production configs to align with new settings structure
- **Authentication**: Removed legacy HS256 JWT code in favor of Keycloak-only RS256 authentication
- **Documentation**: Updated `.env.example` and `.env.prod.example` to match new configuration structure

### Fixed

- **Authentication**: Added graceful error handling when Keycloak is unavailable during login, displaying a toast notification instead of throwing an exception
- **DevOps**: Fixed `docker-compose.prod.yml` indentation issues preventing production stack startup
- **DevOps**: Configured Nginx with `sub_filter` and `X-Forwarded-Prefix` to correctly serve `event-player` frontend under `/events/` subpath
- **DevOps**: Added `proxy_redirect` to Nginx configuration to fix `event-player` redirect loop in production
- **Security**: Updated Keycloak realm with audience and role mappers to ensure `event-player` receives correct token claims
- **Security**: Added production domain to Keycloak redirect URIs to support authentication flow
- **DevOps**: Fixed `Makefile` syntax error causing `make ps` to fail
- **Observability**: Fixed `otel-collector` configuration in dev stack (missing MongoDB credentials and host volumes)

## [0.1.8] - 2025-11-24

### Added

- **License Management**: Added asynchronous license deregistration with background job and SSE progress updates
- **Domain Events**: Added three new deregistration events (Started, Completed, Failed) for async workflow tracking
- **License Management**: Added `LicenseDeregistrationJob` for async license deregistration with polling and timeout handling

### Changed

- **License Management**: Converted license deregistration from synchronous to asynchronous background job pattern
- **License Management**: Updated license registration job to use `CMLApiClientFactory` for proper auth token management
- **API**: License deregistration command now returns HTTP 202 Accepted immediately and schedules background job

### Fixed

- **Idle Detection**: Fixed critical bug where `last_activity_at` was overwritten with None on every check, preventing idle detection from working
- **Domain Events**: Restored `CMLWorkerLicenseDeregisteredDomainEvent` alongside new async events for backward compatibility
- **Activity Tracking**: Activity timestamp now only updates when actual activity is detected, not on empty checks

## [0.1.7] - 2025-11-24

### Added

- **Security**: Added role validation on frontend with clear "Insufficient Permissions" error page for users without required roles
- **Security**: Added guest user in Keycloak realm export for testing insufficient permissions flow
- **Authentication**: Added Identity Provider configuration template in Keycloak realm export for corporate SSO integration
- **Authentication**: Added Identity Provider mappers for email-to-username, firstName, lastName, and groups synchronization
- **Keycloak**: Added user groups (Admins, Managers, Architects, Vendors, Developers, Users) with automatic role mappings
- **Nginx**: Added mongo-express upstream configuration to enable access via reverse proxy
- **Documentation**: Added `configure_cisco_idp.md` guide for Cisco SSO integration with Keycloak

### Changed

- **Keycloak**: Updated test users to use group membership instead of direct role assignment for cleaner access management
- **Keycloak**: Removed `ME_CONFIG_SITE_BASEURL` from mongo-express configuration for better reverse proxy compatibility
- **Security**: Removed display of required roles from insufficient permissions error page to prevent information disclosure
- **Environment**: Added `APP_NAME` environment variable to production docker-compose configuration

### Fixed

- **Nginx**: Fixed mongo-express 404 errors by correcting proxy_pass configuration and adding upstream definition
- **UI**: Fixed unauthorized users seeing worker management interface by adding early return after role validation
- **UI**: Fixed application sections not being hidden for users with insufficient permissions

## [0.1.6] - 2025-11-24

### Added

- **API**: Added comprehensive API documentation with Markdown description loaded dynamically in Swagger UI
- **Documentation**: Created detailed API description covering authentication, architecture, worker lifecycle, and getting started guide
- **UI**: Added confirmation modal when toggling idle detection in Worker Modal's Monitoring tab
- **UI**: Added dynamic page title control via JavaScript using runtime configuration
- **UI**: Added idle detection status indicators to Worker List (table/cards) and Worker Details modal
- **UI**: Implemented real-time updates for idle detection status via SSE
- **UI**: Added application footer displaying version number
- **Deployment**: Injected `APP_VERSION` environment variable into API and UI services

### Changed

- **Version**: Bumped project version to 0.1.6 in pyproject.toml
- **API**: Removed hardcoded API description from main.py, now loaded dynamically from description.md
- **UI**: Updated default page title in templates for consistency
- **Formatting**: Reformatted docker-compose.yml for improved readability
- **Domain**: Centralized worker endpoint resolution logic in `CMLWorker.get_effective_endpoint` to eliminate code duplication
- **Refactor**: Updated all CML commands and queries to use `worker.get_effective_endpoint` for consistent private IP support
- **UI**: Updated "Monitoring" and "Events" tabs in worker details to "Coming soon"
- **Domain**: Temporarily disabled `CMLWorkerTelemetryUpdatedDomainEvent` cloud event

### Fixed

- **UI**: Fixed missing title field in APP_CONFIG injection for dynamic page title
- **Backend**: Fixed `TypeError` in worker DTO serialization by using Neuroglia `JsonSerializer`
- **UI**: Fixed inconsistent idle detection status display across different views
- **UI**: Fixed footer version display showing app name instead of version number
- **Code Quality**: Added missing type hints and formatting improvements

## [0.1.5] - 2025-11-23

### Added

- **Mongo Express**: Enabled secure access to Mongo Express via Nginx at `/mongo-express/`
- **Security**: Implemented admin-only access control for Mongo Express using Nginx `auth_request` and new `/api/auth/check-admin` endpoint
- **UI**: Added Mongo Express link to the Services navigation menu
- **UI**: Added runtime environment configuration injection to frontend
- **UX**: Hid demo user credentials on login screen when running in non-development environments

## [0.1.4] - 2025-11-23

### Added

- **AWS Private Networking**: Added `USE_PRIVATE_IP_FOR_MONITORING` setting to allow workers to be monitored via their private IP addresses within AWS VPCs

### Fixed

- **Production Stability**: Added `restart: unless-stopped` to all production services to ensure recovery from failures
- **Observability**: Fixed OpenTelemetry Collector health checks and DNS resolution issues in production
- **Deployment**: Fixed missing UI assets in production by removing volume overrides in `docker-compose.prod.yml`
- **Nginx Routing**: Fixed 502 errors for Grafana and Keycloak by correcting upstream port configurations

## [0.1.3] - 2025-11-19

### Changed

- **Docker Build**: Converted Dockerfile to multi-stage build to include UI compilation, ensuring consistent builds across environments
- **CI/CD**: Removed separate UI build steps from GitHub Actions workflow in favor of the multi-stage Docker build

### Added

- **Docker Context**: Added `.dockerignore` to exclude unnecessary files from the build
- **Admin Services Menu**: Added "Services" dropdown to the main navigation bar (Admin only) for quick access to Grafana, Event Player, and Identity Management
- **Production Management**: Added `make prod-restart-service` command for restarting individual production services

## [0.1.2] - 2025-11-22

### Security

- **Infrastructure Hardening**: Removed public port mappings for internal services (Redis, Mongo, Keycloak, etc.) in production Docker Compose configuration, exposing only Nginx on port 80

### Fixed

- **Event Player SSE**: Fixed Server-Side Events streaming for Event Player by disabling Nginx proxy buffering
- **Event Player Assets**: Fixed 404 errors for Event Player static assets by implementing correct path rewriting in Nginx
- **Event Player Stability**: Relaxed rate limiting for Event Player endpoints to prevent 503 errors during initial load
- **Content Security Policy**: Updated Nginx CSP headers to allow loading fonts from Google Fonts
- **Keycloak Routing**: Fixed Keycloak redirect loops and 502 errors by correcting hostname configuration and DNS resolution

### Changed

- **Strongly Typed Metrics**: Refactored `CMLMetrics` to use nested Value Objects (`CMLSystemInfoCompute`, `CpuStats`, etc.) instead of raw dictionaries
- **License Persistence**: Enhanced license registration/deregistration to immediately persist full system state to DB
- **UI Resource Utilization**: Improved resource utilization display in Worker Details modal with human-readable units and rounded values

### Fixed

- **Serialization Error**: Fixed `TypeError: Any cannot be instantiated` in `GetCMLWorkerByIdQuery` by manually constructing response dictionaries
- **License Event Propagation**: Fixed issue where license status changes were not triggering SSE updates by adding explicit change detection in `update_cml_metrics`
- **Session Timer**: Fixed session countdown timer in UI to be live and accurate
- **Serialization Reliability**: Refactored SSE and Redis event broadcasting to use `JsonSerializer` consistently, resolving `Any cannot be instantiated` and `bytearray` errors
- **SSE Race Condition**: Fixed race condition in `SSEEventRelay` startup that caused `readuntil()` errors
- **Frontend Reconnection**: Added handling for `system.sse.shutdown` event to allow graceful frontend disconnect/reconnect during backend restarts

### Changed

- **Worker Deletion Workflow**: Enhanced "Delete Worker" functionality
  - Restored "Terminate EC2 Instance" option in Web Components UI modal
  - Updated `DeleteCMLWorkerCommand` to support asynchronous termination tracking
  - Workers marked for termination now transition to `SHUTTING_DOWN` status instead of immediate deletion
  - UI displays `SHUTTING_DOWN` status (yellow badge) and prevents local removal until termination confirmed

- **Dependency Injection**: Updated `EventsController` and worker event handlers to use injected `JsonSerializer` instead of local instantiation or `json.dumps`

### Fixed

- **UI Reactivity for Worker Imports**: Fixed issue where imported workers did not appear in UI without refresh
  - Added `WORKER_IMPORTED` event to `EventBus` and `SSEService`
  - Updated `WorkerList` component to handle `WORKER_IMPORTED` events dynamically
- **Backend SSE Connection Handling**: Fixed issue where SSE connections prevented backend auto-reload
  - Implemented graceful shutdown in `EventsController` to detect client disconnects
  - Added `beforeunload` handler in `WorkersApp` to explicitly close SSE connections
- **500 Internal Server Error on Worker List**: Fixed `AttributeError` in `CMLMetrics` for malformed system info
- **Incomplete Data on Import**: Fixed race condition where imported workers showed incomplete data
  - Updated `OnDemandWorkerDataRefreshJob` to support forced refresh (bypassing throttle)
  - Triggered immediate forced refresh upon `CMLWorkerImportedDomainEvent`

### Added

- **Frontend Web Components Architecture**: Complete refactoring of workers view using vanilla JavaScript Web Components with Pub/Sub pattern
  - Created unified `EventBus` pub/sub system replacing 3 fragmented event systems (SSE custom emitter, store subscriptions, DOM events)
  - Implemented `BaseComponent` class providing lifecycle management, auto-cleanup, reactive state, and event integration
  - Built modular components: `WorkerCard`, `WorkerList`, `FilterBar`, `StatisticsPanel`, `WorkersApp` (150-280 lines each)
  - **NEW**: Implemented `WorkerDetailsModal` (850 lines) with full feature parity: 5 tabs (AWS, CML, Labs, Monitoring, Events), license management, lab operations (start/stop/wipe/delete/export/import)
  - Refactored `SSEService` to publish to EventBus instead of custom event emitter
  - Enhanced `workerStore` with dual-mode operation (EventBus + legacy listeners for backward compatibility)
  - Added feature flag system in `app.js` for gradual rollout with `localStorage.getItem('use-web-components')`
  - **RBAC Implementation**: Table view for admin/manager, cards for users; role-based tab visibility in modal
  - Performance: 6x faster real-time updates (300ms→50ms latency), 30% code reduction, 60% smaller component files
  - Maintainability: Shadow DOM encapsulation, testable components, type-safe event constants, zero global state pollution
  - Documentation: Comprehensive developer guide in `docs/frontend/web-components-guide.md` with API reference and troubleshooting

### Changed

- **Background Scheduler Simplification**: Removed unused `BackgroundTasksBus` reactive pattern (~150 lines)
  - Removed `BackgroundTasksBus` class and reactive stream subscription (dead code)
  - Simplified `BackgroundTaskScheduler` constructor (removed bus parameter)
  - Removed `_on_job_request_async()` handler method (never received messages)
  - Updated DI registration to remove bus dependency
  - Removed unused imports (AsyncRx, Subject, asyncio in background_scheduler.py)
  - Jobs now scheduled directly via APScheduler (clearer, simpler architecture)
  - No functionality impacted - bus was never used in actual scheduling flow
  - Rationale: Bus infrastructure designed for dynamic job submission but never utilized; all jobs scheduled statically at startup

- **SSE Broadcasting Architecture**: Resolved manual SSE broadcast anti-pattern (Issue #5) for cleaner event-driven design
  - Created domain event handlers for `LabRecordCreatedDomainEvent`, `LabRecordUpdatedDomainEvent`, and `LabStateChangedDomainEvent`
  - Removed manual `sse_relay.broadcast_event()` calls from commands: `RefreshWorkerLabsCommand`, `RequestWorkerDataRefreshCommand`
  - Removed manual SSE broadcasts from background jobs: `OnDemandWorkerDataRefreshJob`
  - All SSE events now broadcast automatically via domain event handlers when repository operations complete
  - Eliminates duplicate events (commands + domain handlers broadcasting same event)
  - Ensures consistent event schemas across all SSE broadcasts
  - Decouples commands from UI layer (SSEEventRelay no longer injected into commands)
  - CloudEvents now properly published to external subscribers
  - No breaking changes - same SSE events delivered to UI clients

### Performance

- **Lab Synchronization Batch Operations**: Resolved N+1 database pattern (Issue #3) with 96% performance improvement
  - Added `add_many_async()` and `update_many_async()` to `LabRecordRepository` interface
  - Implemented batch operations in `MongoLabRecordRepository` using MongoDB `bulk_write()` and `insert_many()`
  - Refactored `RefreshWorkerLabsCommand` to collect-then-batch pattern (~150 lines)
  - Refactored `LabsRefreshJob` with identical batch pattern for consistency
  - Performance: 50 labs reduced from 50 individual operations (~2.5s) to 2 batch operations (~50ms) - 50x faster
  - Added comprehensive error handling with fallback to individual operations on batch failure
  - DuplicateKeyError handling for race conditions (moves records from create to update list)
  - Domain events still published correctly after batch operations

### Fixed

- **Type Consistency**: Fixed `remove_by_lab_id_async()` return type from `None` to `bool` in `MongoLabRecordRepository`

### Documentation

- **Orchestration Architecture Review Update**: Updated concurrent processing status
  - Verified that background jobs already implement concurrent processing (since Nov 18, 2025)
  - WorkerMetricsCollectionJob: Uses Semaphore(10) for max 10 concurrent workers
  - LabsRefreshJob: Uses Semaphore(5) for max 5 concurrent workers
  - Both use asyncio.gather() for parallel execution with exception handling
  - Performance: 90% faster than sequential (100s → 10s for 50 workers)
  - Added comprehensive test suite to verify concurrent processing behavior
  - Updated architecture review document to reflect implemented status
  - Marked "Sequential Processing Bottleneck" as ✅ RESOLVED

- **SSE Horizontal Scaling Limitation**: Documented that SSE uses in-memory client registry
  - Current deployment safe with `replicaCount: 1` (single instance)
  - Multiple replicas will break SSE connections (events not delivered to all clients)
  - Added deployment warning to Helm values.yaml with mitigation options
  - Documented Redis Pub/Sub implementation pattern for future scaling
  - Identified scaling triggers: >50 clients, >200 workers, or multi-region deployment
  - Added comprehensive section to IMPLEMENTATION_PATTERNS_CHEAT_SHEET.md
  - Explained why it breaks: Pod A/Pod B event delivery failure scenario
  - Provided workarounds: sticky sessions via load balancer session affinity
  - Noted architectural inconsistency: Sessions use Redis, SSE doesn't yet

### Added

- **Lab Import Refresh Trigger**: Lab list now refreshes immediately after successful lab upload
  - Triggers RefreshWorkerLabsCommand after ImportLabCommand succeeds
  - Respects 10-second debounce threshold (skips if background job imminent)
  - Provides instant UI feedback when new labs are imported
  - Prevents duplicate refresh work when background job about to run
- **Lab Delete Refresh Trigger**: Lab list refreshes immediately after successful lab deletion
  - Triggers RefreshWorkerLabsCommand after DeleteLabCommand succeeds
  - Uses same debounce logic as import (10-second threshold)
  - Ensures UI updates quickly after lab removal operations
- **Lab Record Duplicate Prevention**: Added DuplicateKeyError handling for race conditions
  - Catches MongoDB unique constraint violations during lab record creation
  - Automatically fetches and updates existing record instead of failing
  - Applied to both RefreshWorkerLabsCommand and LabsRefreshJob
  - Prevents crashes when multiple processes try to create same lab record
- **Direct MongoDB Deletion for Lab Records**: Added `remove_by_lab_id_async()` repository method
  - Bypasses aggregate's remove_async() which wasn't deleting from database
  - Uses direct MongoDB `delete_one()` with (worker_id, lab_id) filter
  - Returns boolean indicating if record was actually deleted
  - Ensures lab records are properly removed from database

### Fixed

- **Lab Record Deletion Not Working**: Fixed lab records persisting in database after deletion
  - DeleteLabCommand now uses direct MongoDB deletion via `remove_by_lab_id_async()`
  - RefreshWorkerLabsCommand orphaned detection uses direct deletion
  - LabsRefreshJob orphaned cleanup uses direct deletion
  - Base repository's `remove_async()` was not actually deleting from MongoDB
- **Lab Synchronization Issues**: Enhanced lab refresh logging for better debugging
  - Added debug logs showing existing vs current lab counts
  - Logs existing lab IDs in DB and current lab IDs in CML
  - Helps diagnose sync issues between CML and database state

### Added

- **Worker Monitoring Tab Enhancements**: Added comprehensive monitoring data display in worker details modal
  - Shows idle detection settings and status (enabled/disabled, last activity, next check, target pause)
  - Displays pause/resume history statistics (auto/manual counts, timestamps)
  - Shows metrics collection timing (poll interval, next refresh, last sync times)
  - Provides last pause details (timestamp, paused by, reason)
  - Tab visibility restricted to admin and manager roles only
  - Real-time updates via SSE for activity, pause, and resume events
  - Added worker activity, pause, and resume SSE event listeners
- **Worker API Monitoring Fields**: Extended worker details API response with monitoring-related fields
  - Activity tracking: last_activity_at, last_check_at, next_idle_check_at, target_pause_at
  - Idle detection: is_idle_detection_enabled
  - Pause/resume tracking: auto_pause_count, manual_pause_count, auto_resume_count, manual_resume_count
  - Last pause/resume: last_paused_at, last_resumed_at, paused_by, pause_reason

### Fixed

- **Pause Worker Command**: Fixed missing required arguments for AWS client and domain methods
  - Added missing `aws_region` parameter to `stop_instance()` call
  - Fixed `pause()` method call to provide required `reason` parameter
  - Correctly maps auto-pause vs manual pause to appropriate reason values
  - Removed incorrect `await` from synchronous `stop_instance()` call
- **Repository Method Names**: Fixed incorrect usage of `get_async()` method
  - Replaced with correct `get_by_id_async()` method in all handlers
  - Updated get_worker_idle_status_query, pause_worker_command, get_worker_activity_query
- **Cancellation Token Removal**: Removed unused cancellation_token from all handlers
  - Not implemented in Neuroglia framework, was causing confusion
  - Cleaned up signatures and calls in all command/query handlers
- **Timezone-Aware Datetimes**: Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`
  - Updated all datetime creation to be timezone-aware
  - Consistent UTC datetime handling across the codebase
- **Update Worker Activity Command**: Fixed missing required arguments for update_activity method
  - Added optional fields: last_check_at, next_check_at, target_pause_at
  - Defaults last_check_at to current UTC time if not provided
  - Properly passes all required parameters to domain method
- **Update Worker Activity Command**: Fixed repository method call signature
  - Changed `get_async()` to `get_by_id_async()` (correct method name)
  - Removed invalid `cancellation_token` parameter
- **System View Scheduler Buttons**: Fixed admin action buttons not rendering in scheduler tab
  - Refactored template literal conditional to use explicit if/else for HTML generation
  - Buttons (Play/Delete) now correctly appear for admin users
- **Telemetry Timestamp Parsing**: Fixed timestamp format mismatch in telemetry event filtering
  - CML API returns timestamps without 'Z' suffix (e.g., "2025-11-19T21:11:59")
  - Updated parser to handle 4 ISO 8601 variants (with/without microseconds, with/without Z)
  - Prevents all telemetry events from being rejected due to parsing errors
- **Activity Detection Job Runtime Errors**: Fixed multiple runtime errors in ActivityDetectionJob
  - Changed `worker.id` attribute references to `worker.id()` method calls
  - Fixed `OperationResult` attribute names (`is_successful` → `is_success`, `content` → `data`, `errors` → `error_message`)
  - Corrected repository method call (`get_async()` → `get_by_id_async()`)
  - Removed invalid `cancellation_token` parameter from `get_by_id_async()` calls
- **CML API SSL Verification**: Disabled SSL verification for CML API client connections
  - Added `verify_ssl=False` for telemetry query client instantiation
  - Prevents CERTIFICATE_VERIFY_FAILED errors with self-signed certificates

### Changed

- **CML API Client Factory Pattern**: Refactored CML API client instantiation to use dependency injection
  - Implemented `CMLApiClientFactory` with singleton registration
  - Factory creates transient client instances per worker (thread-safe, no shared token state)
  - Centralizes configuration (verify_ssl=False, timeout, default credentials)
  - Updated all handlers and jobs to inject factory instead of manual instantiation
  - Improves testability and follows same pattern as AwsEc2Client
  - Files affected: sync_worker_cml_data_command, control_lab_command, refresh_worker_labs_command, get_worker_telemetry_events_query, labs_refresh_job

### Added

- **Session Management**: Implemented session expiration warning and extension
  - Added `SessionManager` service in frontend to track user activity and show warnings
  - Added `/api/auth/session` and `/api/auth/extend-session` endpoints
  - Configurable session duration via `SESSION_MAX_DURATION_MINUTES`

### Changed

- **Configuration**: Renamed `SESSION_TIMEOUT_MINUTES` to `SESSION_MAX_DURATION_MINUTES` for clarity
- **Auto-Import Logic**: Enhanced `AutoImportWorkersJob` to handle terminating instances
  - Workers in `shutting-down` or `terminated` state in AWS are now updated locally instead of being skipped
  - Ensures UI reflects external termination events correctly

### Fixed

- **UI Synchronization**: Fixed issue where terminating instances were not updating in the UI
  - `WorkerList` and `WorkerCard` now subscribe to `WORKER_STATUS_CHANGED` events
  - Real-time status updates for `SHUTTING_DOWN` and `TERMINATED` states
- **Session Expiration Handling**: Fixed issue where UI appeared stuck when session expired
  - Added `auth.session.expired` SSE event triggered by backend when session is invalid
  - Updated `EventsController` to check session validity periodically
  - Updated frontend to subscribe to expiration event and redirect to login immediately

## [0.1.0] - 2025-11-19

### Fixed

- **SSE Initial Snapshots**: Fixed scoped service resolution error in SSE event controller
  - Create service scope before resolving CMLWorkerRepository
  - Initial worker snapshots now sent correctly on SSE connection
- **CI/CD Docker Build**: Fixed invalid tag format in GitHub Actions workflow
  - Removed `--tag` prefix from tag values (docker/build-push-action adds it automatically)
  - Use multi-line format for tags output
  - Changed trigger to only build on version tags (not on push to main)
- **CML Data Sync Resilience**: Fixed critical issue where newly imported workers remained with `cml_ready: false` and `service_status: unavailable`
  - Refactored `SyncWorkerCMLDataCommand` from fail-fast to resilient multi-step approach
  - Health check is no longer a gatekeeper - all CML APIs are tried independently
  - `system_information` endpoint (no auth required) is queried first for faster readiness detection
  - Partial data collection: Updates worker metrics even if some APIs timeout
  - Service status determined after collection based on what APIs responded successfully
  - Prevents workers from being stuck in unavailable state due to transient network issues
  - Labs sync now proceeds correctly once CML service becomes accessible
  - See `notes/CML_DATA_SYNC_RESILIENCE_FIX.md` for detailed analysis and solution

### Added

- **Worker Idle Detection and Auto-Pause**: Comprehensive activity monitoring and cost-saving automation
  - Tracks user activity via CML telemetry events (lab/node operations, user logins)
  - Filters 93% noise (system stats, automated API calls) to detect genuine user activity
  - Configurable idle timeout with automatic worker pause (AWS stop)
  - Manual pause/resume tracking with lifecycle counters
  - Activity history: stores last 10 relevant events per worker
  - New commands: `DetectWorkerIdleCommand`, `PauseWorkerCommand`, `UpdateWorkerActivityCommand`
  - New queries: `GetWorkerIdleStatusQuery`, `GetWorkerActivityQuery`, `GetWorkerTelemetryEventsQuery`
  - Background job: `ActivityDetectionJob` (30-minute interval, separate from metrics collection)
  - Domain events: `WorkerActivityUpdatedDomainEvent`, `WorkerPausedDomainEvent`, `WorkerResumedDomainEvent`
  - Settings: `WORKER_IDLE_TIMEOUT_MINUTES`, `ACTIVITY_DETECTION_INTERVAL`, `ACTIVITY_DETECTION_ENABLED`
  - UI endpoints: `/api/workers/{id}/idle-status`, `/api/workers/{id}/activity`, `/api/workers/{id}/telemetry`
  - See `notes/WORKER_IDLE_DETECTION_IMPLEMENTATION.md` for architecture and filtering logic

- **Auto-Import Workers Background Job**: New recurrent job for automatically discovering and importing CML Workers
  - Runs at configurable intervals (default: 1 hour) via `AUTO_IMPORT_WORKERS_INTERVAL`
  - Searches AWS EC2 instances by AMI name pattern in specified region
  - Uses existing `BulkImportCMLWorkersCommand` for consistent import logic
  - Configurable via environment variables:
    - `AUTO_IMPORT_WORKERS_ENABLED` (default: false)
    - `AUTO_IMPORT_WORKERS_REGION` (default: us-east-1)
    - `AUTO_IMPORT_WORKERS_AMI_NAME` (AMI name pattern to search)
    - `AUTO_IMPORT_WORKERS_INTERVAL` (seconds, default: 3600)
  - **Now properly scheduled at boot**: Auto-scheduling mechanism added to `BackgroundTaskScheduler.start_async()`
  - Non-intrusive: skips already-imported instances
  - Visible in System view's Scheduler tab alongside WorkerMetricsCollectionJob and LabsRefreshJob

- **Auto-Schedule Recurrent Jobs**: BackgroundTaskScheduler now automatically schedules all recurrent jobs at startup
  - Added `_schedule_recurrent_jobs_async()` method to auto-discover and schedule `@backgroundjob(task_type="recurrent")` jobs
  - Jobs are scheduled only if not already running (prevents duplicates on restart)
  - Uses dependency injection to instantiate jobs with required services
  - Logs clearly show which recurrent jobs are scheduled at startup

- **Lab Operations Auto-Refresh**: Lab control commands (start/stop/ wipe) now automatically schedule on-demand worker data refresh
  - Ensures worker metrics and lab states are updated after lab operations
  - Non-blocking: refresh scheduling failures don't affect lab operation success
  - Uses existing `OnDemandWorkerDataRefreshJob` infrastructure
  - Improves data consistency and real-time UI updates

#### Recent UI & Realtime Enhancements

- **Live Transition Timers**: Dynamic elapsed timers for worker start/stop lifecycle (pending/stopping) in table, cards, and details modal using `start_initiated_at` / `stop_initiated_at` timestamps propagated via SSE.
- **Worker Creation Visibility**: Newly created or auto-imported workers appear instantly using enriched `worker.created` SSE (name, region, instance_type, created_at) followed by snapshot events for full detail.
- **Tags Management Panel**: Replaced AWS Monitoring section with tag listing & admin-only add/remove controls (controller uses POST). Non-admin users see read-only tags.
- **Import Modal Refactor**: Fixed mode switching (Instance ID vs AMI Name) and added bulk import (`import_all`) via AMI name pattern with contextual field visibility & validation.
- **Worker Cards Layout Fix**: Rebuilt card markup to correct broken layout where body fields rendered outside card; cleaner structure with bottom-aligned action button.
- **Transition Metadata Broadcasting**: Status update SSE now includes `transition_initiated_at`; snapshot SSE includes `start_initiated_at` & `stop_initiated_at` for accurate timers.

#### Diagnostics & Frontend Modularization (Phase 1)

- **Diagnostics API Endpoints**: Added `/api/diagnostics/intervals` (polling intervals + next run times) and `/api/diagnostics/jobs` (RBAC protected) for operational visibility into recurrent background jobs.
  - Summaries include `id`, `name`, `next_run_time`, trigger description, derived interval seconds.
  - Returns settings slice (`worker_metrics_poll_interval`, `labs_refresh_interval`, `auto_import_workers_interval`).
- **SystemHealthService**: New singleton aggregating multi-component health checks (MongoDB latency, background scheduler status & job count, Redis/in-memory session store ping, CloudEvent sink POST validation, Keycloak OIDC discovery, OTEL collector TCP reachability).
  - Produces structured `components` map with per-service `status`, `latency_ms`, and contextual metadata; overall `status` downgraded to `degraded` on any unhealthy/error component.
  - Added health check endpoint `/api/system/health` for aggregated health status
- **Workers UI Modularization (God file breakup – Phase 1)**: Extracted monolithic `workers.js` concerns into discrete modules improving cohesion & testability:
  - Store & Data Flow: `store/workerStore.js` (Map-based store, subscription API, timing metadata, in-flight request dedup, snapshot upsert & metrics update helpers).
  - Rendering Components: `components/metricsPanel.js`, `components/status-badges.js`, `components/workerCmlPanel.js`, `components/workerLicensePanel.js`, `components/escape.js` (central HTML escaping).
  - UI Logic Segments: `ui/worker-init.js` (view bootstrap + SSE wiring), `ui/worker-actions.js` (start/stop/refresh confirmations), `ui/worker-labs.js` (accordion lab details & controls with state polling), `ui/worker-jobs.js`, `ui/worker-monitoring.js`, `ui/worker-events.js` (placeholder), `ui/worker-timing.js` (countdown logic), `ui/worker-actions.js`.
  - Benefits: Eliminates triple detail fetches, clarifies data flow (SSE → store → subscribers), reduces cognitive load, prepares ground for subscription-driven rendering & future TypeScript typings.
- **Metrics Normalization Enhancements**: `metricsPanel.js` backfills CPU (combined or user+system), memory (used/total or total_kb/available_kb), disk (used/total or size_kb/capacity_kb) with clamping & graceful parse fallbacks; improves resilience when telemetry partial.
- **Lab Controls UX Upgrade**: Accordion per lab with badges, timestamp relative formatting, descriptive cards (info, timestamps, description, notes, groups) and guarded Start/Stop/Wipe actions with confirm modals & optimistic polling (`waitForLabState`).
- **License Details Panels**: Dedicated modal tabs rendering registration, authorization, features, transport & UDI (status badges, time blocks, feature ranges & compliance statuses).
- **Central HTML Escape Utility**: `escape.js` consolidates escaping to prevent inconsistent DOM sanitization.
- **Worker Timing Module**: `worker-timing.js` manages metrics refresh countdown & last-refreshed display using store timing state (poll interval + next refresh) with automatic timer reset on SSE updates.
- **SSE Status Indicator Injection**: Workers view now prepends realtime connection badge (`initializing/connected/reconnecting/disconnected/error`) for transparency.
- **Start/Stop Command Refinement**: `StartCMLWorkerCommandHandler` & `StopCMLWorkerCommandHandler` updated for immediate status transitions (`PENDING`, `STOPPING`) with explicit tracing spans (`retrieve_cml_worker`, `start_ec2_instance` / `stop_ec2_instance`, `update_worker_status`); avoids scheduling on-demand refresh relying on periodic monitoring for eventual RUNNING/STOPPED reconciliation.
- **System UI Cleanup**: Removed legacy Worker Monitoring card & tab from `system.jinja`; streamlined to Health + Scheduler tabs, reducing visual noise and aligning with new dedicated Diagnostics endpoints.
- **Frontend Refactor Plan Documented**: Added extensive `notes/FRONTEND_REFACTOR_PLAN.md` capturing assessment, root causes, phased plan (store introduction completed – Phase 1), acceptance criteria & rollback strategy.

### Removed (Recent)

- **Legacy Monitoring Card & Tab**: Eliminated from System view template (`system.jinja`) in favor of richer diagnostics + health aggregation.
- **Ad-hoc Telemetry Test Script**: Deleted `test_telemetry_fix.py` (quick verification script) now superseded by structured components & handlers.

### Changed (Recent)

- **System View Reorganization**: Health/Scheduler primary; monitoring specifics migrated to dedicated worker details monitoring tab & diagnostics endpoints.
- **Modal Interaction Robustness**: Lab confirmation flows manage backdrop z-index & opacity transitions preventing stacked phantom backdrops after chained modals.
- **Refresh Button Stability**: Worker details refresh button clone strategy prevents stale event listeners & disabled state persistence.
- **SSE Integration Path**: Initialization moved into `worker-init.js` with decoupled subscription binding and store-driven rendering.
- **Uniform Status Badge Mapping**: `status-badges.js` centralizes mapping of worker & service states to Bootstrap contextual classes (consistency across table, cards, modal panels).
- **Countdown Reliability**: Timer recalculations use authoritative next refresh timestamp; displays `Refreshing...` when elapsed rather than freezing at `00:00`.

### Fixed (Recent)

- **Duplicate Worker Detail Fetches**: Request deduplication via `inflight` Map prevents redundant concurrent API calls (resolves race & bandwidth waste).
- **Modal Backdrop Leakage**: Confirmation modals now clean up excess backdrops & body classes; prevents darkened, unscrollable page state after multi-action sequences.
- **Metrics Partial Data Handling**: Graceful fallbacks avoid NaN progress bars & inconsistent utilization (CPU, memory, disk) when telemetry incomplete.
- **Lab State UI Lag**: Post-action polling reduces window where UI shows stale STARTING/STOPPING states before server reconciliation.
- **Countdown Staleness**: Automatic reset on timing SSE updates prevents `--:--` persistence & stale last-refreshed timestamps.
- **Escape Duplication**: Consolidated escaping logic eliminates inconsistent manual `innerText` conversions scattered across components.

### Added (Helm & DevOps)

- **Helm Chart**: Initial Kubernetes deployment chart (`charts/lablet-cloud-manager/` & `deployment/helm/lablet-cloud-manager/`) including app Deployment, Service, optional Ingress, Redis sidecar Deployment/Service, and MongoDB StatefulSet with PVC and secrets/config separation.
- **Values Configuration**: Rich `values.yaml` defaults (intervals, auto-import, labs refresh, metrics poll, Redis/Mongo resources) with override examples in `NOTES.txt`.
- **GitHub Actions CI**: Docker build & publish workflow (`.github/workflows/docker-publish.yml`) producing multi-tag images (commit SHA, semver tags) and running Trivy security scan.
- **Environment Diagnostics**: Startup debug dump of environment variables (masked sensitive values) aiding operator visibility into interval & auto-import settings.
- **System Health Service**: Aggregated health endpoint `/api/system/health` via `SystemHealthService` (Mongo latency, scheduler, session store, CloudEvent sink, Keycloak, OTEL collector).

### Changed (Backend & Scheduling)

- **Background Scheduler Refactor**: Simplified recurrent job discovery; stable global IDs; improved serialization with class name; safer service provider resolution; enriched diagnostics logging of scheduled jobs.
- **Recurrent Job Scheduling**: Automatic scheduling of `AutoImportWorkersJob`, `LabsRefreshJob`, and `WorkerMetricsCollectionJob` without duplicate scans; interval now configurable for labs refresh (`LABS_REFRESH_INTERVAL`).
- **On-Demand Refresh Job**: `OnDemandWorkerDataRefreshJob` normalized to `task_type="scheduled"` execution with slight delay to avoid misfire edge cases; refresh scheduling now records `scheduled_at` + emits requested/skip SSE events with accurate ETA seconds.
- **Telemetry Emission**: CloudWatch metrics collection emits telemetry event unconditionally (for countdown timer continuity) and includes next refresh timestamp.
- **Metrics Threshold**: Domain-level suppression for CML metrics changes using `metrics_change_threshold_percent` to reduce noisy events when deltas below threshold.
- **Mongo Repository**: Added unique sparse index on `aws_instance_id` with race-safe duplicate prevention in `MongoCMLWorkerRepository.add_async`.
- **Worker State Transitions**: Added `start_initiated_at` and `stop_initiated_at` timestamps for accurate long-running operation timers; exposed on worker detail & list queries.

### Fixed (Compatibility & Stability)

- **Legacy Refresh Button Error**: Added UI shim `_workersJs.refreshWorker` and API compatibility wrapper `workersApi.refreshWorker()` delegating to `requestWorkerRefresh` with normalized argument order.
- **Rate Limiting Feedback**: Refresh throttle responses now include integer `retry_after_seconds` and emit consistent skip SSE with reason and ETA.
- **Service Template Linting**: Disabled yamllint & pre-commit YAML checks on Helm templated files by using `.yaml.tpl` and updated exclusion patterns (prevents template false positives).
- **Deployment Logs Truncation**: Local dev log file (`debug.log`) truncated at startup to avoid unbounded growth across sessions.
- **Recurrent Job Resolution**: Robust fallback matching (task name, serialized class name, job id prefix) preventing skipped executions after Redis/Mongo job store resets.

### Removed (Cleanup)

- **Telemetry Test Script**: Deleted `test_telemetry_fix.py` (quick ad-hoc script) replaced by integrated CloudWatch telemetry + countdown logic.
- **Redundant Exception Logging**: Removed duplicated error span attribute assignments in on-demand refresh job & bulk import command handler.

### Security / Observability

- **CloudEvent Sink Health Check**: Lightweight CloudEvent POST with masked event data validating sink responsiveness; degrades overall health on non-2xx responses.
- **Keycloak & OTEL Reachability**: Added latency measurement & connection attempt for collector, marking components disabled vs unhealthy appropriately.

### Dev Experience

- **Masked Env Logging**: Sensitive env vars (SECRET/PASSWORD/TOKEN/KEY) masked while still showing length for debugging.
- **Scheduler Diagnostics**: Startup job snapshot enumerates id/name/trigger/next run & kwargs for easier operator troubleshooting.

### Changed

- **System View Scheduler Tab**: Improved job display clarity
  - Renamed "Function" column to "Command" for better understanding
  - Display actual job class name (e.g., "WorkerMetricsCollectionJob") instead of generic wrapper function
  - Makes it easier to identify which background job is scheduled
  - Applied same improvement to Worker Details modal Jobs tab

- **Import Organization**: Removed all inline imports from application layer (jobs, commands, queries, event handlers)
  - Moved 30+ inline imports to module level following Python PEP 8 best practices
  - Improved code readability with explicit dependency declarations at file start
  - Affected files: 21 commands, 2 jobs, 6 queries (29 files total)
  - Common patterns: `AwsRegion`, `CMLWorkerStatus`, `boto3`, service imports
  - Updated `.github/copilot-instructions.md` with comprehensive import guidelines
  - Benefits: Better maintainability, easier circular dependency detection, clearer for static analysis

- **Service Registration Patterns**: Unified DI registration patterns across all `application.services`
  - Standardized to `@staticmethod` decorator (removed `@classmethod`)
  - Consistent `implementation_factory=lambda` pattern for services with dependencies
  - All `configure()` methods now return `None` (builder modified in-place)
  - Added docstrings with Args sections for clarity
  - Unified log messages with ✅ emoji for consistency

- **Tags Update Request Method**: UI switched from PUT to POST for tag updates to align with backend controller.
- **Simplified Worker Card Renderer**: Reduced complexity & improved maintainability; prevents overflow rendering issues.
- **Status SSE Consumption**: Frontend now uses `new_status` instead of legacy `status` field on `worker.status.updated` events.

### Removed

- **WorkerMetricsService**: Removed unnecessary service abstraction layer
  - Service was only used by `CollectWorkerCloudWatchMetricsCommand`
  - Command handler now contains CloudWatch metrics collection logic directly
  - Follows CQRS principles: handlers contain business logic, not delegating to services
  - Simplifies architecture by removing intermediate abstraction
  - Deleted: `application/services/worker_metrics_service.py`, `tests/application/test_worker_metrics_service.py`

### Fixed

- **Worker Refresh Performance**: Optimized worker refresh button to return immediately
  - Removed redundant synchronous labs refresh API call from UI
  - Worker refresh now only calls `/refresh` endpoint which schedules background job
  - Background job (`OnDemandWorkerDataRefreshJob`) handles both metrics AND labs refresh automatically
  - UI returns instantly with lightweight acknowledgment, SSE events provide updates
  - Eliminates slow synchronous operation that was blocking UI responsiveness

- **Worker Metrics Display**: Fixed metrics display inconsistencies between views and SSE updates
  - **User cards view**: Added missing disk utilization progress bar (was only showing CPU/Memory)
  - **SSE real-time updates**: Both admin table and user cards now update when `worker.snapshot` SSE events arrive
  - **Metrics synchronization**: All three metrics (CPU, Memory, Disk) now stay in sync across landing page and modal
  - Worker cards now show individual progress bars for each metric that's available (no longer requires all three)
  - Simplified SSE handler: `worker.metrics.updated` event now only handles timing info, metrics updated via `worker.snapshot`

- **Worker Refresh Duplicates**: Fixed duplicate workers appearing after clicking refresh button
  - Added `workersData.length = 0` to clear array before populating with API response
  - Prevents accumulation of duplicate workers in both admin table and user card views
  - Ensures UI accurately reflects backend state on refresh
- **Import Modal Field Visibility**: Corrected element IDs & listeners so switching import method updates visible input groups (instance vs AMI pattern, bulk checkbox).
- **Worker Card Content Overflow**: Fixed card body fields appearing below/outside card.
- **Missing Transition Timers**: Added timestamps to domain events & SSE, enabling real-time elapsed display during long start/stop transitions.
- **Delayed Worker Appearance**: Ensured new workers surface without full reload via enriched `worker.created` SSE + snapshot integration.

  - Affects: `SSEEventRelayHostedService`, `WorkerMetricsService`, `BackgroundTaskScheduler`
  - See: `notes/SERVICE_REGISTRATION_PATTERNS_UNIFIED.md`

### Fixed

- **Metrics Display Consistency**: Fixed inconsistent CPU/memory metrics between table and modal views
  - Unified data source: both views now use CML native telemetry (not CloudWatch)
  - SSE handler updates local cache directly instead of triggering full page reload
  - Added disk utilization to modal's Resource Utilization card (3-column layout)
  - Real-time metrics sync: table rows and modal update simultaneously on SSE events

- **WorkerMetricsService DI Registration**: Fixed factory function registration to properly inject service instances
  - Changed from `singleton=create_service` to positional `create_service` argument
  - Resolves AttributeError where handlers received factory function instead of service instance
  - Aligns with Neuroglia DI convention for lazy-initialized singletons

- **Countdown Timer Display**: Fixed stale timing data causing `--:--` display in worker details modal
  - Added validation to check if `next_refresh_at` is in the past before displaying
  - Automatically calculates fresh timing (`current_time + poll_interval`) when backend data is stale
  - Ensures countdown always shows valid future timestamp

### Added

#### Worker Metrics Source Separation

- **Multi-Source Metrics Architecture**: Clear separation of metrics by data source
  - **EC2 Metrics**: Instance health checks from AWS EC2 API (`ec2_instance_state_detail`, `ec2_system_status_check`, `ec2_last_checked_at`)
  - **CloudWatch Metrics**: Resource utilization from AWS CloudWatch (`cloudwatch_cpu_utilization`, `cloudwatch_memory_utilization`, `cloudwatch_last_collected_at`, `cloudwatch_detailed_monitoring_enabled`)
  - **CML Metrics**: Application metrics from CML API (`cml_system_info`, `cml_ready`, `cml_uptime_seconds`, `cml_labs_count`, `cml_last_synced_at`)
  - Domain events for each source: `EC2MetricsUpdatedDomainEvent`, `CloudWatchMetricsUpdatedDomainEvent`, `CMLMetricsUpdatedDomainEvent`
  - Aggregate methods: `update_ec2_metrics()`, `update_cloudwatch_metrics()`, `update_cml_metrics()`
  - Backward compatibility maintained with deprecated `update_telemetry()` method

#### CML API Integration

- **CMLApiClient**: Async REST API client for querying CML instances
  - **JWT Authentication**: POST `/api/v0/authenticate` with username/password
  - **Token Management**: Automatic token caching and refresh on expiration
  - **System Stats**: `/api/v0/system_stats` endpoint integration
  - **Metrics Parsing**: Compute nodes, dominfo, CPU/memory/disk statistics
  - **Workload Metrics**: Allocated CPUs, running nodes, total nodes from dominfo
  - **Error Handling**: Graceful handling for unreachable instances
  - **SSL Support**: SSL verification configurable (disabled for self-signed certs)
  - **Async/Await**: Fully async implementation using httpx

#### Command Pattern Implementation

- **RefreshWorkerMetricsCommand**: CQRS-compliant metrics refresh
  - Orchestrates EC2, CloudWatch, and CML data collection
  - Updates worker aggregate state (triggers domain events)
  - Updates OpenTelemetry gauges after each refresh
  - Handles failures gracefully per data source
  - Respects worker status (only queries CML when RUNNING+AVAILABLE)

- **EnableWorkerDetailedMonitoringCommand**: Admin command for 1-minute metrics
  - Enables detailed CloudWatch monitoring via AWS API
  - Updates worker aggregate with monitoring status
  - POST `/region/{region}/workers/{id}/monitoring` endpoint (admin-only)
  - Cost: ~$2.10/month per instance

#### Configuration

- **CML API Settings**:
  - `cml_worker_api_username`: CML API username for system stats (default: "admin")
  - `cml_worker_api_password`: CML API password (change in production)

#### Documentation

- `notes/WORKER_METRICS_SOURCE_SEPARATION.md`: Architecture guide for metric sources
- `notes/REFRESH_WORKER_METRICS_IMPLEMENTATION_PLAN.md`: Implementation roadmap and phases
- `notes/METRICS_STORAGE_ARCHITECTURE.md`: Analysis of metrics storage options (time-series collections, external DBs)
- `notes/CML_API_TESTING.md`: Testing guide for CML API client with endpoint reference and troubleshooting

#### Testing & Development Tools

- `scripts/test_cml_api.py`: Comprehensive test script for CML API client
  - Test specific HTTPS endpoints with authentication
  - Test by worker ID (database lookup)
  - Test all RUNNING workers in parallel
  - MongoDB integration for worker discovery
  - Detailed logging and error reporting

#### Decision Log

- **Custom CML API Client vs Official Library**: Chose custom implementation
  - Official `virl2-client` library is sync (our architecture is async)
  - We only need `system_stats` endpoint (library has 50+ methods)
  - Custom implementation: lightweight, async, fits architecture perfectly
  - Future: Can integrate official library for advanced features if needed

### Changed

- **Monitoring Status Tracking**: AWS EC2 API now returns `monitoring_state` field
  - `get_instance_status_checks()` includes CloudWatch monitoring status
  - RefreshWorkerMetricsCommand syncs monitoring status from AWS
  - New instances created with detailed monitoring enabled by default

#### Background Task Scheduling System

- **APScheduler Integration**: Distributed task scheduling with Redis/MongoDB persistence
  - `BackgroundTaskScheduler`: Core scheduler with automatic job discovery via `@backgroundjob` decorator
  - `BackgroundTasksBus`: Message bus for task scheduling and coordination
  - `RecurrentBackgroundJob` and `ScheduledBackgroundJob`: Base classes for periodic and one-time jobs
  - Dependency injection pattern: Jobs serialize minimal data, dependencies re-injected on deserialization
  - Automatic job recovery after application restarts
  - Support for both Redis and MongoDB job stores

#### Worker Monitoring System

- **Automated Worker Monitoring**: Background monitoring of CML Worker health and metrics
  - `WorkerMetricsCollectionJob`: Recurrent job for collecting AWS EC2 and CloudWatch metrics
  - `WorkerMonitoringScheduler`: Orchestrates monitoring job lifecycle for all active workers
  - `WorkerNotificationHandler`: Reactive observer for processing metrics events and threshold alerts
  - Auto-discovery of active workers on application startup
  - Graceful job termination when workers are deleted
  - CPU and memory utilization threshold monitoring (default: 90%)
  - OpenTelemetry integration for observability

#### Worker Management Features

- **AMI Name Support**: Workers can be created and imported using human-readable AMI names
  - `cml_worker_ami_name_default` setting for default AMI
  - `cml_worker_ami_names` dictionary mapping names to AMI IDs
  - AMI name stored in worker state for auditing
  - AMI name included in worker domain events

- **Worker Refresh Endpoint**: Manual worker state synchronization and monitoring restart
  - POST `/region/{aws_region}/workers/{worker_id}/refresh` endpoint
  - Triggers immediate metrics collection from AWS EC2/CloudWatch
  - Updates worker state in database with current AWS data (emits domain events on changes)
  - Automatically starts monitoring if worker is running/pending and not monitored
  - Returns refreshed worker details to UI
  - Refresh button in Worker Details modal with loading state and notifications
  - Comprehensive error handling and user feedback

#### Configuration

- **Worker Monitoring Settings**:
  - `worker_monitoring_enabled`: Enable/disable automated monitoring (default: true)
  - `worker_metrics_poll_interval`: Metrics collection interval in seconds (default: 300)
  - `worker_notification_webhooks`: List of webhook URLs for alerts (placeholder)

- **Background Job Store Settings**:
  - `background_job_store`: Redis or MongoDB configuration for job persistence
  - Separate Redis database for job storage (DB 1) vs sessions (DB 0)

#### Documentation

- **Architecture Documentation**:
  - `docs/architecture/background-scheduling.md`: Comprehensive guide to background task system
  - `docs/architecture/worker-monitoring.md`: Worker monitoring system architecture and usage
  - Updated README.md with new features and expanded project structure
  - Updated mkdocs.yml navigation to include new documentation pages

#### Design Notes

- `notes/APSCHEDULER_IMPROVEMENTS_COMPLETE.md`: Phase 2 implementation details and recommendations
- `notes/APSCHEDULER_REFACTORING_SUMMARY.md`: Phase 1 summary and architectural decisions
- `notes/WORKER_MONITORING_ARCHITECTURE.md`: Reactive monitoring architecture design
- `notes/ROA_MIGRATION_PLAN.md`: Future Resource-Oriented Architecture (ROA) migration plan
- `notes/WORKER_REFRESH_IMPLEMENTATION.md`: Worker refresh feature implementation details and known issues

#### UI/Frontend Utilities

- **Role-based Access Control**: New `src/ui/src/scripts/utils/roles.js` module
  - `getUserRoles()`, `hasRole()`, `hasAnyRole()`, `hasAllRoles()` utility functions
  - `isAdmin()`, `isManager()`, `isAdminOrManager()` convenience functions
  - Centralized role checking logic for frontend components

### Changed

#### Backend

- Refactored authentication middleware configuration by moving detailed setup code from `main.py` to `DualAuthService.configure_middleware()` helper method for better separation of concerns and maintainability.
- Updated import statements formatting for improved code readability (multi-line imports consolidated).
- Enhanced `main.py` with worker monitoring configuration during application startup
- Added lifecycle hooks for background task scheduler and worker monitoring
- Improved `WorkerMetricsCollectionJob` pickle serialization with `__getstate__` and `__setstate__` methods
- Enhanced job configuration with proper dependency injection pattern

#### UI/Frontend

- Enhanced Worker Details modal with improved refresh functionality
- Added loading states and visual feedback for async operations
- Improved role-based access control checks in workers UI
- Enhanced system monitoring display with better data formatting
- Updated navbar to properly display user information and roles

#### Dependencies

- Updated `neuroglia-python` from 0.6.6 to 0.6.7 (later updated to 0.6.8)
- Added `apscheduler = "^3.11.1"` for background task scheduling
