"""Cleanup Terminated Workers command with handler.

Background job to purge TERMINATED worker records after a retention period.
This completes the soft delete pattern used by DeleteCMLWorkerCommand and GC.

Soft Delete Pattern:
- User delete or GC detection → Sets status=TERMINATED, keeps record
- CleanupTerminatedWorkersCommand → Removes records older than retention period

This job should be scheduled to run periodically (e.g., daily) via the
resource-scheduler or as a cron job.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Default retention period for terminated workers (30 days)
DEFAULT_RETENTION_DAYS = 30


@dataclass
class CleanupTerminatedWorkersCommand(Command[OperationResult[dict]]):
    """Command to cleanup (hard delete) TERMINATED worker records.

    This is an internal/admin command that should be run periodically
    to purge old terminated worker records from the database.

    Args:
        retention_days: Number of days to retain terminated records.
                       Records older than this will be deleted.
                       Default: 30 days.
        dry_run: If True, only report what would be deleted without
                actually deleting. Useful for verification.
        initiated_by: User/system that initiated the cleanup.
    """

    retention_days: int = DEFAULT_RETENTION_DAYS
    dry_run: bool = False
    initiated_by: str | None = None


@dataclass
class CleanupResult:
    """Result of cleanup operation."""

    workers_found: int
    workers_deleted: int
    workers_skipped: int
    retention_days: int
    cutoff_date: datetime
    dry_run: bool
    deleted_worker_ids: list[str]
    errors: list[str]


class CleanupTerminatedWorkersCommandHandler(
    CommandHandlerBase,
    CommandHandler[CleanupTerminatedWorkersCommand, OperationResult[dict]],
):
    """Handle cleanup of terminated worker records.

    This handler queries for all TERMINATED workers with terminated_at
    older than the retention period and permanently deletes them.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: CleanupTerminatedWorkersCommand) -> OperationResult[dict]:
        """Handle cleanup of terminated workers.

        Args:
            request: Cleanup command with retention settings

        Returns:
            OperationResult with cleanup statistics
        """
        command = request

        # Calculate cutoff date
        cutoff_date = datetime.now(UTC) - timedelta(days=command.retention_days)

        add_span_attributes(
            {
                "cleanup.retention_days": command.retention_days,
                "cleanup.cutoff_date": cutoff_date.isoformat(),
                "cleanup.dry_run": command.dry_run,
            }
        )

        log.info(f"{'[DRY RUN] ' if command.dry_run else ''}Starting cleanup of terminated workers. Retention: {command.retention_days} days, cutoff: {cutoff_date.isoformat()}")

        result = CleanupResult(
            workers_found=0,
            workers_deleted=0,
            workers_skipped=0,
            retention_days=command.retention_days,
            cutoff_date=cutoff_date,
            dry_run=command.dry_run,
            deleted_worker_ids=[],
            errors=[],
        )

        try:
            with tracer.start_as_current_span("query_terminated_workers") as span:
                # Query for terminated workers
                # Note: This requires a method on the repository to query by status
                # For now, we'll get all workers and filter (not ideal for large datasets)
                all_workers = await self.cml_worker_repository.get_all_async()

                # Filter for terminated workers older than cutoff
                terminated_workers = [w for w in all_workers if w.state.status == CMLWorkerStatus.TERMINATED and w.state.terminated_at is not None and w.state.terminated_at < cutoff_date]

                result.workers_found = len(terminated_workers)
                span.set_attribute("cleanup.workers_found", result.workers_found)

            log.info(f"Found {result.workers_found} terminated workers eligible for cleanup")

            if result.workers_found == 0:
                return self.ok(
                    {
                        "message": "No workers eligible for cleanup",
                        "workers_found": 0,
                        "workers_deleted": 0,
                        "retention_days": command.retention_days,
                        "cutoff_date": cutoff_date.isoformat(),
                        "dry_run": command.dry_run,
                    }
                )

            # Delete each worker
            with tracer.start_as_current_span("delete_terminated_workers") as span:
                for worker in terminated_workers:
                    worker_id = worker.id()
                    terminated_at = worker.state.terminated_at

                    try:
                        if command.dry_run:
                            log.info(f"[DRY RUN] Would delete worker {worker_id} (terminated at {terminated_at}, age: {(datetime.now(UTC) - terminated_at).days} days)")
                            result.deleted_worker_ids.append(worker_id)
                            result.workers_deleted += 1
                        else:
                            # Actually delete the worker
                            deleted = await self.cml_worker_repository.delete_async(worker_id, worker)

                            if deleted:
                                log.info(f"Deleted terminated worker {worker_id} (terminated at {terminated_at}, age: {(datetime.now(UTC) - terminated_at).days} days)")
                                result.deleted_worker_ids.append(worker_id)
                                result.workers_deleted += 1
                            else:
                                log.warning(f"Failed to delete worker {worker_id}")
                                result.workers_skipped += 1
                                result.errors.append(f"Failed to delete worker {worker_id}")

                    except Exception as e:
                        log.error(f"Error deleting worker {worker_id}: {e}")
                        result.workers_skipped += 1
                        result.errors.append(f"Error deleting {worker_id}: {str(e)}")

                span.set_attribute("cleanup.workers_deleted", result.workers_deleted)
                span.set_attribute("cleanup.workers_skipped", result.workers_skipped)

            log.info(f"{'[DRY RUN] ' if command.dry_run else ''}Cleanup complete. Deleted: {result.workers_deleted}, Skipped: {result.workers_skipped}, Errors: {len(result.errors)}")

            return self.ok(
                {
                    "message": f"Cleanup {'simulation' if command.dry_run else 'complete'}",
                    "workers_found": result.workers_found,
                    "workers_deleted": result.workers_deleted,
                    "workers_skipped": result.workers_skipped,
                    "retention_days": result.retention_days,
                    "cutoff_date": result.cutoff_date.isoformat(),
                    "dry_run": result.dry_run,
                    "deleted_worker_ids": result.deleted_worker_ids,
                    "errors": result.errors if result.errors else None,
                }
            )

        except Exception as e:
            log.exception("Unexpected error during terminated worker cleanup")
            return self.internal_server_error(f"Cleanup failed: {str(e)}")
