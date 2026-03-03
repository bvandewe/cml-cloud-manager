# CML License Registration Implementation Plan

**Date**: November 20, 2025
**Status**: Design Phase
**Objectives**:

1. Implement UI/backend for license registration/deregistration (admin-only)
2. Build testing framework to measure licensing reliability and performance

---

## Executive Summary

Based on analysis of CML API v2.9 OpenAPI spec and existing codebase patterns, here's the recommended approach:

### Key Technical Challenges

1. **Asynchronous/Unpredictable Duration**: CML licensing depends on external Cisco Smart Licensing infrastructure
   - Registration can take 5-60+ seconds
   - Network timeouts, CSSM unavailability, rate limiting
   - No progress callbacks - fire-and-forget API

2. **Status Polling Required**: POST returns 204 immediately, actual status via GET /licensing
   - Must poll registration_status field until COMPLETED or FAILED
   - No SSE/WebSocket notifications from CML API

3. **State Machine Complexity**: Multiple error states (409 conflicts, 400 bad requests, 403 auth failures)

### Recommended Architecture: **Async Command + Background Job + SSE Notifications**

---

## Architecture Overview

### Pattern: Fire-and-Forget with Status Polling

```
User Action (UI Modal)
    ↓
POST /api/workers/{id}/license (Lablet Cloud Manager)
    ↓
RegisterCMLWorkerLicenseCommand (dispatched to background job)
    ↓
Returns 202 Accepted immediately to UI
    ↓
Background Job: LicenseRegistrationJob
    ├─ POST /licensing/registration to CML worker
    ├─ Poll GET /licensing every 5s for up to 90s
    ├─ Update worker aggregate with status
    └─ Emit domain event → SSE notification to UI
    ↓
UI receives SSE event: license.registration.completed | license.registration.failed
    ↓
UI updates modal with final status
```

**Why this pattern?**

- ✅ Non-blocking: UI doesn't hang waiting for CML CSSM
- ✅ Observable: SSE provides real-time feedback
- ✅ Resilient: Handles CML API timeouts gracefully
- ✅ Testable: Background job can be scheduled independently
- ✅ Consistent: Same pattern as WorkerMetricsCollectionJob

---

## Implementation Plan

### Phase 1: Core Functionality (MVP - 1-2 days)

#### 1.1 Backend: CML API Client Extensions

**File**: `src/integration/services/cml_api_client.py`

```python
@dataclass
class CMLLicenseRegistrationRequest:
    """Request body for POST /licensing/registration."""
    token: str  # Smart Licensing token
    reregister: bool = False  # Force re-registration

@dataclass
class CMLLicenseRegistrationStatus:
    """License registration status from polling."""
    status: str  # PENDING, IN_PROGRESS, COMPLETED, FAILED
    message: str | None
    started_at: str | None
    completed_at: str | None
    error_code: str | None

class CMLApiClient:
    async def register_license(
        self,
        token: str,
        reregister: bool = False
    ) -> bool:
        """Initiate license registration (async operation).

        POST /api/v0/licensing/registration

        Args:
            token: Smart Licensing registration token
            reregister: Force re-registration (default False)

        Returns:
            True if registration request accepted (204), False otherwise

        Raises:
            IntegrationException: On API errors (400, 403, 409)

        Note:
            - Returns immediately (async operation on CML side)
            - Poll get_licensing() to check registration_status
            - Can take 5-90 seconds to complete
        """
        endpoint = f"{self.base_url}/api/v0/licensing/registration"

        try:
            token_auth = await self._get_token()

            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=30.0  # Shorter timeout - just for POST
            ) as client:
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {token_auth}"},
                    json={"token": token, "reregister": reregister}
                )

                if response.status_code == 204:
                    log.info(f"License registration request accepted for {self.base_url}")
                    return True

                elif response.status_code == 400:
                    error_detail = response.json().get("description", "Invalid token")
                    raise IntegrationException(f"Invalid license token: {error_detail}")

                elif response.status_code == 403:
                    raise IntegrationException("Access denied: Insufficient permissions")

                elif response.status_code == 409:
                    error_detail = response.json().get("description", "Registration in progress")
                    raise IntegrationException(f"Cannot register now: {error_detail}")

                else:
                    raise IntegrationException(f"License registration failed: HTTP {response.status_code}")

        except httpx.TimeoutException as e:
            raise IntegrationException(f"License registration request timed out: {e}") from e

        except httpx.ConnectError as e:
            raise IntegrationException(f"Cannot connect to CML instance: {e}") from e

    async def deregister_license(self) -> tuple[bool, str]:
        """Request license deregistration.

        DELETE /api/v0/licensing/deregistration

        Returns:
            (success: bool, message: str) tuple
            - 204: Full success
            - 202: Partial success (local deregistration, CSSM timeout)
            - 400: Already deregistered

        Raises:
            IntegrationException: On API errors (403, 409)
        """
        endpoint = f"{self.base_url}/api/v0/licensing/deregistration"

        try:
            token_auth = await self._get_token()

            async with httpx.AsyncClient(
                verify=self.verify_ssl,
                timeout=60.0  # Longer timeout - deregistration can be slow
            ) as client:
                response = await client.delete(
                    endpoint,
                    headers={"Authorization": f"Bearer {token_auth}"}
                )

                if response.status_code == 204:
                    return True, "Successfully deregistered from Smart Licensing"

                elif response.status_code == 202:
                    return True, "Deregistered locally (CSSM communication timeout)"

                elif response.status_code == 400:
                    return False, "Already deregistered"

                elif response.status_code == 403:
                    raise IntegrationException("Access denied: Insufficient permissions")

                elif response.status_code == 409:
                    error_detail = response.json().get("description", "Deregistration not allowed")
                    raise IntegrationException(f"Cannot deregister now: {error_detail}")

                else:
                    raise IntegrationException(f"License deregistration failed: HTTP {response.status_code}")

        except httpx.TimeoutException as e:
            # Timeout during deregistration might mean CSSM unreachable
            return True, "Deregistration timeout (may be deregistered locally)"

        except httpx.ConnectError as e:
            raise IntegrationException(f"Cannot connect to CML instance: {e}") from e
```

