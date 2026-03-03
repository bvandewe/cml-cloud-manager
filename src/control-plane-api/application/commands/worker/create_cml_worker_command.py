"""Create CML Worker command with handler.

Creates a CML Worker domain aggregate with status=PENDING, desired_status=RUNNING.
The worker-controller will observe the CMLWorkerCreatedDomainEvent and
reconcile by provisioning the actual EC2 instance.

ADR-015: Control-plane-api MUST NOT call AWS EC2 directly.
This follows the Kubernetes-like reconciliation pattern:
- desired_status = spec (what user wants)
- status = state (actual EC2 state)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from neuroglia.core import OperationResult
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_bus import CloudEventBus
from neuroglia.eventing.cloud_events.infrastructure.cloud_event_publisher import CloudEventPublishingOptions
from neuroglia.mapping import Mapper
from neuroglia.mediation import Command, CommandHandler, Mediator
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from application.services.system_configuration_service import SystemConfigurationService
from application.settings import Settings
from domain.entities.cml_worker import CMLWorker
from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class CreateCMLWorkerCommand(Command[OperationResult[dict]]):
    """Command to create a new CML Worker (spec update).

    This command creates the CML Worker aggregate with:
    - status = PENDING (actual state, worker not yet provisioned)
    - desired_status = RUNNING (spec, user wants it running)

    The worker-controller will observe the CMLWorkerCreatedDomainEvent and
    reconcile by provisioning the EC2 instance.

    Pattern: spec (desired_status) vs state (status) reconciliation

    Attributes:
        name: Worker name (display name)
        aws_region: AWS region for EC2 instance
        instance_type: EC2 instance type (e.g., m5zn.metal)
        ami_id: Specific AMI ID (optional, worker-controller will resolve)
        ami_name: AMI name pattern (optional, worker-controller will resolve)
        cml_version: CML version tag (optional)
        created_by: User ID who initiated the creation
    """

    name: str
    aws_region: str
    instance_type: str
    ami_id: str | None = None
    ami_name: str | None = None
    cml_version: str | None = None
    created_by: str | None = None


class CreateCMLWorkerCommandHandler(
    CommandHandlerBase,
    CommandHandler[CreateCMLWorkerCommand, OperationResult[dict]],
):
    """Handle CML Worker creation by creating the domain aggregate.

    ADR-015: This handler does NOT call AWS EC2. It only creates the
    domain aggregate with PENDING status. Worker-controller provisions
    the actual EC2 instance.
    """

    def __init__(
        self,
        mediator: Mediator,
        mapper: Mapper,
        cloud_event_bus: CloudEventBus,
        cloud_event_publishing_options: CloudEventPublishingOptions,
        cml_worker_repository: CMLWorkerRepository,
        settings: Settings,
        configuration_service: SystemConfigurationService,
    ):
        super().__init__(
            mediator,
            mapper,
            cloud_event_bus,
            cloud_event_publishing_options,
        )
        self.cml_worker_repository = cml_worker_repository
        self.settings = settings
        self.configuration_service = configuration_service

    async def handle_async(self, request: CreateCMLWorkerCommand) -> OperationResult[dict]:
        """Handle create CML Worker command.

        Creates the domain aggregate with PENDING status and RUNNING desired_status.
        Worker-controller will observe the event and provision EC2.

        Args:
            request: Create command with worker specifications

        Returns:
            OperationResult with created worker details (status=PENDING)
        """
        command = request

        # Add tracing context
        add_span_attributes(
            {
                "cml_worker.name": command.name,
                "cml_worker.region": command.aws_region,
                "cml_worker.instance_type": command.instance_type,
                "cml_worker.has_created_by": command.created_by is not None,
            }
        )

        try:
            with tracer.start_as_current_span("create_cml_worker_aggregate") as span:
                # Determine AMI ID/name from settings if not provided
                # Note: Worker-controller will validate and resolve full AMI details from AWS
                ami_id = command.ami_id
                ami_name = command.ami_name

                if not ami_id:
                    # Get effective provisioning settings
                    prov_settings = await self.configuration_service.get_worker_provisioning_settings_async()

                    # Get AMI from settings for the specified region
                    region_ami_ids = self.settings.cml_worker_ami_ids
                    if command.aws_region in region_ami_ids:
                        ami_id = region_ami_ids[command.aws_region]

                    # Get AMI name from settings
                    region_ami_names = self.settings.cml_worker_ami_names
                    ami_name = region_ami_names.get(command.aws_region, prov_settings.ami_name_default)

                # ADR-015: We do NOT fetch AMI details from AWS here.
                # Worker-controller will validate AMI and fetch details during provisioning.

                # Create CML Worker domain aggregate (PENDING status, RUNNING desired_status)
                worker = CMLWorker(
                    name=command.name,
                    aws_region=command.aws_region,
                    instance_type=command.instance_type,
                    ami_id=ami_id,
                    ami_name=ami_name,
                    ami_description=None,  # Worker-controller will populate
                    ami_creation_date=None,  # Worker-controller will populate
                    status=CMLWorkerStatus.PENDING,
                    cml_version=command.cml_version,
                    created_at=datetime.now(timezone.utc),
                    created_by=command.created_by,
                )

                span.set_attribute("cml_worker.id", worker.id())
                span.set_attribute("cml_worker.status", CMLWorkerStatus.PENDING.value)
                span.set_attribute("cml_worker.desired_status", CMLWorkerStatus.RUNNING.value)

            # Save worker (will publish CMLWorkerCreatedDomainEvent)
            # Worker-controller observes this event and provisions EC2 instance
            saved_worker = await self.cml_worker_repository.add_async(worker)

            log.info(f"CML Worker created with status=PENDING, desired_status=RUNNING: id={saved_worker.id()}, name={command.name}. Worker-controller will provision EC2 instance.")

            # Return worker details including spec vs state
            return self.created(
                {
                    "id": saved_worker.id(),
                    "name": saved_worker.state.name,
                    "status": saved_worker.state.status.value,
                    "desired_status": saved_worker.state.desired_status.value,
                    "aws_region": saved_worker.state.aws_region,
                    "instance_type": saved_worker.state.instance_type,
                    "ami_id": saved_worker.state.ami_id,
                    "ami_name": saved_worker.state.ami_name,
                    "created_at": saved_worker.state.created_at.isoformat(),
                    "message": "Worker created - worker-controller will provision",
                }
            )

        except Exception as e:
            log.error(f"Unexpected error creating CML Worker: {e}", exc_info=True)
            return self.internal_server_error(f"Unexpected error: {str(e)}")
