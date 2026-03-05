"""Update Worker EC2 Details command.

This command updates EC2 instance details for a worker, including:
- Public/Private IP addresses
- Instance type
- AMI information (ID, name, description, creation date)

Called by worker-controller after provisioning completes or during
on-demand refresh to report EC2 instance metadata.

Per ADR-001: All state mutations go through Control Plane API.
"""

import logging
from dataclasses import dataclass
from typing import Any

from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)


@dataclass
class UpdateWorkerEc2DetailsCommand(Command[OperationResult[dict[str, Any]]]):
    """Command to update EC2 instance details for a worker.

    Called by worker-controller to report EC2 instance metadata
    including AMI details after provisioning or on-demand refresh.
    """

    worker_id: str
    public_ip: str | None = None
    private_ip: str | None = None
    instance_type: str | None = None
    ami_id: str | None = None
    ami_name: str | None = None
    ami_description: str | None = None
    ami_creation_date: str | None = None


class UpdateWorkerEc2DetailsCommandHandler(
    CommandHandlerBase,
    CommandHandler[UpdateWorkerEc2DetailsCommand, OperationResult[dict[str, Any]]],
):
    """Handle updating EC2 instance details for a worker."""

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

    async def handle_async(self, request: UpdateWorkerEc2DetailsCommand) -> OperationResult[dict[str, Any]]:
        """Handle update worker EC2 details command.

        Calls the aggregate's update_ec2_instance_details() method which emits
        EC2InstanceDetailsUpdatedDomainEvent, populating AMI info and IP details.

        Args:
            request: Command with EC2 detail fields.

        Returns:
            OperationResult with acknowledgment or error.
        """
        log.info(f"Updating EC2 details for worker {request.worker_id}")

        # Retrieve worker from repository
        worker = await self.cml_worker_repository.get_by_id_async(request.worker_id)

        if not worker:
            return self.not_found("CMLWorker", f"Worker {request.worker_id} not found")

        # Update EC2 instance details via domain method
        try:
            worker.update_ec2_instance_details(
                public_ip=request.public_ip,
                private_ip=request.private_ip,
                instance_type=request.instance_type,
                ami_id=request.ami_id,
                ami_name=request.ami_name,
                ami_description=request.ami_description,
                ami_creation_date=request.ami_creation_date,
            )
        except Exception as e:
            log.error(f"Failed to update EC2 details for worker {request.worker_id}: {e}")
            return self.internal_server_error(f"Failed to update EC2 details: {e}")

        # Persist changes
        await self.cml_worker_repository.update_async(worker)

        return self.ok(
            {
                "worker_id": request.worker_id,
                "ec2_details_updated": True,
                "ami_id": request.ami_id,
                "ami_name": request.ami_name,
            }
        )
