"""Delete CML Worker command with handler.

ADR-015: This command is DB-only. It marks the worker for termination (soft delete).
The worker-controller watches etcd for state changes and handles actual EC2 instance
termination. A background cleanup job removes TERMINATED records after a retention period.

Soft Delete Pattern:
- User delete or GC detection → Sets status=TERMINATED, keeps record
- TerminatedWorkerCleanupJob → Removes records older than retention period (default: 30 days)
"""

import logging
from dataclasses import dataclass

from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DeleteCMLWorkerCommand(Command[OperationResult[dict]]):
    """Command to delete a CML Worker (soft delete).

    ADR-015: This command is DB-only. It does NOT make EC2 API calls.

    Soft Delete Pattern (consistent with GC behavior):
    1. Sets desired_status to TERMINATED
    2. If worker has EC2 instance: Worker-controller terminates it via etcd watch
    3. Worker-controller updates status to TERMINATED
    4. Record remains in DB with terminated_at timestamp
    5. TerminatedWorkerCleanupJob purges old records after retention period

    Args:
        worker_id: ID of the worker to delete
        force_hard_delete: If True, immediately removes from DB (admin only, use with caution).
                          Default False - uses soft delete for consistency.
        deleted_by: Optional user ID who initiated the deletion
    """

    worker_id: str
    force_hard_delete: bool = False  # Renamed from terminate_instance for clarity
    deleted_by: str | None = None


class DeleteCMLWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[DeleteCMLWorkerCommand, OperationResult[dict]],
):
    """Handle deleting a CML Worker (soft delete, DB-only per ADR-015).

    Uses soft delete pattern for consistency with GC behavior.
    Does NOT make EC2 API calls. Worker-controller handles actual
    EC2 termination by watching etcd for desired_status changes.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: DeleteCMLWorkerCommand) -> OperationResult[dict]:
        """Handle delete CML Worker command (soft delete).

        ADR-015: DB-only operation. No EC2 calls.

        Args:
            request: Delete command with worker ID and options

        Returns:
            OperationResult with termination details
        """
        command = request

        # Add tracing context
        add_span_attributes(
            {
                "cml_worker.id": command.worker_id,
                "cml_worker.force_hard_delete": command.force_hard_delete,
                "cml_worker.has_deleted_by": command.deleted_by is not None,
            }
        )

        try:
            with tracer.start_as_current_span("retrieve_cml_worker") as span:
                # Retrieve worker from repository
                worker = await self.cml_worker_repository.get_by_id_async(command.worker_id)

                if not worker:
                    error_msg = f"CML Worker not found: {command.worker_id}"
                    log.error(error_msg)
                    return self.not_found("CMLWorker", error_msg)

                span.set_attribute("ec2.instance_id", worker.state.aws_instance_id or "none")
                span.set_attribute("cml_worker.current_status", worker.state.status.value)

            # Check if already terminated
            if worker.state.status == CMLWorkerStatus.TERMINATED:
                log.info(f"CML Worker {command.worker_id} is already terminated")
                return self.ok(
                    {
                        "message": "Worker already terminated",
                        "worker_id": command.worker_id,
                        "status": CMLWorkerStatus.TERMINATED.value,
                        "terminated_at": worker.state.terminated_at.isoformat() if worker.state.terminated_at else None,
                    }
                )

            # Force hard delete (admin escape hatch for cleanup)
            if command.force_hard_delete:
                with tracer.start_as_current_span("force_hard_delete") as span:
                    log.warning(f"Force hard delete requested for worker {command.worker_id} by {command.deleted_by}")
                    worker.terminate(terminated_by=command.deleted_by)
                    deleted = await self.cml_worker_repository.delete_async(command.worker_id, worker)

                    if not deleted:
                        return self.bad_request(f"Failed to delete worker {command.worker_id}")

                    span.set_attribute("cml_worker.hard_deleted", True)

                return self.ok(
                    {
                        "message": "Worker permanently deleted (hard delete)",
                        "worker_id": command.worker_id,
                        "deleted_by": command.deleted_by,
                    }
                )

            # Soft delete: Set desired_status to TERMINATED
            # Worker-controller will handle EC2 termination and update status
            with tracer.start_as_current_span("soft_delete_worker") as span:
                # Set desired_status to TERMINATED - worker-controller reconciles
                worker.update_desired_status(CMLWorkerStatus.TERMINATED)

                # If worker has an EC2 instance, mark as SHUTTING_DOWN for UI visibility
                # If no EC2 instance (orphaned record), mark as TERMINATED immediately
                if worker.state.aws_instance_id:
                    worker.update_status(CMLWorkerStatus.SHUTTING_DOWN)
                    new_status = CMLWorkerStatus.SHUTTING_DOWN
                else:
                    # No EC2 instance - terminate immediately (soft delete)
                    worker.terminate(terminated_by=command.deleted_by)
                    new_status = CMLWorkerStatus.TERMINATED

                await self.cml_worker_repository.update_async(worker)

                span.set_attribute("cml_worker.desired_status", CMLWorkerStatus.TERMINATED.value)
                span.set_attribute("cml_worker.new_status", new_status.value)

            log.info(
                f"CML Worker {command.worker_id} marked for termination (soft delete). "
                f"desired_status=TERMINATED, status={new_status.value}. "
                f"Worker-controller will handle EC2 termination. "
                f"Record will be purged by TerminatedWorkerCleanupJob after retention period."
            )

            return self.accepted(
                {
                    "message": "Worker termination initiated (soft delete)",
                    "worker_id": command.worker_id,
                    "desired_status": CMLWorkerStatus.TERMINATED.value,
                    "status": new_status.value,
                    "has_ec2_instance": bool(worker.state.aws_instance_id),
                    "note": "Record will be retained for audit. Use force_hard_delete=True for immediate removal.",
                }
            )

        except Exception as e:
            log.exception(f"Unexpected error deleting CML Worker {command.worker_id}")
            return self.internal_server_error(f"Unexpected error: {str(e)}")