#### 1.2 Backend: Domain Events

**File**: `src/domain/events/cml_worker_events.py` (add new events)

```python
@dataclass
class CMLWorkerLicenseRegistrationStartedDomainEvent(DomainEvent):
    """Published when license registration starts."""
    worker_id: str
    started_at: str
    initiated_by: str

@dataclass
class CMLWorkerLicenseRegistrationCompletedDomainEvent(DomainEvent):
    """Published when license registration completes successfully."""
    worker_id: str
    registration_status: str
    smart_account: str | None
    virtual_account: str | None
    completed_at: str

@dataclass
class CMLWorkerLicenseRegistrationFailedDomainEvent(DomainEvent):
    """Published when license registration fails."""
    worker_id: str
    error_message: str
    error_code: str | None
    failed_at: str

@dataclass
class CMLWorkerLicenseDeregisteredDomainEvent(DomainEvent):
    """Published when license is deregistered."""
    worker_id: str
    deregistered_at: str
    initiated_by: str
```

#### 1.3 Backend: Commands

**File**: `src/application/commands/register_cml_worker_license_command.py`

```python
"""Register CML Worker license command and handler."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from neuroglia.core.operation_result import OperationResult
from neuroglia.mediation.mediator import Command, CommandHandler

from application.jobs.license_registration_job import LicenseRegistrationJob
from application.services.background_task_scheduler import BackgroundTaskScheduler
from domain.repositories.cml_worker_repository import CMLWorkerRepository

log = logging.getLogger(__name__)


@dataclass
class RegisterCMLWorkerLicenseCommand(Command[OperationResult[dict]]):
    """Command to register a CML Worker license.

    This command schedules a background job to handle the actual registration
    and polling process, returning immediately to the caller.
    """
    worker_id: str
    license_token: str
    reregister: bool = False
    initiated_by: str | None = None


class RegisterCMLWorkerLicenseCommandHandler(
    CommandHandler[RegisterCMLWorkerLicenseCommand, OperationResult[dict]]
):
    """Handler for RegisterCMLWorkerLicenseCommand."""

    def __init__(
        self,
        worker_repository: CMLWorkerRepository,
        scheduler: BackgroundTaskScheduler,
    ):
        self._repository = worker_repository
        self._scheduler = scheduler

    async def handle_async(
        self,
        command: RegisterCMLWorkerLicenseCommand,
        cancellation_token=None,
    ) -> OperationResult[dict]:
        """Handle license registration command.

        Steps:
        1. Validate worker exists and is running
        2. Schedule background job for registration + polling
        3. Return 202 Accepted immediately
        4. Background job will emit SSE events on completion
        """
        # Validate worker exists
        worker = await self._repository.get_by_id_async(command.worker_id, cancellation_token)
        if not worker:
            return self.not_found("Worker", f"Worker {command.worker_id} not found")

        # Check worker is running
        if worker.state.status not in ["running", "ready"]:
            return self.bad_request(
                f"Worker must be running to register license (current: {worker.state.status})"
            )

        # Check if registration already in progress
        # (Could add a worker state field: license_operation_in_progress)

        # Schedule background job
        job_id = f"license_reg_{command.worker_id}_{int(datetime.now(UTC).timestamp())}"

        try:
            self._scheduler.schedule_one_time_job(
                job_class=LicenseRegistrationJob,
                job_id=job_id,
                run_date=datetime.now(UTC),
                kwargs={
                    "worker_id": command.worker_id,
                    "license_token": command.license_token,
                    "reregister": command.reregister,
                    "initiated_by": command.initiated_by,
                },
            )

            log.info(
                f"📝 Scheduled license registration job for worker {command.worker_id} "
                f"(job_id: {job_id})"
            )

            return self.accepted({
                "message": "License registration initiated",
                "worker_id": command.worker_id,
                "job_id": job_id,
                "status": "pending",
                "note": "Monitor SSE events for completion status",
            })

        except Exception as e:
            log.error(f"Failed to schedule license registration job: {e}")
            return self.internal_server_error(f"Failed to schedule registration: {e}")
```

**File**: `src/application/commands/deregister_cml_worker_license_command.py`

