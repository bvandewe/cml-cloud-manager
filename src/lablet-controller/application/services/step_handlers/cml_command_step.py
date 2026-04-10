"""CML command step handler — execute_command_on_cml_node.

ADR-038 Phase 4: Parameterized step handler for arbitrary CML node
operations. This handler is the key enabler for divergent pipeline
definitions — different lab definitions can inject custom CML commands
without writing new step handler code.

Supported actions (via ``params.action``):
- ``transfer_file`` — Upload a file to a CML node filesystem
- ``execute_command`` — Run a CLI command on a CML node console
- ``shut_interface`` — Admin-down a node interface
- ``no_shut_interface`` — Admin-up a node interface
- ``extract_configs`` — Extract running config from a node

YAML usage::

    - name: transfer_student_archive
      handler: execute_command_on_cml_node
      params:
        action: transfer_file
        target_node: ubuntu-desktop
        source_url: "https://..."
        target_path: /tmp/lab-files.tar.gz
      timeout_seconds: 120
"""

from __future__ import annotations

import logging
from typing import Any

from lcm_core.domain.entities import LabletSessionReadModel

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import StepResult, step_handler

logger = logging.getLogger(__name__)


def _find_node_id_by_label(nodes: list, target_label: str) -> str | None:
    """Find a CML node ID by its label.

    Args:
        nodes: List of NodeInfo from CML Labs SPI.
        target_label: Node label to match (case-insensitive).

    Returns:
        Node ID string, or None if not found.
    """
    for node in nodes:
        if node.label.lower() == target_label.lower():
            return node.id
    return None


