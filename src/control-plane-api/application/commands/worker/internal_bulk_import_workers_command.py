"""Internal bulk import discovered workers command.

This command accepts pre-discovered EC2 instances from worker-controller
and persists them as CML Worker aggregates.

Per ADR-001: Control Plane API is the only component that writes to MongoDB.
Worker-controller discovers instances and submits them here for persistence.
"""

import logging
from dataclasses import dataclass, field

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

from domain.entities.cml_worker import CMLWorker
from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DiscoveredInstance:
    """A single discovered EC2 instance from worker-controller."""

    instance_id: str
    state: str
    public_ip: str | None = None
    private_ip: str | None = None
    instance_type: str | None = None
    image_id: str | None = None  # AMI ID from EC2
    launch_time: str | None = None  # ISO 8601 string
    name: str | None = None  # EC2 Name tag


@dataclass
class InternalBulkImportResult:
    """Result of internal bulk import operation."""

    imported: list[str]  # List of imported worker IDs
    skipped: list[dict[str, str]]  # {"instance_id": str, "reason": str}
    updated: list[str]  # List of updated worker IDs (status sync)
    total_found: int
    total_imported: int
    total_skipped: int
    total_updated: int


@dataclass
class InternalBulkImportWorkersCommand(Command[OperationResult[InternalBulkImportResult]]):
    """Command to import pre-discovered EC2 instances as CML Workers.

    This is called by worker-controller's WorkerReconciler discovery loop after it
    scans AWS for EC2 instances. The actual AWS discovery is done by the
    controller; this command only handles persistence.

    Args:
        discovered_instances: List of discovered EC2 instance data
        aws_region: AWS region where instances were discovered
        source: Source of the import (e.g., "worker-controller-discovery")
    """

    discovered_instances: list[dict] = field(default_factory=list)
    aws_region: str = ""
    source: str = "worker-controller"