```python
"""Deregister CML Worker license command and handler."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from neuroglia.core.operation_result import OperationResult
from neuroglia.mediation.mediator import Command, CommandHandler

from domain.repositories.cml_worker_repository import CMLWorkerRepository
from integration.services.cml_api_client import CMLApiClient

log = logging.getLogger(__name__)


@dataclass
class DeregisterCMLWorkerLicenseCommand(Command[OperationResult[dict]]):
    """Command to deregister a CML Worker license.

    Deregistration is typically faster than registration (< 10s),
    so we handle it synchronously instead of background job.
    """
    worker_id: str
    initiated_by: str | None = None


class DeregisterCMLWorkerLicenseCommandHandler(
    CommandHandler[DeregisterCMLWorkerLicenseCommand, OperationResult[dict]]
):
    """Handler for DeregisterCMLWorkerLicenseCommand."""

    def __init__(self, worker_repository: CMLWorkerRepository):
        self._repository = worker_repository

    async def handle_async(
        self,
        command: DeregisterCMLWorkerLicenseCommand,
        cancellation_token=None,
    ) -> OperationResult[dict]:
        """Handle license deregistration command.

        Deregistration is typically fast (<10s), so we do it synchronously.
        """
        # Get worker
        worker = await self._repository.get_by_id_async(command.worker_id, cancellation_token)
        if not worker:
            return self.not_found("Worker", f"Worker {command.worker_id} not found")

        # Check worker is accessible
        if not worker.state.cml_host:
            return self.bad_request("Worker does not have CML host configured")

        # Create CML API client
        cml_client = CMLApiClient(
            base_url=f"https://{worker.state.cml_host}",
            username="admin",  # TODO: Get from settings
            password="admin",  # pragma: allowlist secret
            verify_ssl=False,  # TODO: Get from settings
            timeout=60.0,
        )

        try:
            # Call deregister API (can take 10-60s)
            success, message = await cml_client.deregister_license()

            if success:
                # Update worker with deregistration event
                worker.deregister_license(
                    deregistered_at=datetime.now(UTC).isoformat(),
                    initiated_by=command.initiated_by,
                )
                await self._repository.update_async(worker, cancellation_token)

                log.info(f"✅ Successfully deregistered license for worker {command.worker_id}")

                return self.ok({
                    "message": message,
                    "worker_id": command.worker_id,
                    "deregistered_at": datetime.now(UTC).isoformat(),
                })
            else:
                # Already deregistered or failed
                return self.bad_request(message)

        except Exception as e:
            log.error(f"Failed to deregister license for worker {command.worker_id}: {e}")
            return self.internal_server_error(f"Deregistration failed: {e}")
```

#### 1.4 Backend: Background Job

**File**: `src/application/jobs/license_registration_job.py`

```python
"""Background job for CML license registration and status polling."""

import asyncio
import logging
from datetime import UTC, datetime

from application.jobs.base_background_job import BackgroundJobBase
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from integration.services.cml_api_client import CMLApiClient

log = logging.getLogger(__name__)


class LicenseRegistrationJob(BackgroundJobBase):
    """Background job to register CML license and poll for completion.

    Process:
    1. POST /licensing/registration (returns 204 immediately)
    2. Poll GET /licensing every 5s for up to 90s
    3. Update worker aggregate with final status
    4. Emit domain event (triggers SSE notification)
    """

    def __init__(
        self,
        service_provider,
        worker_id: str,
        license_token: str,
        reregister: bool = False,
        initiated_by: str | None = None,
    ):
        super().__init__(service_provider)
        self.worker_id = worker_id
        self.license_token = license_token
        self.reregister = reregister
        self.initiated_by = initiated_by

    async def execute_async(self, context) -> None:
        """Execute license registration and polling."""
        scope = self._service_provider.create_scope()
        repository = scope.get_required_service(CMLWorkerRepository)

        try:
            # Get worker
            worker = await repository.get_by_id_async(self.worker_id)
            if not worker:
                log.error(f"Worker {self.worker_id} not found for license registration")
                return

            # Check worker has CML host
            if not worker.state.cml_host:
                log.error(f"Worker {self.worker_id} does not have CML host configured")
                return

            # Create CML API client
            cml_client = CMLApiClient(
                base_url=f"https://{worker.state.cml_host}",
                username="admin",  # TODO: Get from settings
                password="",
                verify_ssl=False,  # TODO: Get from settings
                timeout=30.0,
            )

            # Start registration
            log.info(
                f"🔐 Starting license registration for worker {self.worker_id} "
                f"(reregister={self.reregister})"
            )

            started_at = datetime.now(UTC)

            # Emit started event
            worker.start_license_registration(
                started_at=started_at.isoformat(),
                initiated_by=self.initiated_by,
            )
            await repository.update_async(worker)

            # Call registration API
            try:
                await cml_client.register_license(self.license_token, self.reregister)
            except Exception as e:
                log.error(f"License registration API call failed: {e}")
                worker.fail_license_registration(
                    error_message=str(e),
                    failed_at=datetime.now(UTC).isoformat(),
                )
                await repository.update_async(worker)
                return

            # Poll for completion (max 90 seconds, poll every 5 seconds)
            max_attempts = 18  # 18 * 5s = 90s
            poll_interval = 5.0

            for attempt in range(max_attempts):
                await asyncio.sleep(poll_interval)

                try:
                    license_info = await cml_client.get_licensing()
                    if not license_info:
                        log.warning(f"Could not fetch licensing info (attempt {attempt + 1}/{max_attempts})")
                        continue

                    reg_status = license_info.registration_status

                    log.debug(
                        f"License registration status for worker {self.worker_id}: "
                        f"{reg_status} (attempt {attempt + 1}/{max_attempts})"
                    )

                    # Check for completion
                    if reg_status == "COMPLETED":
                        elapsed = (datetime.now(UTC) - started_at).total_seconds()
                        log.info(
                            f"✅ License registration completed for worker {self.worker_id} "
                            f"in {elapsed:.1f}s"
                        )

                        worker.complete_license_registration(
                            registration_status=reg_status,
                            smart_account=license_info.smart_account,
                            virtual_account=license_info.virtual_account,
                            completed_at=datetime.now(UTC).isoformat(),
                        )
                        await repository.update_async(worker)
                        return

                    # Check for failure
                    elif reg_status in ["FAILED", "EXPIRED", "RETRY_FAILED"]:
                        log.error(
                            f"❌ License registration failed for worker {self.worker_id}: "
                            f"{reg_status}"
                        )

                        worker.fail_license_registration(
                            error_message=f"Registration failed with status: {reg_status}",
                            failed_at=datetime.now(UTC).isoformat(),
                        )
                        await repository.update_async(worker)
                        return

                    # Still in progress (PENDING, IN_PROGRESS, etc.)
                    # Continue polling

                except Exception as e:
                    log.warning(f"Error polling license status (attempt {attempt + 1}): {e}")
                    continue

            # Timeout - registration took too long
            log.error(
                f"⏱️ License registration timeout for worker {self.worker_id} "
                f"(exceeded {max_attempts * poll_interval}s)"
            )

            worker.fail_license_registration(
                error_message=f"Registration timeout (exceeded {max_attempts * poll_interval}s)",
                failed_at=datetime.now(UTC).isoformat(),
            )
            await repository.update_async(worker)

        except Exception as e:
            log.error(f"License registration job failed for worker {self.worker_id}: {e}")
```

