"""Binding step handlers — lab_binding, lds_provision, mark_ready.

ADR-038: Extracted from LabletReconciler._step_lab_binding/lds_provision/mark_ready.

These steps handle session binding and readiness:
6. lab_binding — bind LabRecord to session and create LabRunRecord
8. lds_provision — create LDS session, map devices, get launch URL
9. mark_ready — atomic transition to READY status

ADR-038 Task 1: Parity gaps closed — handlers now use enriched PipelineContext
callables (find_lab_record_id, register_lab_record, build_device_access_list)
and shared tracking state (resolved_lab_ids, freshly_imported_sessions).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from integration.services.lds_spi import DeviceAccessInfo, LdsSpiError
from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.reconciler_helpers.lds_helpers import build_device_access_from_allocated_ports
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


def _get_step_result_data(progress: dict[str, Any], step_name: str) -> dict[str, Any] | None:
    """Extract result_data from a completed step in the progress dict."""
    step_info = progress.get(step_name)
    if not step_info or not isinstance(step_info, dict):
        return None
    return step_info.get("result_data")


def _build_device_access_list_simple(nodes: list, worker_ip: str) -> list[DeviceAccessInfo]:
    """Build device access info list from CML nodes (simple, no multi-tag suffixing).

    This is the fallback when ``context.build_device_access_list`` is not available.
    For the full implementation with multi-tag label suffixing, the reconciler's
    static method is used via the context callable.

    Args:
        nodes: List of NodeInfo from CML Labs SPI.
        worker_ip: Worker IP address for device access.

    Returns:
        List of DeviceAccessInfo for LDS provisioning.
    """
    devices: list[DeviceAccessInfo] = []
    for node in nodes:
        if not node.tags:
            continue
        for tag in node.tags:
            if ":" in tag:
                protocol, port_str = tag.split(":", 1)
                try:
                    port = int(port_str)
                except ValueError:
                    continue
                devices.append(
                    DeviceAccessInfo(
                        device_label=node.label,
                        protocol=protocol,
                        host=worker_ip,
                        port=port,
                    )
                )
    return devices


@step_handler("lab_binding")
async def step_lab_binding(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Bind LabRecord to session and create LabRunRecord (§4.3).

    Calls CPA ``bind_lab_to_session()`` which:
    1. Creates a LabRunRecord (runtime tracking)
    2. Sets ``active_lablet_session_id`` on LabRecord
    3. Denormalizes ``LabRecord.allocated_ports`` onto LabletSession

    ADR-038 Task 1 parity: If ``lab_record_id`` is missing from lab_resolve
    result data, attempts full fallback chain: find → register → fail.
    Uses ``context.find_lab_record_id`` and ``context.register_lab_record``.
    """
    resolve_data = _get_step_result_data(progress, "lab_resolve")
    cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
    lab_record_id = resolve_data.get("lab_record_id") if resolve_data else None

    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id from lab_resolve")

    # Resilient fallback: resolve lab_record_id if missing from stale progress
    if not lab_record_id:
        logger.warning(f"lab_binding: lab_record_id missing from lab_resolve data for lab {cml_lab_id} — attempting to find or register LabRecord")
        # Step 1: Try to find existing LabRecord
        if context.find_lab_record_id:
            lab_record_id = await context.find_lab_record_id(cml_lab_id, instance.worker_id or "")

        # Step 2: Register if not found
        if not lab_record_id and context.register_lab_record:
            lab_record_id = await context.register_lab_record(cml_lab_id, instance)

        # Step 3: Direct CPA fallback
        if not lab_record_id:
            try:
                records = await context.api.get_lab_records_for_worker(worker_id=instance.worker_id or "")
                for lr in records:
                    if lr.get("lab_id") == cml_lab_id:
                        lab_record_id = lr.get("id")
                        break
            except Exception as e:
                logger.warning(f"lab_binding: fallback lookup failed: {e}")

        if not lab_record_id:
            return StepResult.failed(f"No lab_record_id for lab {cml_lab_id} — find and register both failed")
        logger.info(f"lab_binding: resolved lab_record_id={lab_record_id} via fallback")

    cml_lab_title = resolve_data.get("cml_lab_title") if resolve_data else None

    try:
        result = await context.api.bind_lab_to_session(
            session_id=instance.id,
            worker_id=instance.worker_id,
            lab_record_id=lab_record_id,
            cml_lab_id=cml_lab_id,
            cml_lab_title=cml_lab_title,
        )
        return StepResult.completed(result)
    except Exception as e:
        return StepResult.failed(str(e))


