"""Evidence collection step handlers — stubs.

ADR-038: Extracted from LabletReconciler evidence step stubs.

E1. capture_configs — export running-config from managed devices
E2. capture_screenshots — capture VNC screenshots of graphical nodes
E3. export_pcaps — export packet capture files
E4. package_evidence — bundle all artifacts into evidence package

All steps are stubs — real implementation in Sprint F+ when the
evidence collection subsystem is built.
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("capture_configs")
async def step_capture_configs(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Export running-config from all managed devices.

    Stub — will be implemented in Sprint F+.
    """
    logger.info(f"capture_configs not yet implemented for session {instance.id}")
    return StepResult.completed({"configs": [], "note": "stub"})


@step_handler("capture_screenshots")
async def step_capture_screenshots(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Capture VNC screenshots of graphical nodes.

    Stub — will be implemented in Sprint F+.
    """
    logger.info(f"capture_screenshots not yet implemented for session {instance.id}")
    return StepResult.completed({"screenshots": [], "note": "stub"})


@step_handler("export_pcaps")
async def step_export_pcaps(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Export packet capture files from bridge interfaces.

    Stub — will be implemented in Sprint F+.
    """
    logger.info(f"export_pcaps not yet implemented for session {instance.id}")
    return StepResult.completed({"pcaps": [], "note": "stub"})


@step_handler("package_evidence")
async def step_package_evidence(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Bundle all artifacts into a compressed evidence package.

    Stub — will be implemented in Sprint F+.
    """
    logger.info(f"package_evidence not yet implemented for session {instance.id}")
    return StepResult.completed({"evidence_uri": None, "note": "stub — no evidence collected yet"})
