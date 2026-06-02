"""Enable CloudWatch Detailed Monitoring Command.

ADR-015: This command is DB-only. It sets the desired monitoring configuration
in MongoDB. The worker-controller watches etcd for state changes and
enables detailed monitoring on the EC2 instance.
"""

import logging
from dataclasses import dataclass

from domain.repositories.cml_worker_repository import CMLWorkerRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from neuroglia.observability.tracing import add_span_attributes
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class EnableWorkerDetailedMonitoringCommand(Command[OperationResult[bool]]):
    """Command to enable detailed CloudWatch monitoring on a worker.

    ADR-015: This command is DB-only. It does NOT make EC2 API calls.

    This sets the desired monitoring configuration in the database.
    The worker-controller watches etcd and enables actual monitoring on EC2.

    Detailed monitoring enables 1-minute metric granularity instead of 5-minute.
    Cost: ~$2.10/month per instance.
    """

    worker_id: str


class EnableWorkerDetailedMonitoringCommandHandler(
    CommandHandlerBase,
    CommandHandler[EnableWorkerDetailedMonitoringCommand, OperationResult[bool]],
):
    """Handle enabling detailed monitoring on workers (DB-only per ADR-015).

    Does NOT make EC2 API calls. Worker-controller handles actual
    EC2 monitoring configuration by watching etcd for state changes.
    """

    def __init__(self, cml_worker_repository: CMLWorkerRepository):
        self.cml_worker_repository = cml_worker_repository

    async def handle_async(self, request: EnableWorkerDetailedMonitoringCommand) -> OperationResult[bool]:
        """Enable detailed monitoring on worker (DB-only).

        ADR-015: DB-only operation. No EC2 calls.

        Args:
            request: Command with worker ID

        Returns:
            OperationResult with True if configuration saved successfully
        """
        command = request

        add_span_attributes({"cml_worker.id": command.worker_id})

        try:
            with tracer.start_as_current_span("retrieve_cml_worker") as span:
                # Load worker
                worker = await self.cml_worker_repository.get_by_id_async(command.worker_id)
                if not worker:
                    error_msg = f"Worker not found: {command.worker_id}"
                    log.error(error_msg)
                    return self.not_found("CMLWorker", error_msg)

                span.set_attribute("ec2.instance_id", worker.state.aws_instance_id or "none")

            with tracer.start_as_current_span("update_monitoring_config") as span:
                # Update worker aggregate with desired monitoring configuration
                # Worker-controller will watch etcd and apply to EC2
                worker.update_cloudwatch_monitoring(enabled=True)
                await self.cml_worker_repository.update_async(worker)

                span.set_attribute("cml_worker.detailed_monitoring_enabled", True)

            log.info(
                f"Detailed CloudWatch monitoring enabled in DB for worker {command.worker_id}. Worker-controller will apply to EC2 instance {worker.state.aws_instance_id or 'none'} via etcd watch."
            )

            return self.ok(True)

        except Exception as ex:
            log.exception(f"Unexpected error enabling monitoring for worker {command.worker_id}")
            return self.internal_server_error(f"Unexpected error: {ex}")
