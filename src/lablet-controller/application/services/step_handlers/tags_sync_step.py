"""Tags sync step handler — tags_sync.

Writes allocated port numbers to CML node tags after port allocation.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_handlers._helpers import get_step_result_data
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


@step_handler("tags_sync")
async def step_tags_sync(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Write allocated port numbers to CML node tags (§3.7, AD-TAGS-001).

    After ports_alloc, write protocol:port tags to each CML node via
    PATCH /api/v0/labs/{lab_id}/nodes/{node_id}.
    Tags persist across start/stop/wipe — they are topology-level metadata.
    """
    ports_data = get_step_result_data(progress, "ports_alloc")
    if not ports_data:
        return StepResult.skipped("No ports_alloc data")

    allocated_ports = ports_data.get("allocated_ports", {})
    if not allocated_ports:
        return StepResult.skipped("No allocated ports")

    resolve_data = get_step_result_data(progress, "lab_resolve")
    cml_lab_id = resolve_data.get("cml_lab_id") if resolve_data else None
    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id from lab_resolve")

    # Group allocated ports by node label.
    # Port names follow convention: "{node_label}_{protocol}"
    node_tags: dict[str, list[str]] = {}
    for port_name, port_number in allocated_ports.items():
        parts = port_name.rsplit("_", 1)
        if len(parts) != 2:
            continue
        node_label, protocol = parts
        tag = f"{protocol}:{port_number}"
        node_tags.setdefault(node_label, []).append(tag)

    # Get CML lab nodes to find node IDs
    try:
        nodes = await context.cml.get_lab_nodes(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
    except Exception as e:
        return StepResult.failed(f"Failed to get lab nodes: {e}")

    # Write tags to each matching node via PATCH
    synced_nodes = []
    for node in nodes:
        node_label = node.label
        safe_label = re.sub(r"[^a-zA-Z0-9_-]", "_", node_label)
        if safe_label in node_tags:
            try:
                await context.cml.patch_node_tags(
                    host=context.worker_ip,
                    lab_id=cml_lab_id,
                    node_id=node.id,
                    tags=node_tags[safe_label],
                    username=context.worker_cml_username,
                    password=context.worker_cml_password,
                )
                synced_nodes.append(node_label)
            except Exception as e:
                # AD-TAGS-001: Tag sync failures are non-fatal warnings
                logger.warning(f"Failed to sync tags for node {node_label} in lab {cml_lab_id}: {e}")

    return StepResult.completed(
        {
            "synced_nodes": synced_nodes,
            "tag_count": sum(len(t) for t in node_tags.values()),
        }
    )
