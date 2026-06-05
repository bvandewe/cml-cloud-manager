"""Content sync step handler — content_sync.

Verifies definition content is synced and available before proceeding
with lab import or LDS provisioning.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("content_sync")
async def step_content_sync(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Verify definition content is synced and available (§6).

    Fail-fast prerequisite — if content is not synced, there is no
    point importing a lab (LDS provisioning requires the form and content).

    If content is not synced, triggers a content sync request via
    ``context.request_content_sync``.
    """
    definition = context.definition
    if not definition:
        return StepResult.failed("Definition not found")

    if not getattr(definition, "content_sync_enabled", False):
        return StepResult.skipped("Content sync not enabled")

    sync_status = getattr(definition, "sync_status", None)
    if sync_status == "synced":
        return StepResult.completed(
            {
                "sync_status": sync_status,
                "form_qualified_name": definition.form_qualified_name,
            }
        )

    # Not synced — optionally trigger sync and fail (will retry on next reconcile)
    if context.request_content_sync and sync_status in (None, "not_synced", "sync_failed"):
        try:
            await context.request_content_sync(definition.id)
        except Exception as e:
            logger.warning(f"Could not trigger content sync for {definition.id}: {e}")

    return StepResult.failed(f"Content not synced (status: {sync_status}). Waiting for sync.")
