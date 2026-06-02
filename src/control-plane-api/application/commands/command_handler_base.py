"""Base class for command handlers with automatic OTEL span enrichment.

ADR-042: CommandHandlerBase is a zero-dependency observability shell,
symmetric with QueryHandlerBase. Each concrete handler declares only the
dependencies it actually uses in its own __init__.

All command handlers inheriting from this base automatically get their
request dataclass fields added as span attributes on the
TracingPipelineBehavior's span.

Usage:
    class CreateWorkerCommandHandler(
        CommandHandlerBase,
        CommandHandler[CreateWorkerCommand, OperationResult[dict]],
    ):
        def __init__(self, worker_repository: CMLWorkerRepository):
            self.worker_repository = worker_repository

        async def handle_async(self, request):
            ...
"""

from infrastructure.observability.cqrs_instrumentation import wrap_handle_async_with_enrichment
from neuroglia.mediation import CommandHandler


class CommandHandlerBase(CommandHandler):
    """Base class for command handlers with automatic OTEL span enrichment.

    Observability:
        All subclasses automatically get OTEL span enrichment via __init_subclass__.
        The TracingPipelineBehavior (registered by Observability.configure) creates the
        parent span; this base class enriches it with request dataclass field values.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        wrap_handle_async_with_enrichment(cls)
