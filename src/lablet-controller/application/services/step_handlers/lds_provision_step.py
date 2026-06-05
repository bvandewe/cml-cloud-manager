"""LDS provision step handler — lds_provision.

ADR-038: Extracted from binding_steps.py (one step per file refactor).

Provisions LDS session with device mapping.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.reconciler_helpers.lds_helpers import build_device_access_from_allocated_ports
from application.services.step_handlers._helpers import get_step_result_data
from application.services.step_registry import StepResult, step_handler
from integration.services.lds_spi import DeviceAccessInfo, LdsSpiError

logger = logging.getLogger(__name__)


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
    resolve_data = get_step_result_data(progress, "lab_resolve")
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
        ports_data = get_step_result_data(progress, "ports_alloc")
        allocated_ports: dict[str, int] = {}
        if ports_data:
            allocated_ports = ports_data.get("allocated_ports", {})

        # ── Build filtered device list ──
        if allocated_ports:
            devices = build_device_access_from_allocated_ports(
                allocated_ports=allocated_ports,
                worker_ip=context.worker_ip,
                user_visible_labels=visible_labels,
                protocol_priority=context.lds_protocol_priority,
                port_preferences=context.lds_port_preferences,
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