#### 1.5 Backend: Domain Aggregate Methods

**File**: `src/domain/entities/cml_worker.py` (add methods)

```python
class CMLWorker(AggregateRoot[str, CMLWorkerState]):
    """CML Worker aggregate root."""

    def start_license_registration(
        self,
        started_at: str,
        initiated_by: str | None,
    ) -> None:
        """Start license registration process."""
        event = CMLWorkerLicenseRegistrationStartedDomainEvent(
            aggregate_id=self.id(),
            worker_id=self.id(),
            started_at=started_at,
            initiated_by=initiated_by or "system",
        )
        self.record_event(event)

    def complete_license_registration(
        self,
        registration_status: str,
        smart_account: str | None,
        virtual_account: str | None,
        completed_at: str,
    ) -> None:
        """Complete license registration successfully."""
        event = CMLWorkerLicenseRegistrationCompletedDomainEvent(
            aggregate_id=self.id(),
            worker_id=self.id(),
            registration_status=registration_status,
            smart_account=smart_account,
            virtual_account=virtual_account,
            completed_at=completed_at,
        )
        self.record_event(event)

    def fail_license_registration(
        self,
        error_message: str,
        failed_at: str,
        error_code: str | None = None,
    ) -> None:
        """Fail license registration."""
        event = CMLWorkerLicenseRegistrationFailedDomainEvent(
            aggregate_id=self.id(),
            worker_id=self.id(),
            error_message=error_message,
            error_code=error_code,
            failed_at=failed_at,
        )
        self.record_event(event)

    def deregister_license(
        self,
        deregistered_at: str,
        initiated_by: str | None,
    ) -> None:
        """Deregister license."""
        event = CMLWorkerLicenseDeregisteredDomainEvent(
            aggregate_id=self.id(),
            worker_id=self.id(),
            deregistered_at=deregistered_at,
            initiated_by=initiated_by or "system",
        )
        self.record_event(event)

    # Dispatch handlers for state updates
    @dispatch(CMLWorkerLicenseRegistrationStartedDomainEvent)
    def on(self, event: CMLWorkerLicenseRegistrationStartedDomainEvent) -> None:
        """Handle license registration started."""
        # Could add: self.license_operation_in_progress = True
        pass

    @dispatch(CMLWorkerLicenseRegistrationCompletedDomainEvent)
    def on(self, event: CMLWorkerLicenseRegistrationCompletedDomainEvent) -> None:
        """Handle license registration completed."""
        # Update license info from next sync
        pass

    @dispatch(CMLWorkerLicenseRegistrationFailedDomainEvent)
    def on(self, event: CMLWorkerLicenseRegistrationFailedDomainEvent) -> None:
        """Handle license registration failed."""
        pass

    @dispatch(CMLWorkerLicenseDeregisteredDomainEvent)
    def on(self, event: CMLWorkerLicenseDeregisteredDomainEvent) -> None:
        """Handle license deregistered."""
        pass
```

#### 1.6 Backend: SSE Event Handlers

**File**: `src/application/events/domain/cml_worker_license_events.py` (NEW FILE)

