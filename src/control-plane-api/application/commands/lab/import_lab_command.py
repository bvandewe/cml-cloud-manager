"""Import Lab Command - queues lab import for reconciliation (ADR-017).

ADR-017: Lab import operations use the reconciliation pattern:
1. Control-plane-api stores YAML in PendingLabImport (MongoDB)
2. Lablet-controller watches etcd, sees pending import
3. Lablet-controller imports the lab via CML API
4. Lablet-controller reports success/failure via internal API
"""

import logging
from dataclasses import dataclass

from domain.entities.pending_lab_import import PendingLabImport
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.pending_lab_import_repository import PendingLabImportRepository
from infrastructure.observability.cqrs_instrumentation import instrumented
from neuroglia.core.operation_result import OperationResult
from neuroglia.mediation import Command, CommandHandler, Mediator
from opentelemetry import trace

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class ImportLabCommand(Command[OperationResult[dict]]):
    """Command to import a lab topology from YAML.

    ADR-017: This command stores the YAML for reconciliation.
    The actual CML API call is performed by lablet-controller.

    Attributes:
        worker_id: Worker ID to import the lab to
        yaml_content: Lab topology in CML2 YAML format
        title: Optional title for the imported lab (overrides YAML title)
        requested_by: Optional username of the requester
    """

    worker_id: str
    yaml_content: str
    title: str | None = None
    requested_by: str | None = None


@instrumented
class ImportLabCommandHandler(CommandHandler[ImportLabCommand, OperationResult[dict]]):
    """Handler for ImportLabCommand - queues lab import for reconciliation.

    ADR-017: This handler stores the YAML in MongoDB, setting status=pending.
    Lablet-controller reconciles by importing the lab via CML API.
    """

    def __init__(
        self,
        mediator: Mediator,
        worker_repository: CMLWorkerRepository,
        pending_import_repository: PendingLabImportRepository,
    ):
        """Initialize handler with repository dependencies.

        Args:
            mediator: Mediator for triggering other commands
            worker_repository: Repository for accessing CML worker data
            pending_import_repository: Repository for pending lab imports
        """
        self._mediator = mediator
        self._worker_repository = worker_repository
        self._pending_import_repository = pending_import_repository

    async def handle_async(self, request: ImportLabCommand) -> OperationResult[dict]:
        """Queue lab import for reconciliation.

        ADR-017: Stores YAML in PendingLabImport, returns 202 Accepted.
        Lablet-controller will reconcile the actual import.

        Args:
            request: Command containing worker_id, yaml_content, and optional title

        Returns:
            OperationResult with accepted status (async processing)
        """
        with tracer.start_as_current_span("import_lab_command") as span:
            span.set_attribute("worker.id", request.worker_id)
            span.set_attribute("yaml.size", len(request.yaml_content) if request.yaml_content else 0)
            span.set_attribute("adr", "ADR-017")
            span.set_attribute("pattern", "reconciliation")

            try:
                # 1. Validate worker exists
                worker = await self._worker_repository.get_by_id_async(request.worker_id)
                if not worker:
                    error_msg = f"Worker {request.worker_id} not found"
                    log.error(error_msg)
                    return self.not_found("Worker", error_msg)

                # 2. Validate YAML content
                if not request.yaml_content or not request.yaml_content.strip():
                    return self.bad_request("YAML content is required")

                # 3. Create PendingLabImport record (stores YAML in MongoDB)
                pending_import = PendingLabImport.create(
                    worker_id=request.worker_id,
                    yaml_content=request.yaml_content,
                    title=request.title,
                    requested_by=request.requested_by,
                )

                # 4. Save to repository
                await self._pending_import_repository.add_async(pending_import)

                import_id = pending_import.id()
                log.info(f"Created pending lab import {import_id} for worker {request.worker_id}")

                span.set_attribute("import.id", import_id)

                # 5. Return 202 Accepted - lablet-controller will reconcile
                log.info(f"Lab import queued (import_id={import_id}). Lablet-controller will reconcile.")
                return self.accepted(
                    {
                        "import_id": import_id,
                        "worker_id": request.worker_id,
                        "title": request.title,
                        "status": "pending",
                        "message": "Import queued for reconciliation",
                    }
                )

            except Exception as e:
                error_msg = f"Error queuing lab import: {str(e)}"
                log.error(error_msg, exc_info=True)
                return self.internal_server_error(error_msg)
