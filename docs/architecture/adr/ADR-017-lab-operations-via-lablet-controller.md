# ADR-017: Lab Operations via Lablet-Controller

- **Status**: Accepted
- **Date**: 2026-02-07
- **Deciders**: Platform Team
- **Related**: ADR-015 (Control Plane API Must Not Make External Calls), ADR-016 (License Operations via Worker-Controller)

## Context

ADR-015 established that control-plane-api must not make external API calls. The following lab commands in control-plane-api currently violate this principle by directly calling the CML REST API:

| Command | CML API Calls | Purpose |
|---------|---------------|---------|
| `ControlLabCommand` | `start_lab()`, `stop_lab()`, `wipe_lab()` | Control lab lifecycle |
| `DeleteLabCommand` | `delete_lab()` | Remove lab from CML |
| `ImportLabCommand` | `import_lab()` | Import lab YAML to CML |
| `DownloadLabCommand` | `download_lab()` | Retrieve lab YAML from CML |

These commands use `CMLApiClientFactory` to create clients that directly communicate with CML workers, bypassing the controller architecture.

### Why Not Extend ADR-015?

ADR-015 defines the **principle** (no external calls from control-plane-api). This ADR documents the **specific implementation decision** for lab operations, including:

1. Pattern selection (reconciliation vs BFF)
2. Domain model changes
3. Lablet-controller reconciliation logic
4. Exception handling for read-only operations

Keeping this as a separate ADR maintains clarity and traceability for the lab operations subsystem.

## Decision

### Pattern Selection

Lab operations will use **two patterns** based on operation type:

#### 1. Reconciliation Pattern (State-Changing Operations)

For operations that modify lab state, use the Kubernetes-style reconciliation pattern established in ADR-016:

| Operation | Flow |
|-----------|------|
| **Start** | User request → DB: `pending_action=start` → lablet-controller reconciles → CML API |
| **Stop** | User request → DB: `pending_action=stop` → lablet-controller reconciles → CML API |
| **Wipe** | User request → DB: `pending_action=wipe` → lablet-controller reconciles → CML API |
| **Delete** | User request → DB: `pending_action=delete` → lablet-controller reconciles → CML API |
| **Import** | User provides YAML → DB: stores YAML + `pending_action=import` → lablet-controller reconciles → CML API |

#### 2. BFF Pattern (Read-Only Operations)

For operations that need immediate results and don't modify state:

| Operation | Flow |
|-----------|------|
| **Download** | User request → control-plane-api proxies to lablet-controller `/labs/{lab_id}/download` → immediate YAML response |

The BFF pattern is acceptable here because:

- Download is read-only (no state change)
- Users need immediate YAML content for editing/backup
- Reconciliation pattern doesn't fit request-response semantics
- Lablet-controller is an internal service, not an external API

### Domain Model Changes

#### LabRecordState (control-plane-api/domain/entities/lab_record.py)

Add pending action fields:

```python
class LabRecordState(AggregateState[str]):
    # ... existing fields ...

    # Pending action for reconciliation (ADR-017)
    pending_action: str | None = None  # "start", "stop", "wipe", "delete", "import"
    pending_action_at: datetime | None = None  # When action was requested
    pending_action_error: str | None = None  # Error message if reconciliation failed

    # For import operations: store the YAML until reconciliation
    pending_import_yaml: str | None = None
    pending_import_title: str | None = None  # Optional title override
```

#### LabRecord Aggregate Methods

Add methods to set pending actions:

```python
def request_start(self) -> None:
    """Request lab to be started via reconciliation."""

def request_stop(self) -> None:
    """Request lab to be stopped via reconciliation."""

def request_wipe(self) -> None:
    """Request lab to be wiped via reconciliation."""

def request_delete(self) -> None:
    """Request lab to be deleted via reconciliation."""

def clear_pending_action(self, error: str | None = None) -> None:
    """Clear pending action after reconciliation (success or failure)."""
```

#### PendingLabImport Entity (New)

For import operations, we need to store YAML before the lab exists:

```python
class PendingLabImportState(AggregateState[str]):
    id: str = ""
    worker_id: str = ""
    yaml_content: str = ""
    title: str | None = None
    requested_by: str | None = None
    requested_at: datetime | None = None
    status: str = "pending"  # "pending", "importing", "completed", "failed"
    error_message: str | None = None
    created_lab_id: str | None = None  # Set after successful import
```

### Command Refactoring

#### ControlLabCommand (Reconciliation)