```python
"""Domain event handlers for CML Worker license events."""

import logging

from neuroglia.eventing.cloud_events.cloud_event import CloudEvent
from neuroglia.mediation.mediator import EventHandler

from application.services.sse_event_relay import SSEEventRelay
from domain.events.cml_worker_events import (
    CMLWorkerLicenseDeregisteredDomainEvent,
    CMLWorkerLicenseRegistrationCompletedDomainEvent,
    CMLWorkerLicenseRegistrationFailedDomainEvent,
    CMLWorkerLicenseRegistrationStartedDomainEvent,
)

log = logging.getLogger(__name__)


class CMLWorkerLicenseRegistrationStartedEventHandler(
    EventHandler[CMLWorkerLicenseRegistrationStartedDomainEvent]
):
    """Broadcasts SSE event when license registration starts."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(
        self,
        event: CMLWorkerLicenseRegistrationStartedDomainEvent,
        cancellation_token=None,
    ) -> None:
        """Broadcast license registration started event via SSE."""
        log.debug(f"📡 Broadcasting license registration started for worker {event.worker_id}")

        sse_event = CloudEvent.create(
            source="lablet-cloud-manager/workers",
            type="worker.license.registration.started",
            data={
                "worker_id": event.worker_id,
                "started_at": event.started_at,
                "initiated_by": event.initiated_by,
            },
        )

        await self._sse_relay.publish_event(sse_event)


class CMLWorkerLicenseRegistrationCompletedEventHandler(
    EventHandler[CMLWorkerLicenseRegistrationCompletedDomainEvent]
):
    """Broadcasts SSE event when license registration completes."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(
        self,
        event: CMLWorkerLicenseRegistrationCompletedDomainEvent,
        cancellation_token=None,
    ) -> None:
        """Broadcast license registration completed event via SSE."""
        log.info(f"📡 Broadcasting license registration completed for worker {event.worker_id}")

        sse_event = CloudEvent.create(
            source="lablet-cloud-manager/workers",
            type="worker.license.registration.completed",
            data={
                "worker_id": event.worker_id,
                "registration_status": event.registration_status,
                "smart_account": event.smart_account,
                "virtual_account": event.virtual_account,
                "completed_at": event.completed_at,
            },
        )

        await self._sse_relay.publish_event(sse_event)


class CMLWorkerLicenseRegistrationFailedEventHandler(
    EventHandler[CMLWorkerLicenseRegistrationFailedDomainEvent]
):
    """Broadcasts SSE event when license registration fails."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(
        self,
        event: CMLWorkerLicenseRegistrationFailedDomainEvent,
        cancellation_token=None,
    ) -> None:
        """Broadcast license registration failed event via SSE."""
        log.warning(f"📡 Broadcasting license registration failed for worker {event.worker_id}")

        sse_event = CloudEvent.create(
            source="lablet-cloud-manager/workers",
            type="worker.license.registration.failed",
            data={
                "worker_id": event.worker_id,
                "error_message": event.error_message,
                "error_code": event.error_code,
                "failed_at": event.failed_at,
            },
        )

        await self._sse_relay.publish_event(sse_event)


class CMLWorkerLicenseDeregisteredEventHandler(
    EventHandler[CMLWorkerLicenseDeregisteredDomainEvent]
):
    """Broadcasts SSE event when license is deregistered."""

    def __init__(self, sse_relay: SSEEventRelay):
        self._sse_relay = sse_relay

    async def handle_async(
        self,
        event: CMLWorkerLicenseDeregisteredDomainEvent,
        cancellation_token=None,
    ) -> None:
        """Broadcast license deregistered event via SSE."""
        log.info(f"📡 Broadcasting license deregistered for worker {event.worker_id}")

        sse_event = CloudEvent.create(
            source="lablet-cloud-manager/workers",
            type="worker.license.deregistered",
            data={
                "worker_id": event.worker_id,
                "deregistered_at": event.deregistered_at,
                "initiated_by": event.initiated_by,
            },
        )

        await self._sse_relay.publish_event(sse_event)
```

#### 1.7 Backend: Controller Endpoints

**File**: `src/api/controllers/workers_controller.py` (update existing endpoint)

```python
@post(
    "/region/{aws_region}/workers/{worker_id}/license",
    response_model=Any,
    status_code=202,  # Changed from 200 to 202 Accepted
    responses=ControllerBase.error_responses,
)
async def register_license(
    self,
    aws_region: aws_region_annotation,
    worker_id: worker_id_annotation,
    request: RegisterLicenseRequest,
    token: str = Depends(require_roles("admin")),
) -> Any:
    """Registers a license for a CML Worker instance.

    This is an asynchronous operation that returns immediately with 202 Accepted.
    The actual registration process (which can take 5-90 seconds) happens in
    a background job. Monitor SSE events for completion status:

    - worker.license.registration.started: Registration initiated
    - worker.license.registration.completed: Registration successful
    - worker.license.registration.failed: Registration failed

    (**Requires `admin` role!**)"""
    logger.info(f"Registering license for CML worker {worker_id} in region {aws_region}")

    command = RegisterCMLWorkerLicenseCommand(
        worker_id=worker_id,
        license_token=request.license_token,
        reregister=request.reregister if hasattr(request, 'reregister') else False,
        initiated_by=token.get("sub") if isinstance(token, dict) else None,
    )

    return self.process(await self.mediator.execute_async(command))

@delete(
    "/region/{aws_region}/workers/{worker_id}/license",
    response_model=Any,
    status_code=200,
    responses=ControllerBase.error_responses,
)
async def deregister_license(
    self,
    aws_region: aws_region_annotation,
    worker_id: worker_id_annotation,
    token: str = Depends(require_roles("admin")),
) -> Any:
    """Deregisters the license from a CML Worker instance.

    This removes the worker from Cisco Smart Licensing. The operation
    can take 10-60 seconds and is handled synchronously.

    (**Requires `admin` role!**)"""
    logger.info(f"Deregistering license for CML worker {worker_id} in region {aws_region}")

    command = DeregisterCMLWorkerLicenseCommand(
        worker_id=worker_id,
        initiated_by=token.get("sub") if isinstance(token, dict) else None,
    )

    return self.process(await self.mediator.execute_async(command))
```

#### 1.8 Frontend: UI Modal

**File**: `src/ui/src/components/modals/license-registration-modal.js` (NEW FILE)

