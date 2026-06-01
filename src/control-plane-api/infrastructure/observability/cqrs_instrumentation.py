"""Automatic CQRS handler instrumentation for OpenTelemetry.

This module provides utilities to automatically enrich OTEL spans created by
Neuroglia's TracingPipelineBehavior with domain-specific request attributes.

The TracingPipelineBehavior (registered by Observability.configure()) already
creates spans for ALL commands and queries. This module adds request field
values as span attributes so traces contain actionable domain context.

Architecture:
    TracingPipelineBehavior creates span "Command.CreateWorkerCommand"
    -> Our enrichment adds attributes: cqrs.request.worker_id="abc", etc.
    -> Handler executes (may add its own child span with deeper detail)

Usage in CommandHandlerBase:
    The __init_subclass__ hook wraps handle_async to auto-enrich spans.
    No per-handler code needed for basic observability.
"""

import functools
import logging

from opentelemetry import trace

log = logging.getLogger(__name__)

# Scalar types safe to record as span attributes
_ATTRIBUTE_SAFE_TYPES = (str, int, float, bool)

# Maximum attribute value length to prevent bloating spans
_MAX_ATTR_VALUE_LEN = 256


def enrich_span_with_request(request) -> None:
    """Add dataclass fields from a CQRS request to the current OTEL span.

    Extracts all scalar-typed fields from the request dataclass and sets them
    as span attributes with the `cqrs.request.` prefix.

    Args:
        request: A dataclass command or query instance.
    """
    span = trace.get_current_span()
    if not span or not span.is_recording():
        return

    fields = getattr(request, "__dataclass_fields__", None)
    if not fields:
        return

    for field_name in fields:
        value = getattr(request, field_name, None)
        if value is None:
            continue
        if isinstance(value, _ATTRIBUTE_SAFE_TYPES):
            attr_value = str(value) if not isinstance(value, (int, float, bool)) else value
            # Truncate long strings
            if isinstance(attr_value, str) and len(attr_value) > _MAX_ATTR_VALUE_LEN:
                attr_value = attr_value[:_MAX_ATTR_VALUE_LEN] + "..."
            span.set_attribute(f"cqrs.request.{field_name}", attr_value)


def wrap_handle_async_with_enrichment(cls) -> None:
    """Wrap a handler class's handle_async to auto-enrich spans with request attributes.

    This is called by __init_subclass__ in CommandHandlerBase and QueryHandlerBase.
    It wraps handle_async so that when the TracingPipelineBehavior's span is active,
    the request's dataclass fields are added as span attributes.

    Args:
        cls: The handler class being defined.
    """
    original = getattr(cls, "handle_async", None)
    if original is None:
        return

    # Skip if already wrapped (prevents double-wrapping on deep inheritance)
    if getattr(original, "_cqrs_enriched", False):
        return

    @functools.wraps(original)
    async def _enriched_handle_async(self, request, *args, **kwargs):
        enrich_span_with_request(request)
        return await original(self, request, *args, **kwargs)

    _enriched_handle_async._cqrs_enriched = True
    cls.handle_async = _enriched_handle_async


def instrumented(cls):
    """Class decorator to add automatic OTEL span enrichment to a CQRS handler.

    Use this on handlers that don't inherit from CommandHandlerBase or QueryHandlerBase
    but still need automatic span attribute enrichment.

    Example:
        @instrumented
        class MyCommandHandler(CommandHandler[MyCommand, OperationResult[dict]]):
            async def handle_async(self, request):
                ...
    """
    wrap_handle_async_with_enrichment(cls)
    return cls