```python
async def handle_async(self, request: ControlLabCommand) -> OperationResult[dict]:
    # 1. Get lab record from repository
    lab = await self._lab_repository.get_by_worker_and_lab_id(request.worker_id, request.lab_id)
    if not lab:
        return self.not_found("Lab", f"Lab {request.lab_id} not found")

    # 2. Set pending action (no CML API call!)
    if request.action == LabAction.START:
        lab.request_start()
    elif request.action == LabAction.STOP:
        lab.request_stop()
    elif request.action == LabAction.WIPE:
        lab.request_wipe()

    # 3. Save and write to etcd for controller to watch
    await self._lab_repository.update_async(lab)
    await self._etcd_state_writer.write_lab_state(lab)

    # 4. Return accepted (async processing)
    return self.accepted({
        "lab_id": request.lab_id,
        "action": request.action.value,
        "status": "pending",
        "message": "Operation queued for reconciliation"
    })
```

#### DeleteLabCommand (Reconciliation)

```python
async def handle_async(self, request: DeleteLabCommand) -> OperationResult[dict]:
    # 1. Get lab record
    lab = await self._lab_repository.get_by_worker_and_lab_id(request.worker_id, request.lab_id)
    if not lab:
        return self.not_found("Lab", f"Lab {request.lab_id} not found")

    # 2. Set pending delete action
    lab.request_delete()

    # 3. Save and write to etcd
    await self._lab_repository.update_async(lab)
    await self._etcd_state_writer.write_lab_state(lab)

    return self.accepted({
        "lab_id": request.lab_id,
        "status": "pending_delete",
        "message": "Delete queued for reconciliation"
    })
```

#### ImportLabCommand (Reconciliation)

```python
async def handle_async(self, request: ImportLabCommand) -> OperationResult[dict]:
    # 1. Validate worker exists
    worker = await self._worker_repository.get_by_id_async(request.worker_id)
    if not worker:
        return self.not_found("Worker", f"Worker {request.worker_id} not found")

    # 2. Create PendingLabImport record (stores YAML in MongoDB)
    pending_import = PendingLabImport.create(
        worker_id=request.worker_id,
        yaml_content=request.yaml_content,
        title=request.title,
        requested_by=current_user,  # From auth context
    )
    await self._pending_import_repository.add_async(pending_import)

    # 3. Write to etcd for lablet-controller to watch
    await self._etcd_state_writer.write_pending_import(pending_import)

    return self.accepted({
        "import_id": pending_import.id(),
        "worker_id": request.worker_id,
        "status": "pending",
        "message": "Import queued for reconciliation"
    })
```

#### DownloadLabCommand (BFF - Proxy to Lablet-Controller)

```python
async def handle_async(self, request: DownloadLabCommand) -> OperationResult[str]:
    # 1. Get worker to determine lablet-controller endpoint
    worker = await self._worker_repository.get_by_id_async(request.worker_id)
    if not worker:
        return self.not_found("Worker", f"Worker {request.worker_id} not found")

    # 2. Call lablet-controller's download endpoint (BFF pattern)
    try:
        yaml_content = await self._lablet_controller_client.download_lab(
            worker_id=request.worker_id,
            lab_id=request.lab_id,
        )
        return self.ok(yaml_content)
    except LabletControllerError as e:
        return self.bad_request(str(e))
```

### Lablet-Controller Changes

#### Lab Reconciler

Add lab reconciliation to `LabletControllerService`:

```python
async def _reconcile_lab_pending_actions(self) -> None:
    """Reconcile labs with pending actions."""

    # 1. Query Control Plane API for labs with pending actions
    labs_with_pending = await self.api.get_labs_with_pending_actions()

    for lab in labs_with_pending:
        try:
            if lab.pending_action == "start":
                await self._execute_lab_start(lab)
            elif lab.pending_action == "stop":
                await self._execute_lab_stop(lab)
            elif lab.pending_action == "wipe":
                await self._execute_lab_wipe(lab)
            elif lab.pending_action == "delete":
                await self._execute_lab_delete(lab)
        except Exception as e:
            await self._report_lab_action_failure(lab.id, str(e))

async def _reconcile_pending_imports(self) -> None:
    """Reconcile pending lab imports."""

    # 1. Query Control Plane API for pending imports
    pending_imports = await self.api.get_pending_lab_imports()

    for pending in pending_imports:
        try:
            # 2. Get worker endpoint
            worker = await self.api.get_worker(pending.worker_id)

            # 3. Call CML API to import
            lab_id = await self.cml_labs.import_lab(
                host=worker.endpoint,
                topology=pending.yaml_content,
                title=pending.title,
            )

            # 4. Report success to Control Plane API
            await self.api.complete_lab_import(
                import_id=pending.id,
                lab_id=lab_id,
            )

        except Exception as e:
            await self.api.fail_lab_import(pending.id, str(e))
```

#### Download Endpoint (BFF)