class InternalBulkImportWorkersCommandHandler(
    CommandHandlerBase,
    CommandHandler[InternalBulkImportWorkersCommand, OperationResult[InternalBulkImportResult]],
):
    """Handle internal bulk import of pre-discovered EC2 instances."""

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        cml_worker_repository: CMLWorkerRepository,
    ):
        super().__init__(
            mediator,
            mapper,
            cloud_event_bus,
            cloud_event_publishing_options,
        )
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: InternalBulkImportWorkersCommand) -> OperationResult[InternalBulkImportResult]:
        """Handle internal bulk import command.

        Args:
            request: Command with discovered instances

        Returns:
            OperationResult with import statistics
        """
        command = request

        if not command.discovered_instances:
            return self.ok(
                InternalBulkImportResult(
                    imported=[],
                    skipped=[],
                    updated=[],
                    total_found=0,
                    total_imported=0,
                    total_skipped=0,
                    total_updated=0,
                )
            )

        if not command.aws_region:
            return self.bad_request("aws_region is required")

        with tracer.start_as_current_span("internal_bulk_import_workers") as span:
            span.set_attribute("import.source", command.source)
            span.set_attribute("import.region", command.aws_region)
            span.set_attribute("import.instance_count", len(command.discovered_instances))

            log.info(f"📥 Internal bulk import: {len(command.discovered_instances)} instances from {command.source} in {command.aws_region}")

            # Get existing workers to filter duplicates
            existing_workers = await self.cml_worker_repository.get_all_async()
            existing_workers_map = {w.state.aws_instance_id: w for w in existing_workers if w.state.aws_instance_id}

            log.info(f"Found {len(existing_workers_map)} existing workers in database")

            imported_ids: list[str] = []
            skipped_instances: list[dict[str, str]] = []
            updated_ids: list[str] = []

            for instance_data in command.discovered_instances:
                instance_id = instance_data.get("instance_id")
                instance_state = instance_data.get("state", "unknown")

                if not instance_id:
                    log.warning("Skipping instance with no instance_id")
                    continue

                # Check if already registered
                if instance_id in existing_workers_map:
                    worker = existing_workers_map[instance_id]

                    # Backfill worker name from AWS Name tag if current name is auto-generated
                    discovered_name = instance_data.get("name")
                    if discovered_name and worker.state.name.startswith("worker-"):
                        log.info(f"🔄 Updating worker {worker.id()} name: '{worker.state.name}' → '{discovered_name}'")
                        worker.state.name = discovered_name

                    # Sync IP addresses — EC2 assigns new public IPs on stop/start
                    discovered_public_ip = instance_data.get("public_ip")
                    discovered_private_ip = instance_data.get("private_ip")
                    ip_changed = False

                    if discovered_public_ip and discovered_public_ip != worker.state.public_ip:
                        log.info(f"🔄 Updating worker {worker.id()} public IP: {worker.state.public_ip} → {discovered_public_ip}")
                        worker.update_ec2_instance_details(public_ip=discovered_public_ip)
                        ip_changed = True

                    if discovered_private_ip and discovered_private_ip != worker.state.private_ip:
                        log.info(f"🔄 Updating worker {worker.id()} private IP: {worker.state.private_ip} → {discovered_private_ip}")
                        worker.update_ec2_instance_details(private_ip=discovered_private_ip)
                        ip_changed = True

                    # Sync actual EC2 state into worker status
                    # Discovery is the source of truth for actual instance state
                    updated = False
                    if instance_state == "running" and worker.state.status != CMLWorkerStatus.RUNNING:
                        log.info(f"🔄 Syncing worker {worker.id()} status to RUNNING based on AWS state (was {worker.state.status.value})")
                        worker.update_status(CMLWorkerStatus.RUNNING)
                        updated = True
                    elif instance_state == "stopped" and worker.state.status != CMLWorkerStatus.STOPPED:
                        log.info(f"🔄 Syncing worker {worker.id()} status to STOPPED based on AWS state (was {worker.state.status.value})")
                        worker.update_status(CMLWorkerStatus.STOPPED)
                        # Also align desired_status — EC2 is already stopped, no point
                        # keeping desired_status=running (would trigger unwanted reconciliation)
                        worker.update_desired_status(
                            CMLWorkerStatus.STOPPED,
                            requested_by="system-sync",
                            reason="Aligned with actual EC2 stopped state detected during discovery",
                        )
                        updated = True
                    elif instance_state == "stopping" and worker.state.status != CMLWorkerStatus.STOPPING:
                        log.info(f"🔄 Syncing worker {worker.id()} status to STOPPING based on AWS state (was {worker.state.status.value})")
                        worker.update_status(CMLWorkerStatus.STOPPING)
                        updated = True
                    elif instance_state == "shutting-down" and worker.state.status != CMLWorkerStatus.SHUTTING_DOWN:
                        log.info(f"🔄 Updating worker {worker.id()} to SHUTTING_DOWN based on AWS state")
                        worker.update_status(CMLWorkerStatus.SHUTTING_DOWN)
                        updated = True
                    elif instance_state == "terminated" and worker.state.status != CMLWorkerStatus.TERMINATED:
                        log.info(f"🔄 Marking worker {worker.id()} as TERMINATED based on AWS state")
                        worker.terminate(terminated_by="system-sync")
                        updated = True

                    if updated or ip_changed:
                        try:
                            await self.cml_worker_repository.update_async(worker)
                            updated_ids.append(worker.id())
                        except Exception as e:
                            log.error(f"Failed to update worker {worker.id()}: {e}")

                    skipped_instances.append({"instance_id": instance_id, "reason": "Already registered"})
                    continue

                # Skip terminated instances (don't import them)
                if instance_state in ("terminated", "shutting-down"):
                    skipped_instances.append({"instance_id": instance_id, "reason": f"Instance state: {instance_state}"})
                    continue

                try:
                    # Create new CML Worker — use AWS EC2 Name tag if available
                    worker_name = instance_data.get("name") or f"worker-{instance_id}"

                    worker = CMLWorker.import_from_existing_instance(
                        name=worker_name,
                        aws_region=command.aws_region,
                        aws_instance_id=instance_id,
                        instance_type=instance_data.get("instance_type"),
                        ami_id=instance_data.get("image_id"),  # AMI ID from EC2 discovery
                        instance_state=instance_state,
                        created_by=command.source,
                        ami_name=None,  # Populated later by worker-controller EC2 details report
                        ami_description=None,  # Populated later by worker-controller EC2 details report
                        ami_creation_date=None,  # Populated later by worker-controller EC2 details report
                        public_ip=instance_data.get("public_ip"),
                        private_ip=instance_data.get("private_ip"),
                    )

                    saved_worker = await self.cml_worker_repository.add_async(worker)
                    imported_ids.append(saved_worker.id())

                    log.info(f"✅ Worker imported: id={saved_worker.id()}, instance_id={instance_id}")

                except Exception as e:
                    log.error(f"❌ Failed to import instance {instance_id}: {e}", exc_info=True)
                    skipped_instances.append({"instance_id": instance_id, "reason": f"Import failed: {str(e)}"})

            result = InternalBulkImportResult(
                imported=imported_ids,
                skipped=skipped_instances,
                updated=updated_ids,
                total_found=len(command.discovered_instances),
                total_imported=len(imported_ids),
                total_skipped=len(skipped_instances),
                total_updated=len(updated_ids),
            )

            span.set_attribute("import.imported_count", result.total_imported)
            span.set_attribute("import.skipped_count", result.total_skipped)
            span.set_attribute("import.updated_count", result.total_updated)

            log.info(f"🎉 Internal bulk import complete: imported={result.total_imported}, skipped={result.total_skipped}, updated={result.total_updated}")

            return self.ok(result)
