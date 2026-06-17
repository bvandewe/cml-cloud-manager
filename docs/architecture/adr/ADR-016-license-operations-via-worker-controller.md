# ADR-016: License Operations Must Go Through Worker-Controller

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted (Partially Superseded) |
| **Date** | 2026-02-07 |
| **Deciders** | Platform Team |
| **Related ADRs** | [ADR-015](./ADR-015-control-plane-api-no-ec2.md) (CPA No External Calls), [ADR-017](./ADR-017-lab-operations-via-lablet-controller.md) (Lab Operations) |
| **Partially Superseded by** | [ADR-054](./ADR-054-controller-topology-resource-kind.md) (service topology — `worker-controller` folds into `pod-controller`; the reconcile-through-controller _principle_ stands) |

## Context

As part of ADR-015 (Control Plane API Must Not Make External Calls), we identified that `RegisterCMLWorkerLicenseCommand` and `DeregisterCMLWorkerLicenseCommand` in control-plane-api directly call the CML API to register/deregister licenses. This violates the principle that control-plane-api should only manage state in the database.

The current implementation:

1. Receives license registration request
2. Directly calls `cml_client.register_license()` or `cml_client.deregister_license()`
3. Returns 202 Accepted
4. Worker-controller polls for completion status

This creates several issues:

- Control-plane-api has runtime dependencies on CML API availability
- Error handling is split between control-plane-api (initial call) and worker-controller (status polling)
- Inconsistent with the reconciliation pattern used for EC2 lifecycle operations

## Decision

License registration and deregistration operations will follow the same pattern as EC2 lifecycle operations:

1. **Control-plane-api** stores the desired license state (intent) in the database
2. **Worker-controller** reconciles by calling the CML API
3. **Worker-controller** updates the worker state with success/failure

### Implementation Details

#### CMLLicense Value Object Enhancement

Add a `pending_token` field to store the desired license token:

```python
@dataclass(frozen=True)
class CMLLicense:
    status: LicenseStatus = LicenseStatus.UNREGISTERED
    token: str | None = None  # Current registered token
    pending_token: str | None = None  # Desired token for registration
    pending_operation: str | None = None  # "register" | "deregister" | None
    operation_in_progress: bool = False
    expiry_date: date | None = None
    features: tuple[str, ...] = ()
    raw_info: dict[str, Any] | None = None
```

#### Control-plane-api Commands (DB-only)

```python
# RegisterCMLWorkerLicenseCommand
async def handle_async(self, request):
    worker = await self._repository.get_by_id_async(request.worker_id)
    worker.request_license_registration(
        token=request.license_token,
        initiated_by=request.initiated_by
    )
    await self._repository.update_async(worker)
    return self.accepted({"status": "pending", "message": "License registration queued"})
```

#### Worker-controller Reconciliation

```python
async def _reconcile_license(self, worker: CMLWorkerReadModel):
    license = worker.license
    if license.pending_operation == "register" and license.pending_token:
        success = await self._cml_client.register_license(license.pending_token)
        if success:
            await self._api_client.complete_license_registration(worker.id)
        else:
            await self._api_client.fail_license_registration(worker.id, "CML API error")
    elif license.pending_operation == "deregister":
        success = await self._cml_client.deregister_license()
        if success:
            await self._api_client.complete_license_deregistration(worker.id)
        else:
            await self._api_client.fail_license_deregistration(worker.id, "CML API error")
```

## Consequences

### Positive

1. **Consistent pattern**: License operations follow the same reconciliation pattern as EC2 lifecycle
2. **Decoupled**: Control-plane-api has no runtime dependency on CML API
3. **Resilient**: Failed operations can be retried by worker-controller
4. **Observable**: All state changes are recorded in the database
5. **Testable**: Control-plane-api commands can be unit tested without mocking CML API

### Negative

1. **Complexity**: Adds reconciliation logic to worker-controller
2. **Latency**: Slightly longer time to initiate (async reconciliation vs direct call)
3. **State management**: Need to track pending operations in worker state

### Neutral

1. Worker-controller already has CML System SPI client for worker-level operations
2. Existing domain events (`LicenseRegistrationStarted`, `LicenseRegistrationCompleted`, etc.) support this pattern

## Implementation Checklist

### Phase 1: Domain Model Updates

- [x] Add `pending_token` field to `CMLLicense` value object
- [x] Add `pending_operation` field to `CMLLicense` value object
- [x] Add `request_license_registration()` method to `CMLWorker` entity
- [x] Add `request_license_deregistration()` method to `CMLWorker` entity
- [x] Add `CMLWorkerLicenseRegistrationRequestedDomainEvent`
- [x] Add `CMLWorkerLicenseDeregistrationRequestedDomainEvent`
- [x] Add dispatch handlers for new events
- [x] Update `CMLLicenseReadModel` in lcm_core for worker-controller

### Phase 2: Control-plane-api Command Refactoring

- [x] Refactor `RegisterCMLWorkerLicenseCommand` to be DB-only
- [x] Refactor `DeregisterCMLWorkerLicenseCommand` to be DB-only
- [x] Add completion/failure commands for worker-controller to call

### Phase 3: Worker-controller Reconciliation

- [x] Add license reconciliation to `WorkerReconciler`
- [x] Add CML license API methods to `CmlSystemSpiClient`
- [x] Add Control Plane API client methods for license status updates

### Phase 4: Cleanup

- [ ] Remove `CMLApiClientFactory` from control-plane-api (if no other usages)
- [ ] Update tests

## References

- ADR-015: Control Plane API Must Not Make External Calls
- ADR-001: API-Centric State Management
- ADR-005: Dual State Store Architecture
- [notes/CML_LICENSE_REGISTRATION_IMPLEMENTATION.md](../../../notes/CML_LICENSE_REGISTRATION_IMPLEMENTATION.md)