Add download endpoint to lablet-controller's API:

```python
@router.get("/labs/{worker_id}/{lab_id}/download")
async def download_lab(
    worker_id: str,
    lab_id: str,
    cml_client: CmlLabsSpiClient = Depends(get_cml_client),
    api_client: ControlPlaneApiClient = Depends(get_api_client),
):
    """Download lab YAML from CML worker.

    BFF pattern: Called by control-plane-api or UI directly.
    """
    # Get worker endpoint
    worker = await api_client.get_worker(worker_id)
    if not worker:
        raise HTTPException(404, f"Worker {worker_id} not found")

    # Download from CML
    yaml_content = await cml_client.download_lab(
        host=worker.endpoint,
        lab_id=lab_id,
    )

    return Response(content=yaml_content, media_type="application/x-yaml")
```

### Control Plane API Internal Endpoints

Add endpoints for lablet-controller to report reconciliation status:

```python
# POST /internal/labs/{lab_id}/action/start
# POST /internal/labs/{lab_id}/action/complete
# POST /internal/labs/{lab_id}/action/fail

# POST /internal/lab-imports/{import_id}/start
# POST /internal/lab-imports/{import_id}/complete
# POST /internal/lab-imports/{import_id}/fail
```

## Consequences

### Positive

1. **ADR-015 Compliance**: control-plane-api no longer calls CML API directly
2. **Consistent Pattern**: Matches ADR-016 license reconciliation approach
3. **Resilient**: Reconciliation retries on transient failures
4. **Observable**: Pending actions visible in lab state
5. **Auditable**: YAML stored in MongoDB before import

### Negative

1. **Eventual Consistency**: Users see "pending" state before actual change
2. **Complexity**: New domain entities and reconciliation logic
3. **BFF Exception**: Download doesn't fit pure reconciliation (documented exception)

### Neutral

1. **UI Changes**: UI should show pending states with spinners
2. **Polling**: UI may need to poll for action completion

## Implementation Checklist

### Phase 1: Domain Model Updates

- [ ] Add `pending_action`, `pending_action_at`, `pending_action_error` to `LabRecordState`
- [ ] Add domain events: `LabActionRequestedDomainEvent`, `LabActionCompletedDomainEvent`, `LabActionFailedDomainEvent`
- [ ] Add aggregate methods: `request_start()`, `request_stop()`, `request_wipe()`, `request_delete()`, `clear_pending_action()`
- [ ] Create `PendingLabImport` entity for import queue
- [ ] Create `PendingLabImportRepository` interface and MongoDB implementation

### Phase 2: Control-Plane-API Command Refactoring

- [ ] Refactor `ControlLabCommand` to set `pending_action` (no CML calls)
- [ ] Refactor `DeleteLabCommand` to set `pending_action=delete` (no CML calls)
- [ ] Refactor `ImportLabCommand` to create `PendingLabImport` record (no CML calls)
- [ ] Create `LabletControllerClient` for BFF calls
- [ ] Refactor `DownloadLabCommand` to proxy through lablet-controller

### Phase 3: Control-Plane-API Internal Endpoints

- [ ] Add `POST /internal/labs/{lab_id}/action/start` endpoint
- [ ] Add `POST /internal/labs/{lab_id}/action/complete` endpoint
- [ ] Add `POST /internal/labs/{lab_id}/action/fail` endpoint
- [ ] Add `POST /internal/lab-imports/{import_id}/start` endpoint
- [ ] Add `POST /internal/lab-imports/{import_id}/complete` endpoint
- [ ] Add `POST /internal/lab-imports/{import_id}/fail` endpoint
- [ ] Add `GET /internal/labs/pending-actions` query endpoint
- [ ] Add `GET /internal/lab-imports/pending` query endpoint

### Phase 4: Lablet-Controller Reconciliation

- [ ] Add `_reconcile_lab_pending_actions()` to `LabletControllerService`
- [ ] Add `_execute_lab_start()`, `_execute_lab_stop()`, `_execute_lab_wipe()`, `_execute_lab_delete()`
- [ ] Add `_reconcile_pending_imports()` method
- [ ] Add `GET /labs/{worker_id}/{lab_id}/download` BFF endpoint
- [ ] Update reconciliation loop to call lab reconciliation methods

### Phase 5: Cleanup

- [ ] Remove `CMLApiClientFactory` usage from lab commands
- [ ] Update tests for new command behavior
- [ ] Update API documentation for async behavior

## References

- ADR-015: Control Plane API Must Not Make External Calls
- ADR-016: License Operations via Worker-Controller
- [Kubernetes Controller Pattern](https://kubernetes.io/docs/concepts/architecture/controller/)
