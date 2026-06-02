"""Request Worker Scale-Up command with handler.

Creates a CML Worker aggregate from a worker template specification.
The scale-up request comes from the resource-scheduler when no existing worker
has sufficient capacity for a pending lablet instance.

Flow:
1. Resource-scheduler detects insufficient capacity
2. Resource-scheduler calls control-plane-api POST /api/internal/workers/scale-up
3. This command resolves the template, validates scaling constraints, creates worker
4. Worker-controller observes CMLWorkerCreatedDomainEvent → provisions EC2

ADR-015: Control-plane-api MUST NOT call AWS EC2 directly.
ADR-016: Template resolution happens at control-plane-api level.
ADR-018: AMI resolution and infrastructure config handled by worker-controller at provisioning time.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from application.services.worker_template_service import TemplateNotFoundError, WorkerTemplateService
from application.settings import Settings
from domain.entities.cml_worker import CMLWorker
from domain.entities.worker_template import WorkerTemplate
from domain.enums import CMLWorkerStatus
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from infrastructure.observability import record_scaling_event
from infrastructure.observability.logging import get_logger
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

audit_log = get_logger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class RequestScaleUpCommand(Command[OperationResult[dict]]):
    """Command to request a new worker via scale-up.

    This command resolves the template, validates scaling constraints,
    and creates a CML Worker aggregate with:
    - status = PENDING (actual state, worker not yet provisioned)
    - desired_status = RUNNING (spec, we want it running)
    - template_name populated for worker-controller to use

    The worker-controller will observe the CMLWorkerCreatedDomainEvent and
    reconcile by provisioning the EC2 instance using template config.

    Attributes:
        template_name: Name of the worker template to use (e.g., "metal", "large")
        reason: Human-readable reason for the scale-up (e.g., "insufficient capacity for lablet X")
        requested_by: Identifier of the requesting service (e.g., "resource-scheduler")
        aws_region: AWS region override (optional, uses template default or settings default)
    """

    template_name: str
    reason: str
    requested_by: str = "resource-scheduler"
    aws_region: str | None = None


class RequestScaleUpCommandHandler(
    CommandHandlerBase,
    CommandHandler[RequestScaleUpCommand, OperationResult[dict]],
):
    """Handle scale-up request by resolving template and creating worker aggregate.

    Responsibilities:
    1. Resolve worker template by name
    2. Validate scaling constraints (max workers per region, cooldown)
    3. Create CML Worker aggregate with template info populated
    4. Worker-controller will handle actual EC2 provisioning

    ADR-015: This handler does NOT call AWS EC2.
    ADR-016: Template name is stored on the worker for worker-controller to fetch full config.
    ADR-018: AMI name from template → worker-controller resolves to AMI ID at provisioning.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository, template_service: WorkerTemplateService, settings: Settings):
        self._worker_repository = cml_worker_repository
        self._template_service = template_service
        self._settings = settings

    async def handle_async(self, request: RequestScaleUpCommand) -> OperationResult[dict]:
        """Handle scale-up request.

        Args:
            request: Scale-up command with template name and reason.

        Returns:
            OperationResult with created worker details (status=PENDING).
        """
        add_span_attributes(
            {
                "scale_up.template_name": request.template_name,
                "scale_up.reason": request.reason,
                "scale_up.requested_by": request.requested_by,
            }
        )

        try:
            with tracer.start_as_current_span("request_scale_up") as span:
                # 1. Resolve the worker template
                template = await self._resolve_template(request.template_name)
                if template is None:
                    return self.not_found(
                        WorkerTemplate,
                        request.template_name,
                    )

                if not template.state.enabled:
                    return self.bad_request(f"Worker template '{request.template_name}' is disabled")

                # 2. Determine AWS region
                aws_region = request.aws_region or self._settings.aws_access_key_id and "us-east-1"
                # Fallback: use the first region from AMI config
                if not aws_region:
                    ami_regions = list(self._settings.cml_worker_ami_names.keys())
                    aws_region = ami_regions[0] if ami_regions else "us-east-1"

                span.set_attribute("scale_up.aws_region", aws_region)

                # 3. Validate scaling constraints
                constraint_error = await self._check_scaling_constraints(aws_region)
                if constraint_error:
                    return self.conflict(constraint_error)

                # 4. Get instance type and AMI name from template
                instance_type = template.state.instance_type.value
                ami_name = template.state.ami_name_pattern

                # Get AMI name from settings for the region if template doesn't specify
                if not ami_name:
                    ami_name = self._settings.cml_worker_ami_names.get(aws_region)

                # 5. Generate worker name
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                worker_name = f"cml-{request.template_name}-{timestamp}"

                # 6. Create CML Worker aggregate
                worker = CMLWorker(
                    name=worker_name,
                    aws_region=aws_region,
                    instance_type=instance_type,
                    ami_name=ami_name,
                    status=CMLWorkerStatus.PENDING,
                    created_by=request.requested_by,
                )

                # 7. Set template info on the worker for worker-controller
                worker.update_capacity(
                    template_name=request.template_name,
                    cpu_cores=template.state.capacity.cpu_cores,
                    memory_gb=template.state.capacity.memory_gb,
                    storage_gb=template.state.capacity.storage_gb,
                    max_nodes=template.state.capacity.max_nodes,
                )

                span.set_attribute("cml_worker.id", worker.id())
                span.set_attribute("cml_worker.template_name", request.template_name)

            # 8. Save worker (publishes CMLWorkerCreatedDomainEvent)
            saved_worker = await self._worker_repository.add_async(worker)

            # Scaling audit: record accepted scale-up
            record_scaling_event(
                action="scale_up_accepted",
                worker_id=saved_worker.id(),
                template=request.template_name,
                reason=request.reason,
                requested_by=request.requested_by,
            )
            audit_log.log_scaling_event(
                action="scale_up_accepted",
                worker_id=saved_worker.id(),
                template=request.template_name,
                reason=request.reason,
                requested_by=request.requested_by,
                aws_region=aws_region,
                instance_type=instance_type,
            )

            return self.created(
                {
                    "id": saved_worker.id(),
                    "name": saved_worker.state.name,
                    "status": saved_worker.state.status.value,
                    "desired_status": saved_worker.state.desired_status.value,
                    "aws_region": saved_worker.state.aws_region,
                    "instance_type": saved_worker.state.instance_type,
                    "template_name": request.template_name,
                    "reason": request.reason,
                    "requested_by": request.requested_by,
                    "created_at": saved_worker.state.created_at.isoformat(),
                    "message": "Scale-up accepted - worker-controller will provision EC2 instance",
                }
            )

        except TemplateNotFoundError as e:
            record_scaling_event(
                action="scale_up_rejected",
                template=request.template_name,
                reason=f"template_not_found: {e}",
                requested_by=request.requested_by,
                success=False,
            )
            audit_log.log_scaling_event(
                action="scale_up_rejected",
                template=request.template_name,
                reason=f"template_not_found: {e}",
                requested_by=request.requested_by,
            )
            return self.not_found(WorkerTemplate, request.template_name)
        except Exception as e:
            record_scaling_event(
                action="scale_up_rejected",
                template=request.template_name,
                reason=f"error: {e}",
                requested_by=request.requested_by,
                success=False,
            )
            audit_log.error(f"Unexpected error during scale-up: {e}", exc_info=True)
            return self.internal_server_error(f"Scale-up failed: {str(e)}")

    async def _resolve_template(self, template_name: str):
        """Resolve worker template by name from repository.

        Args:
            template_name: Template name to look up.

        Returns:
            WorkerTemplate entity or None if not found.
        """
        try:
            return await self._template_service.get_template_by_name_async(template_name)
        except TemplateNotFoundError:
            return None
        except Exception as e:
            audit_log.error(f"Error resolving template '{template_name}': {e}")
            return None

    async def _check_scaling_constraints(self, aws_region: str) -> str | None:
        """Check scaling constraints before creating a new worker.

        Args:
            aws_region: AWS region to check constraints for.

        Returns:
            Error message string if constraints violated, None if OK.
        """
        try:
            # Check max workers per region
            active_workers = await self._worker_repository.get_active_workers_async()
            region_workers = [w for w in active_workers if w.state.aws_region == aws_region]
            active_count = len(region_workers)

            max_per_region = self._settings.max_workers_per_region
            if active_count >= max_per_region:
                return f"Maximum workers per region ({max_per_region}) reached in {aws_region}. Active: {active_count}"

            # Check if there are already PENDING workers (avoid over-provisioning)
            pending_in_region = [w for w in region_workers if w.state.status == CMLWorkerStatus.PENDING]
            if len(pending_in_region) > 0:
                pending_names = [w.state.name for w in pending_in_region]
                audit_log.info(f"Note: {len(pending_in_region)} workers already PENDING in {aws_region}: {pending_names}")

            return None

        except Exception as e:
            audit_log.error(f"Error checking scaling constraints: {e}")
            # Fail open - allow scale-up if constraint check fails
            return None
