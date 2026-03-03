# Bootstrap Prompt — Content Synchronization Phase 2

**Use this prompt to start a new AI session for Phase 2 implementation.**

---

## Session Initialization

```
Recall session: workspace_id="lablet-cloud-manager", focus_hint="Phase 2 CPA internal API sync trigger content synchronization"
```

---

## Context

We are implementing the **Content Synchronization** feature for the Lablet Cloud Manager.
The full implementation plan is at `docs/implementation/content_synchronization.md`.

### What's Done (Phase 1 — ✅ Complete)

Phase 1 expanded the domain model across `lcm-core` and `control-plane-api`. All sub-tasks (3.1–3.7) are implemented, tested, and lint-clean.

**Key deliverables:**

| Sub-task | Scope | Files Modified |
|----------|-------|---------------|
| 3.1 | `PENDING_SYNC` added to `LabletDefinitionStatus` enum | `src/core/lcm_core/domain/enums/lablet_definition_status.py` |
| 3.2 | `LabletDefinitionState` expanded with 15+ new fields (bucket_name, user_session_package_name, content_package_hash, upstream_*, devices_json, cml_yaml_*, etc.) | `src/control-plane-api/domain/entities/lablet_definition.py` |
| 3.3 | Domain events expanded: `CreatedDomainEvent` + new `ContentSyncedDomainEvent` + `SyncRequestedDomainEvent` (Phase 2 early) | `src/control-plane-api/domain/events/lablet_definition_events.py` |
| 3.4 | `create()` accepts `form_qualified_name` (required), auto-derives `bucket_name`/`lab_artifact_uri`. `slugify_fqn()` utility in both lcm-core and CPA. `record_content_sync()` expanded with full metadata + `port_template` | `src/control-plane-api/domain/entities/lablet_definition.py`, `src/core/lcm_core/domain/utils.py`, `src/control-plane-api/domain/utils.py` |
| 3.5 | `@dispatch(CreatedDomainEvent)` sets `PENDING_SYNC` status + applies new fields | `src/control-plane-api/domain/entities/lablet_definition.py` |
| 3.6 | DTOs expanded (full + summary) + mapper functions updated | `src/control-plane-api/application/dtos/lablet_definition_dto.py` |
| 3.7 | `LabletDefinitionReadModel` expanded with content metadata fields | `src/core/lcm_core/domain/entities/read_models/lablet_definition_read_model.py` |

**Bonus deliverables (done ahead of schedule):**

- `PortTemplate.from_cml_nodes()` static factory — extracts port_template from CML YAML `nodes[].tags` (ADR-029)
- `port_template` field on `ContentSyncedDomainEvent` + wired through `record_content_sync()` + `@dispatch` handler
- `LabletDefinitionSyncRequestedDomainEvent` already defined (Phase 2 artifact)
- `lds_region` renamed to `user_session_default_region` across all layers

**Test coverage:** 69/69 CPA tests + 77/77 lcm-core tests passing.

### What's Next (Phase 2)

**Goal:** CPA Internal API & Sync Trigger — implement the CQRS commands, internal API endpoints, and etcd projectors that allow:

1. Creating definitions with content-sync fields via updated Create command
2. Triggering sync via `SyncLabletDefinitionCommand` (emits domain event → etcd)
3. Recording sync results via `RecordContentSyncResultCommand` (called by lablet-controller)
4. etcd projectors for reactive sync notification (AD-CS-001)

### Phase 2 Sub-Tasks (from plan §4.1–4.6)

| Section | Task | New/Modified Files |
|---------|------|--------------------|
| **4.1** | Update `CreateLabletDefinitionCommand` — accept `form_qualified_name` (required), new content config fields, validate FQN | `application/commands/lablet_definition/create_lablet_definition_command.py` |
| **4.2** | Update `SyncLabletDefinitionCommand` — trigger sync via `request_sync()` aggregate method, return 202 Accepted | `application/commands/lablet_definition/sync_lablet_definition_command.py` |
| **4.3** | NEW `RecordContentSyncResultCommand` — internal API for lablet-controller to report sync results, includes version-bump logic on content change | `application/commands/lablet_definition/record_content_sync_result_command.py` (NEW) |
| **4.4** | CPA Internal API endpoints — `GET /internal/lablet-definitions?sync_status=...`, `POST /internal/lablet-definitions/{id}/content-synced` | `api/controllers/internal_controller.py`, repository + query updates |
| **4.5** | Update `CreateLabletDefinitionRequest` API model — add `form_qualified_name` (required), content config fields | `api/controllers/lablet_definitions_controller.py` |
| **4.6** | NEW etcd projectors — `ContentSyncRequestedEtcdProjector` (write key), `ContentSyncCompletedEtcdProjector` (delete key) | `infrastructure/projectors/` (NEW), etcd state store config |

### Architecture References

- **Implementation Plan**: `docs/implementation/content_synchronization.md` §4 (Phase 2)
- **ADR-023**: Content sync trigger (etcd watch pattern — same as LabRecordReconciler)
- **ADR-027**: Version auto-increment on content change
- **ADR-028**: Definition initial status (PENDING_SYNC)
- **ADR-029**: Port template extraction from CML YAML
- **Existing pattern to follow**: `LabActionRequestedEtcdProjector` → `LabRecordReconciler` in worker-controller

### Key Patterns to Respect

1. **Self-contained CQRS**: Each command file contains both the `Command` dataclass and its `CommandHandler` class
2. **Mediator API**: `await self.mediator.execute_async(command)` — ONE argument only, no `cancellation_token`
3. **Handler helpers**: Use `self.ok()`, `self.created()`, `self.accepted()`, `self.not_found()`, `self.bad_request()` — NOT `OperationResult.success()`
4. **Repository methods**: Accept `cancellation_token`, mediator does NOT
5. **Controllers**: Class name = route prefix. Override `self.prefix = ""` for root serving
6. **etcd projectors**: Follow the existing `LabActionRequestedEtcdProjector` pattern exactly

### Running Tests & Lint

```bash
# CPA tests
cd src/control-plane-api && make test

# CPA lint
cd src/control-plane-api && make lint

# lcm-core tests
cd src/core && .venv/bin/python -m pytest tests/ -v
```

---

## Suggested Approach

1. Start with **4.1** (update CreateLabletDefinitionCommand) — this is the most straightforward
2. Then **4.5** (API model) — closely tied to 4.1
3. Then **4.2** (SyncLabletDefinitionCommand) — the sync trigger
4. Then **4.3** (RecordContentSyncResultCommand) — the sync callback
5. Then **4.4** (internal API endpoints) — wire the commands to HTTP
6. Finally **4.6** (etcd projectors) — the reactive trigger mechanism

Run tests after each sub-task to validate incrementally.