```javascript
/**
 * License Registration Modal
 *
 * Displays a modal for registering/deregistering CML licenses.
 * Handles SSE events for real-time status updates.
 */

export class LicenseRegistrationModal {
    constructor() {
        this.workerId = null;
        this.modal = null;
        this.sseSubscription = null;
    }

    show(workerId, currentLicenseStatus) {
        this.workerId = workerId;

        const modalHtml = `
            <div class="modal fade" id="licenseRegistrationModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">License Management</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div id="licenseStatus" class="mb-3">
                                <strong>Current Status:</strong>
                                <span class="badge bg-${this.getStatusBadgeClass(currentLicenseStatus)}">
                                    ${currentLicenseStatus || 'Unknown'}
                                </span>
                            </div>

                            <div id="registrationForm">
                                <div class="mb-3">
                                    <label for="licenseToken" class="form-label">License Token</label>
                                    <textarea
                                        class="form-control font-monospace"
                                        id="licenseToken"
                                        rows="4"
                                        placeholder="Paste your Smart Licensing token here..."
                                    ></textarea>
                                    <small class="form-text text-muted">
                                        Get your token from Cisco Smart Licensing portal
                                    </small>
                                </div>

                                <div class="form-check mb-3">
                                    <input class="form-check-input" type="checkbox" id="reregister">
                                    <label class="form-check-label" for="reregister">
                                        Force re-registration (if already registered)
                                    </label>
                                </div>
                            </div>

                            <div id="registrationProgress" class="d-none">
                                <div class="alert alert-info">
                                    <div class="d-flex align-items-center">
                                        <div class="spinner-border spinner-border-sm me-2" role="status">
                                            <span class="visually-hidden">Loading...</span>
                                        </div>
                                        <span id="progressMessage">Initiating registration...</span>
                                    </div>
                                </div>
                                <small class="text-muted">
                                    This can take 5-90 seconds depending on Cisco Smart Licensing service availability.
                                </small>
                            </div>

                            <div id="registrationResult" class="d-none"></div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                            <button
                                type="button"
                                class="btn btn-danger"
                                id="deregisterBtn"
                                ${!currentLicenseStatus || currentLicenseStatus === 'UNREGISTERED' ? 'disabled' : ''}
                            >
                                Deregister License
                            </button>
                            <button type="button" class="btn btn-primary" id="registerBtn">
                                Register License
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Inject modal into DOM
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Initialize Bootstrap modal
        this.modal = new bootstrap.Modal(document.getElementById('licenseRegistrationModal'));

        // Attach event listeners
        document.getElementById('registerBtn').addEventListener('click', () => this.handleRegister());
        document.getElementById('deregisterBtn').addEventListener('click', () => this.handleDeregister());

        // Subscribe to SSE events for this worker
        this.subscribeToSSE();

        // Show modal
        this.modal.show();

        // Cleanup on close
        document.getElementById('licenseRegistrationModal').addEventListener('hidden.bs.modal', () => {
            this.cleanup();
        });
    }

    async handleRegister() {
        const token = document.getElementById('licenseToken').value.trim();
        const reregister = document.getElementById('reregister').checked;

        if (!token) {
            this.showError('Please enter a license token');
            return;
        }

        // Hide form, show progress
        document.getElementById('registrationForm').classList.add('d-none');
        document.getElementById('registrationProgress').classList.remove('d-none');
        document.getElementById('registerBtn').disabled = true;
        document.getElementById('progressMessage').textContent = 'Initiating registration...';

        try {
            const response = await fetch(`/api/region/us-west-2/workers/${this.workerId}/license`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ license_token: token, reregister })
            });

            if (response.status === 202) {
                // Accepted - background job scheduled
                const data = await response.json();
                document.getElementById('progressMessage').textContent =
                    'Registration in progress... Waiting for Smart Licensing response...';

                // SSE events will update the UI when complete
            } else {
                const error = await response.json();
                this.showError(error.detail || 'Registration failed');
            }
        } catch (error) {
            this.showError('Network error: ' + error.message);
        }
    }

    async handleDeregister() {
        if (!confirm('Are you sure you want to deregister this license? This will remove it from Cisco Smart Licensing.')) {
            return;
        }

        document.getElementById('deregisterBtn').disabled = true;
        document.getElementById('progressMessage').textContent = 'Deregistering license...';
        document.getElementById('registrationProgress').classList.remove('d-none');

        try {
            const response = await fetch(`/api/region/us-west-2/workers/${this.workerId}/license`, {
                method: 'DELETE'
            });

            if (response.ok) {
                const data = await response.json();
                this.showSuccess(data.message || 'License deregistered successfully');
            } else {
                const error = await response.json();
                this.showError(error.detail || 'Deregistration failed');
            }
        } catch (error) {
            this.showError('Network error: ' + error.message);
        }
    }

    subscribeToSSE() {
        // Reuse existing SSE connection from app
        // Subscribe to license events for this worker
        this.sseSubscription = window.sseEventBus.subscribe(
            ['worker.license.registration.started',
             'worker.license.registration.completed',
             'worker.license.registration.failed',
             'worker.license.deregistered'],
            (event) => this.handleSSEEvent(event)
        );
    }

    handleSSEEvent(event) {
        const data = event.data;

        // Filter events for this worker only
        if (data.worker_id !== this.workerId) return;

        switch (event.type) {
            case 'worker.license.registration.started':
                document.getElementById('progressMessage').textContent =
                    'Registration started... Waiting for Smart Licensing confirmation...';
                break;

            case 'worker.license.registration.completed':
                this.showSuccess(
                    `License registered successfully!\n` +
                    `Smart Account: ${data.smart_account || 'N/A'}\n` +
                    `Virtual Account: ${data.virtual_account || 'N/A'}`
                );
                break;

            case 'worker.license.registration.failed':
                this.showError(
                    `Registration failed: ${data.error_message}\n` +
                    (data.error_code ? `Error Code: ${data.error_code}` : '')
                );
                break;

            case 'worker.license.deregistered':
                this.showSuccess('License deregistered successfully');
                break;
        }
    }

    showSuccess(message) {
        document.getElementById('registrationProgress').classList.add('d-none');
        document.getElementById('registrationResult').innerHTML = `
            <div class="alert alert-success">
                <i class="bi bi-check-circle-fill me-2"></i>
                ${message.replace(/\n/g, '<br>')}
            </div>
        `;
        document.getElementById('registrationResult').classList.remove('d-none');
        document.getElementById('registerBtn').disabled = false;
    }

    showError(message) {
        document.getElementById('registrationProgress').classList.add('d-none');
        document.getElementById('registrationResult').innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                ${message.replace(/\n/g, '<br>')}
            </div>
        `;
        document.getElementById('registrationResult').classList.remove('d-none');
        document.getElementById('registerBtn').disabled = false;
        document.getElementById('registrationForm').classList.remove('d-none');
    }

    getStatusBadgeClass(status) {
        const statusMap = {
            'COMPLETED': 'success',
            'IN_COMPLIANCE': 'success',
            'PENDING': 'warning',
            'IN_PROGRESS': 'info',
            'FAILED': 'danger',
            'UNREGISTERED': 'secondary'
        };
        return statusMap[status] || 'secondary';
    }

    cleanup() {
        if (this.sseSubscription) {
            this.sseSubscription.unsubscribe();
        }
        document.getElementById('licenseRegistrationModal').remove();
    }
}
```

#### 1.9 Frontend: Integration into Worker Details

**File**: `src/ui/src/components/worker-details.js` (update existing)

```javascript
// Add button to worker details card
function renderLicenseSection(worker) {
    const licenseStatus = worker.cml_data?.license_info?.registration_status || 'Unknown';
    const isRegistered = licenseStatus === 'COMPLETED' || licenseStatus === 'IN_COMPLIANCE';

    return `
        <div class="card mb-3">
            <div class="card-header">
                <h6 class="mb-0">License Information</h6>
            </div>
            <div class="card-body">
                <dl class="row mb-0">
                    <dt class="col-sm-4">Registration Status:</dt>
                    <dd class="col-sm-8">
                        <span class="badge bg-${getStatusBadgeClass(licenseStatus)}">
                            ${licenseStatus}
                        </span>
                    </dd>

                    ${isRegistered ? `
                        <dt class="col-sm-4">Smart Account:</dt>
                        <dd class="col-sm-8">${worker.cml_data?.license_info?.smart_account || 'N/A'}</dd>

                        <dt class="col-sm-4">Virtual Account:</dt>
                        <dd class="col-sm-8">${worker.cml_data?.license_info?.virtual_account || 'N/A'}</dd>

                        <dt class="col-sm-4">Authorization Status:</dt>
                        <dd class="col-sm-8">
                            <span class="badge bg-${getAuthStatusBadgeClass(worker.cml_data?.license_info?.authorization_status)}">
                                ${worker.cml_data?.license_info?.authorization_status || 'Unknown'}
                            </span>
                        </dd>
                    ` : ''}
                </dl>

                <button
                    class="btn btn-sm btn-primary mt-2"
                    id="manageLicenseBtn"
                    data-worker-id="${worker.id}"
                    data-license-status="${licenseStatus}"
                >
                    <i class="bi bi-key-fill me-1"></i>
                    Manage License
                </button>
            </div>
        </div>
    `;
}

// Add event listener
document.addEventListener('click', (e) => {
    if (e.target.closest('#manageLicenseBtn')) {
        const btn = e.target.closest('#manageLicenseBtn');
        const workerId = btn.dataset.workerId;
        const licenseStatus = btn.dataset.licenseStatus;

        const modal = new LicenseRegistrationModal();
        modal.show(workerId, licenseStatus);
    }
});
```

---

### Phase 2: Testing Framework (2-3 days)

#### 2.1 Testing UI View

**File**: `src/ui/src/views/license-testing.html` (NEW FILE)

Purpose: Dedicated view for systematic license testing

Features:

- Select target worker(s)
- Configure test scenarios:
  - Sequential registration/deregistration cycles
  - Concurrent registration attempts (stress test)
  - Variable delays between operations
  - Token validation testing
- Real-time results table
- Statistical analysis:
  - Success rate
  - Average duration
  - Failure patterns
  - Min/max/p50/p95/p99 latencies
- Export results to CSV/JSON

#### 2.2 Testing Backend: Commands

**File**: `src/application/commands/test_license_registration_command.py`

```python
"""Command to run automated license registration tests."""

@dataclass
class TestLicenseRegistrationCommand(Command[OperationResult[dict]]):
    """Run automated license registration test suite."""
    worker_ids: list[str]
    license_token: str
    test_scenario: str  # "sequential", "concurrent", "stress"
    iterations: int = 10
    delay_between_ops: float = 5.0
    concurrent_workers: int = 1
    initiated_by: str | None = None
```

**Handler**:

- Schedule test job for each scenario
- Track results in dedicated test collection
- Emit SSE events for live updates
- Generate final report

#### 2.3 Testing Results Storage

**MongoDB Collection**: `license_test_results`

Schema:

```python
{
    "_id": ObjectId,
    "test_id": str,  # UUID
    "scenario": str,  # "sequential", "concurrent", "stress"
    "started_at": datetime,
    "completed_at": datetime,
    "worker_ids": list[str],
    "iterations": int,
    "results": [
        {
            "worker_id": str,
            "iteration": int,
            "operation": str,  # "register" | "deregister"
            "started_at": datetime,
            "completed_at": datetime,
            "duration_seconds": float,
            "status": str,  # "success" | "failed" | "timeout"
            "error_message": str | None,
            "cml_status": str,  # Final CML registration_status
        }
    ],
    "statistics": {
        "total_attempts": int,
        "successful": int,
        "failed": int,
        "timeout": int,
        "success_rate": float,
        "avg_duration": float,
        "min_duration": float,
        "max_duration": float,
        "p50_duration": float,
        "p95_duration": float,
        "p99_duration": float,
        "failure_reasons": dict[str, int],  # Count by error type
    }
}
```

#### 2.4 Testing API Endpoints

**File**: `src/api/controllers/license_testing_controller.py` (NEW FILE)

```python
class LicenseTestingController(ControllerBase):
    """Controller for license testing operations."""

    @post("/tests/license-registration")
    async def start_license_test(
        self,
        request: StartLicenseTestRequest,
        token: str = Depends(require_roles("admin")),
    ) -> Any:
        """Start automated license registration test."""
        pass

    @get("/tests/{test_id}")
    async def get_test_results(
        self,
        test_id: str,
        token: str = Depends(get_current_user),
    ) -> Any:
        """Get test results and statistics."""
        pass

    @get("/tests")
    async def list_tests(
        self,
        limit: int = 50,
        token: str = Depends(get_current_user),
    ) -> Any:
        """List recent test runs."""
        pass
```

---

## Summary of Recommendations

### ✅ **Best Approach for Production Feature**

**Async Command + Background Job + SSE Pattern**

**Why this pattern excels:**

1. **Non-blocking UX**: Users get immediate feedback (202 Accepted)
2. **Resilient**: Handles CML/CSSM timeouts gracefully
3. **Observable**: Real-time SSE updates keep UI in sync
4. **Scalable**: Background jobs can be retried, monitored, queued
5. **Testable**: Can schedule test jobs independently
6. **Consistent**: Same pattern as existing WorkerMetricsCollectionJob

**Alternatives considered (and rejected)**:

- ❌ Synchronous blocking: Would timeout frontend (90s)
- ❌ WebSocket: Overkill for infrequent operations
- ❌ Polling from frontend: Inefficient, race conditions

### ✅ **Best Approach for Testing Framework**

**Dedicated Testing View + Test Suite Commands + Results Storage**

**Why this approach works:**

1. **Isolation**: Testing doesn't interfere with production operations
2. **Reproducible**: Scenarios can be re-run with same parameters
3. **Statistical**: Built-in analytics (success rate, latencies, failure patterns)
4. **Evidence-based**: Historical data for capacity planning
5. **Debugging**: Detailed logs per attempt for failure analysis

**Test Scenarios to Implement:**

1. **Sequential Baseline**: Single worker, 10 cycles (register → wait → deregister → wait)
2. **Concurrent Workers**: 5 workers, simultaneous registration
3. **Stress Test**: Rapid cycles with minimal delays (find failure threshold)
4. **Token Validation**: Various invalid tokens (malformed, expired, wrong format)
5. **Network Chaos**: Registration during simulated network issues

**Success Criteria:**

- Success rate > 95% for normal operations
- P95 latency < 60s
- Identifiable failure patterns (CSSM unavailable vs invalid token)
- Recovery time after failures

---

## Implementation Checklist

**Phase 1: Core Feature (MVP)**

- [ ] 1.1: CML API client methods (register, deregister)
- [ ] 1.2: Domain events (4 new events)
- [ ] 1.3: Commands (Register, Deregister)
- [ ] 1.4: Background job (LicenseRegistrationJob with polling)
- [ ] 1.5: Domain aggregate methods
- [ ] 1.6: SSE event handlers
- [ ] 1.7: Controller endpoints
- [ ] 1.8: Frontend modal
- [ ] 1.9: Worker details integration
- [ ] Unit tests for commands
- [ ] Integration tests for background job
- [ ] Manual testing on dev worker

**Phase 2: Testing Framework**

- [ ] 2.1: Testing UI view
- [ ] 2.2: Test commands (TestLicenseRegistrationCommand)
- [ ] 2.3: Results storage (MongoDB collection + repository)
- [ ] 2.4: Testing controller endpoints
- [ ] Test job implementation
- [ ] Statistics calculation
- [ ] CSV/JSON export
- [ ] Run baseline test suite (sequential, concurrent, stress)
- [ ] Document findings (success rates, latencies, failure patterns)

**Phase 3: Production Hardening**

- [ ] Add retry logic for transient failures
- [ ] Circuit breaker for CSSM availability
- [ ] Rate limiting (prevent hammering CSSM)
- [ ] Audit logging (who registered/deregistered what, when)
- [ ] Prometheus metrics (registration_duration, registration_success_rate)
- [ ] Alerts (high failure rate, unusual latencies)

---

## Expected Performance Characteristics

Based on CML API documentation and typical Smart Licensing behavior:

**Registration:**

- **Normal case**: 10-30 seconds
- **Slow case**: 30-60 seconds
- **Timeout threshold**: 90 seconds (recommended)
- **Failure modes**: CSSM unreachable, invalid token, rate limiting

**Deregistration:**

- **Normal case**: 5-15 seconds
- **Timeout case**: 30-60 seconds (returns 202, deregisters locally)

**Testing gaps to measure:**

- Minimum interval between successful registrations (rate limiting)
- Concurrent registration behavior (does CML queue or reject?)
- Recovery time after CSSM outage
- Token expiration behavior

---

## Security Considerations

1. **Admin-only**: Both operations require `admin` role
2. **Audit trail**: Domain events provide complete history
3. **Token exposure**: Tokens only in POST body, never logged or stored
4. **CSRF protection**: Existing cookie-based auth handles this
5. **Secrets management**: CML credentials from settings/vault (not hardcoded)

---

## Open Questions for Testing

1. **Rate limiting**: How many registrations per hour does CSSM allow?
2. **Concurrent behavior**: Can multiple workers register simultaneously?
3. **Token reuse**: Can same token be used on multiple workers?
4. **Failure recovery**: Does CML retry failed registrations automatically?
5. **Partial failures**: What happens if registration succeeds but authorization fails?

These should be answered empirically via the testing framework.