@step_handler("lds_provision")
async def step_lds_provision(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Provision LDS session with device mapping (§2.2).

    Revised approach (FR-2.2.5d / AD-LDS-001):
    1. Read user_visible_devices from definition (extracted from content.xml)
    2. Read allocated_ports from ports_alloc step result
    3. Build device list by joining: only devices in BOTH sources
    4. Fallback: legacy tag-based path when no allocated_ports
    5. Create LDS session and set filtered devices
    """
    resolve_data = _get_step_result_data(progress, "lab_resolve")
    cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id from lab_resolve")

    definition = context.definition
    if not definition or not definition.form_qualified_name:
        return StepResult.skipped("No form_qualified_name — LDS not applicable")

    if not context.lds:
        return StepResult.skipped("LDS client not configured")

    try:
        # ── Get user-visible devices from definition (content.xml source) ──
        # None = field not populated (backward compat, include all devices)
        # [] = content.xml parsed but has no <device> elements (nothing visible)
        raw_visible = definition.user_visible_devices
        if raw_visible is None:
            visible_labels = None  # Backward compat: no filter
        else:
            visible_labels = {d["device_label"] for d in raw_visible}

        # ── Get allocated ports (source of truth for connectivity) ──
        ports_data = _get_step_result_data(progress, "ports_alloc")
        allocated_ports: dict[str, int] = {}
        if ports_data:
            allocated_ports = ports_data.get("allocated_ports", {})

        # ── Build filtered device list ──
        if allocated_ports:
            devices = build_device_access_from_allocated_ports(
                allocated_ports=allocated_ports,
                worker_ip=context.worker_ip,
                user_visible_labels=visible_labels,
            )
        else:
            # Fallback: legacy tag-based path (backward compat for definitions
            # synced before port_template support or when ports_alloc is skipped)
            nodes = await context.cml.get_lab_nodes(
                host=context.worker_ip,
                lab_id=cml_lab_id,
                username=context.worker_cml_username,
                password=context.worker_cml_password,
            )
            if context.build_device_access_list:
                all_devices = context.build_device_access_list(nodes, context.worker_ip)
            else:
                all_devices = _build_device_access_list_simple(nodes, context.worker_ip)
            # Filter by visible labels if available
            if visible_labels:
                devices = [d for d in all_devices if d.device_label in visible_labels]
            else:
                devices = all_devices

        # ── Create LDS session ──
        region = instance.worker_aws_region
        session_info = await context.lds.create_session(
            username=instance.name,
            first_name="Lablet",
            last_name="User",
            scheduled_date=datetime.now(timezone.utc).isoformat(),
            form_qualified_name=definition.form_qualified_name,
            region=region,
        )
        lds_session_id = session_info.session_id
        logger.info(f"LDS session {lds_session_id} created for session {instance.id}")

        if devices:
            await context.lds.set_devices(
                session_id=lds_session_id,
                part_num=1,
                devices=devices,
                region=region,
            )
            logger.info(f"Set {len(devices)} devices on LDS session {lds_session_id}")
        else:
            logger.warning(f"No devices to set on LDS session {lds_session_id} (visible_labels={visible_labels}, allocated_ports keys={list(allocated_ports.keys())})")

        # Get lablet launch URL
        launch_url = await context.lds.get_lablet_launch_url(
            session_id=lds_session_id,
            region=region,
        )

        # Create UserSession child entity via CPA
        user_session_data = await context.api.create_user_session(
            session_id=instance.id,
            lds_session_id=lds_session_id,
            lds_login_url=launch_url,
            cml_lab_id=cml_lab_id,
        )
        user_session_id = user_session_data.get("id", lds_session_id)

        return StepResult.completed(
            {
                "lds_session_id": lds_session_id,
                "user_session_id": user_session_id,
                "launch_url": launch_url,
                "device_count": len(devices),
            }
        )

    except LdsSpiError as e:
        return StepResult.failed(f"LDS provisioning failed: {e}")
    except Exception as e:
        return StepResult.failed(str(e))


@step_handler("mark_ready")
async def step_mark_ready(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Atomic transition to READY status.

    Calls ``mark_session_ready()`` with the resolved CML lab ID
    and user session ID.

    ADR-038 Task 1 parity: Cleans up shared tracking state
    (resolved_lab_ids, freshly_imported_sessions) after successful
    mark_ready — the lab ID is now persisted in CPA.
    """
    resolve_data = _get_step_result_data(progress, "lab_resolve")
    cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id from lab_resolve")

    # Get user_session_id from lds_provision (if it ran)
    lds_data = _get_step_result_data(progress, "lds_provision")
    user_session_id = (lds_data.get("user_session_id") if lds_data else None) or ""

    try:
        await context.api.mark_session_ready(
            session_id=instance.id,
            user_session_id=user_session_id,
            cml_lab_id=cml_lab_id,
        )

        # Clean up local lab ID tracking (now persisted in CPA)
        if context.resolved_lab_ids is not None:
            context.resolved_lab_ids.pop(instance.id, None)
        if context.freshly_imported_sessions is not None:
            context.freshly_imported_sessions.discard(instance.id)

        logger.info(f"✅ Session {instance.id} marked READY (pipeline complete)")
        return StepResult.completed(
            {
                "cml_lab_id": cml_lab_id,
                "user_session_id": user_session_id,
            }
        )
    except Exception as e:
        return StepResult.failed(str(e))
