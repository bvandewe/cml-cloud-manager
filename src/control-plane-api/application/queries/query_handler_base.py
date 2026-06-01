"""Base class for query handlers with automatic OTEL span enrichment.

All query handlers inheriting from this base automatically get their request
dataclass fields added as span attributes on the TracingPipelineBehavior's span.

Usage:
    class GetWorkerQueryHandler(
        QueryHandlerBase,
        QueryHandler[GetWorkerQuery, OperationResult[dict]],
    ):
        async def handle_async(self, request):
            ...
"""

from neuroglia.mediation import QueryHandler

from infrastructure.observability.cqrs_instrumentation import wrap_handle_async_with_enrichment


class QueryHandlerBase(QueryHandler):
    """Base class for query handlers with automatic OTEL span enrichment.

    Observability:
        All subclasses automatically get OTEL span enrichment via __init_subclass__.
        The TracingPipelineBehavior (registered by Observability.configure) creates the
        parent span; this base class enriches it with request dataclass field values.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        wrap_handle_async_with_enrichment(cls)
