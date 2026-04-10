"""Lab lifecycle step handlers — lab_start, stop_lab, wipe_lab.

ADR-038: Extracted from LabletReconciler._step_lab_start/stop_lab/wipe_lab.

These steps handle CML lab state transitions:
7. lab_start — start the CML lab and poll until STARTED + converged
T1. stop_lab — stop the CML lab and poll until STOPPED
T3. wipe_lab — wipe the CML lab (reset to DEFINED_ON_CORE)

ADR-038 Task 1: Parity gaps closed — lab_start now marks ghost labs as
ORPHANED via ``context.update_lab_record_status``, and wipe_lab updates
the LabRecord status to WIPED after successful wipe.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler
from integration.services.cml_labs_spi import LabState

logger = logging.getLogger(__name__)


def _get_step_result_data(progress: dict[str, Any], step_name: str) -> dict[str, Any] | None:
    """Extract result_data from a completed step in the progress dict."""
    step_info = progress.get(step_name)
    if not step_info or not isinstance(step_info, dict):
        return None
    return step_info.get("result_data")


@step_handler("lab_start")
async def step_lab_start(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Start the CML lab and poll until STARTED + converged.

    If lab is already STARTED and converged (reuse case), completes immediately.
    If lab is STOPPED/DEFINED_ON_CORE, starts it then polls.
    If lab is STARTED/QUEUED, polls until converged (all nodes ready).

    Polls every ``_LAB_BOOT_POLL_INTERVAL`` seconds. The executor's
    ``timeout_seconds`` (typically 300s) bounds the total wait via
    ``asyncio.wait_for()``, so this loop is safe from hanging.
    """
    _LAB_BOOT_POLL_INTERVAL = 20  # seconds between state checks
    _NODE_DIAG_EVERY_N_POLLS = 3  # fetch node states every Nth poll (~60s)

    resolve_data = _get_step_result_data(progress, "lab_resolve")
    cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id from lab_resolve")

    try:
        lab_state = await context.cml.get_lab_state(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
    except Exception as e:
        return StepResult.failed(f"Failed to get lab state: {e}")

    # Guard: lab must actually exist on the CML worker
    if lab_state is None:
        logger.error(f"👻 Lab {cml_lab_id} does not exist on worker {context.worker_ip} (session={instance.id})")
        # Mark the LabRecord as ORPHANED if we have the helper and a worker_id
        if instance.worker_id and context.update_lab_record_status:
            try:
                await context.update_lab_record_status(cml_lab_id, instance.worker_id, "orphaned")
            except Exception as e:
                logger.warning(f"Failed to mark lab {cml_lab_id} as ORPHANED: {e}")
        return StepResult.failed(f"Lab {cml_lab_id} not found on worker (ghost lab) — LabRecord marked ORPHANED")

    if lab_state == LabState.STARTED:
        # Lab is already running — check if nodes have converged
        try:
            converged = await context.cml.check_if_converged(
                host=context.worker_ip,
                lab_id=cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
        except Exception as e:
            logger.warning(f"Convergence check failed for already-STARTED lab {cml_lab_id}: {e}")
            converged = False

        if converged:
            logger.info(f"Lab {cml_lab_id} already STARTED and converged for session {instance.id}")
            return StepResult.completed({"lab_state": "CONVERGED", "cml_lab_id": cml_lab_id})
        # Not yet converged — fall through to polling loop

    elif lab_state in (LabState.STOPPED, LabState.DEFINED_ON_CORE):
        # Start the lab
        try:
            await context.cml.start_lab(
                host=context.worker_ip,
                lab_id=cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
            logger.info(f"Lab {cml_lab_id} start initiated for session {instance.id}")
        except Exception as e:
            return StepResult.failed(f"Failed to start lab: {e}")

    # Poll for convergence (bounded by executor's per-step timeout)
    poll_count = 0
    while True:
        await asyncio.sleep(_LAB_BOOT_POLL_INTERVAL)
        poll_count += 1

        try:
            lab_state = await context.cml.get_lab_state(
                host=context.worker_ip,
                lab_id=cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
        except Exception as e:
            logger.warning(f"Lab {cml_lab_id} state poll #{poll_count} failed: {e}")
            continue

        if lab_state == LabState.QUEUED:
            logger.debug(f"Lab {cml_lab_id} still QUEUED (poll #{poll_count}), waiting...")
            continue

        if lab_state != LabState.STARTED:
            return StepResult.failed(f"Lab entered unexpected state {lab_state} while waiting for convergence")

        try:
            converged = await context.cml.check_if_converged(
                host=context.worker_ip,
                lab_id=cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
        except Exception as e:
            logger.warning(f"Lab {cml_lab_id} convergence check #{poll_count} failed: {e}")
            converged = False

        if converged:
            logger.info(f"Lab {cml_lab_id} converged after {poll_count} polls for session {instance.id}")
            return StepResult.completed({"lab_state": "CONVERGED", "cml_lab_id": cml_lab_id})

        logger.debug(f"Lab {cml_lab_id} STARTED but not converged (poll #{poll_count}), waiting...")

        # Periodic node diagnostics
        if poll_count == 1 or poll_count % _NODE_DIAG_EVERY_N_POLLS == 0:
            try:
                nodes = await context.cml.get_lab_nodes(
                    host=context.worker_ip,
                    lab_id=cml_lab_id,
                    username=context.worker_cml_username,
                    password=context.worker_cml_password,
                )
                state_groups: dict[str, list[str]] = {}
                for node in nodes:
                    state_groups.setdefault(node.state, []).append(f"{node.label}({node.node_definition})")
                summary_parts = [f"{state}: {', '.join(labels)}" for state, labels in sorted(state_groups.items())]
                logger.info(f"🔍 Lab {cml_lab_id} node boot status (session={instance.id}, poll #{poll_count}, {len(nodes)} nodes): {' | '.join(summary_parts)}")
            except Exception as diag_err:
                logger.debug(f"Node diagnostic fetch failed for lab {cml_lab_id}: {diag_err}")


@step_handler("stop_lab")
async def step_stop_lab(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Stop the CML lab and poll until STOPPED.

    CML Labs SPI: PUT /api/v0/labs/{id}/stop
    """
    if not instance.cml_lab_id:
        return StepResult.completed({"lab_state": "NO_LAB"})

    try:
        lab_state = await context.cml.get_lab_state(
            host=context.worker_ip,
            lab_id=instance.cml_lab_id,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
    except Exception as e:
        return StepResult.failed(f"Failed to get lab state: {e}")

    if lab_state in (LabState.STOPPED, LabState.DEFINED_ON_CORE):
        return StepResult.completed({"lab_state": str(lab_state)})

    if lab_state == LabState.STARTED:
        try:
            await context.cml.stop_lab(
                host=context.worker_ip,
                lab_id=instance.cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
            logger.info(f"Lab {instance.cml_lab_id} stop initiated for session {instance.id}")
        except Exception as e:
            return StepResult.failed(f"Failed to stop lab: {e}")

    # Poll until STOPPED (bounded by executor's per-step timeout)
    while True:
        await asyncio.sleep(5)
        try:
            lab_state = await context.cml.get_lab_state(
                host=context.worker_ip,
                lab_id=instance.cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
        except Exception as e:
            return StepResult.failed(f"Failed to poll lab state: {e}")

        if lab_state in (LabState.STOPPED, LabState.DEFINED_ON_CORE):
            logger.info(f"Lab {instance.cml_lab_id} stopped (state={lab_state}) for session {instance.id}")
            return StepResult.completed({"lab_state": str(lab_state)})


@step_handler("wipe_lab")
async def step_wipe_lab(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Wipe the CML lab (reset to DEFINED_ON_CORE).

    Preserves topology for reuse — does NOT delete the lab.
    CML Labs SPI: PUT /api/v0/labs/{id}/wipe

    ADR-038 Task 1 parity: Updates LabRecord status to WIPED via
    ``context.update_lab_record_status`` after successful wipe.
    """
    if not instance.cml_lab_id:
        return StepResult.completed({"lab_wiped": False})

    try:
        await context.cml.wipe_lab(
            host=context.worker_ip,
            lab_id=instance.cml_lab_id,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
        # Update LabRecord status to WIPED (best-effort)
        if instance.worker_id and context.update_lab_record_status:
            try:
                await context.update_lab_record_status(instance.cml_lab_id, instance.worker_id, "wiped")
            except Exception as e:
                logger.warning(f"Failed to update lab record status to WIPED for {instance.cml_lab_id}: {e}")
        logger.info(f"Lab {instance.cml_lab_id} wiped for session {instance.id}")
        return StepResult.completed({"lab_wiped": True})
    except Exception as e:
        return StepResult.failed(f"Failed to wipe lab: {e}")