@step_handler("execute_command_on_cml_node")
async def step_execute_command_on_cml_node(
    instance: LabletSessionReadModel,
    progress: dict[str, Any],
    context: PipelineContext,
    params: dict[str, Any] | None = None,
) -> StepResult:
    """Execute a parameterized CML node command.

    This handler dispatches to sub-actions based on ``params["action"]``.
    Each action maps to a specific CML Labs SPI operation.

    Required params:
        action: One of transfer_file, execute_command, shut_interface,
                no_shut_interface, extract_configs
        target_node: CML node label (matched case-insensitively)

    Action-specific params vary (see individual action handlers).
    """
    if not params:
        return StepResult.failed("No params provided for execute_command_on_cml_node")

    action = params.get("action")
    target_node_label = params.get("target_node")

    if not action:
        return StepResult.failed("Missing required param: action")
    if not target_node_label:
        return StepResult.failed("Missing required param: target_node")

    cml_lab_id = instance.cml_lab_id
    if not cml_lab_id:
        # Try to get from prior step results
        lab_resolve_data = progress.get("lab_resolve", {})
        if isinstance(lab_resolve_data, dict):
            cml_lab_id = lab_resolve_data.get("result_data", {}).get("cml_lab_id")
    if not cml_lab_id:
        return StepResult.failed("No cml_lab_id available")

    # Resolve target node ID from label
    try:
        nodes = await context.cml.get_lab_nodes(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
    except Exception as e:
        return StepResult.failed(f"Failed to get lab nodes: {e}")

    node_id = _find_node_id_by_label(nodes, target_node_label)
    if not node_id:
        return StepResult.failed(f"Node '{target_node_label}' not found in lab {cml_lab_id}")

    # Dispatch to action handler
    action_handlers = {
        "transfer_file": _action_transfer_file,
        "execute_command": _action_execute_command,
        "shut_interface": _action_shut_interface,
        "no_shut_interface": _action_no_shut_interface,
        "extract_configs": _action_extract_configs,
    }

    handler = action_handlers.get(action)
    if not handler:
        return StepResult.failed(f"Unknown action: {action}. Supported: {', '.join(action_handlers.keys())}")

    return await handler(
        context=context,
        cml_lab_id=cml_lab_id,
        node_id=node_id,
        node_label=target_node_label,
        params=params,
    )


# ── Action Implementations ──────────────────────────


async def _action_transfer_file(
    context: PipelineContext,
    cml_lab_id: str,
    node_id: str,
    node_label: str,
    params: dict[str, Any],
) -> StepResult:
    """Transfer a file to a CML node.

    Params:
        source_url: URL or local path of the file to transfer
        target_path: Destination path on the CML node
    """
    source_url = params.get("source_url", "")
    target_path = params.get("target_path", "")

    if not source_url or not target_path:
        return StepResult.failed("transfer_file requires source_url and target_path params")

    try:
        # CML Labs SPI: node file upload endpoint
        await context.cml.upload_file_to_node(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            node_id=node_id,
            source_url=source_url,
            target_path=target_path,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
        logger.info(f"Transferred {source_url} → {node_label}:{target_path} in lab {cml_lab_id}")
        return StepResult.completed(
            {
                "action": "transfer_file",
                "node": node_label,
                "target_path": target_path,
            }
        )
    except Exception as e:
        return StepResult.failed(f"File transfer to {node_label} failed: {e}")


async def _action_execute_command(
    context: PipelineContext,
    cml_lab_id: str,
    node_id: str,
    node_label: str,
    params: dict[str, Any],
) -> StepResult:
    """Execute a CLI command on a CML node console.

    Params:
        command: The command string to execute
    """
    command = params.get("command", "")
    if not command:
        return StepResult.failed("execute_command requires command param")

    try:
        result = await context.cml.execute_node_command(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            node_id=node_id,
            command=command,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
        logger.info(f"Executed command on {node_label} in lab {cml_lab_id}: {command}")
        return StepResult.completed(
            {
                "action": "execute_command",
                "node": node_label,
                "command": command,
                "output": result if isinstance(result, str) else str(result),
            }
        )
    except Exception as e:
        return StepResult.failed(f"Command execution on {node_label} failed: {e}")


async def _action_shut_interface(
    context: PipelineContext,
    cml_lab_id: str,
    node_id: str,
    node_label: str,
    params: dict[str, Any],
) -> StepResult:
    """Admin-shutdown a node interface (fault injection).

    Params:
        interface: Interface name (e.g. GigabitEthernet0/1)
    """
    interface = params.get("interface", "")
    if not interface:
        return StepResult.failed("shut_interface requires interface param")

    try:
        await context.cml.set_interface_state(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            node_id=node_id,
            interface_name=interface,
            state="down",
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
        logger.info(f"Shut interface {interface} on {node_label} in lab {cml_lab_id}")
        return StepResult.completed(
            {
                "action": "shut_interface",
                "node": node_label,
                "interface": interface,
                "state": "down",
            }
        )
    except Exception as e:
        return StepResult.failed(f"Interface shutdown on {node_label}.{interface} failed: {e}")


async def _action_no_shut_interface(
    context: PipelineContext,
    cml_lab_id: str,
    node_id: str,
    node_label: str,
    params: dict[str, Any],
) -> StepResult:
    """Admin-enable a node interface.

    Params:
        interface: Interface name (e.g. GigabitEthernet0/1)
    """
    interface = params.get("interface", "")
    if not interface:
        return StepResult.failed("no_shut_interface requires interface param")

    try:
        await context.cml.set_interface_state(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            node_id=node_id,
            interface_name=interface,
            state="up",
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
        logger.info(f"No-shut interface {interface} on {node_label} in lab {cml_lab_id}")
        return StepResult.completed(
            {
                "action": "no_shut_interface",
                "node": node_label,
                "interface": interface,
                "state": "up",
            }
        )
    except Exception as e:
        return StepResult.failed(f"Interface enable on {node_label}.{interface} failed: {e}")


async def _action_extract_configs(
    context: PipelineContext,
    cml_lab_id: str,
    node_id: str,
    node_label: str,
    params: dict[str, Any],
) -> StepResult:
    """Extract running configuration from a CML node.

    Params:
        config_type: Optional — "running" (default) or "startup"
    """
    config_type = params.get("config_type", "running")

    try:
        config = await context.cml.get_node_config(
            host=context.worker_ip,
            lab_id=cml_lab_id,
            node_id=node_id,
            config_type=config_type,
            username=context.worker_cml_username,
            password=context.worker_cml_password,
        )
        logger.info(f"Extracted {config_type} config from {node_label} in lab {cml_lab_id}")
        return StepResult.completed(
            {
                "action": "extract_configs",
                "node": node_label,
                "config_type": config_type,
                "config_length": len(config) if config else 0,
                "config": config,
            }
        )
    except Exception as e:
        return StepResult.failed(f"Config extraction from {node_label} failed: {e}")
