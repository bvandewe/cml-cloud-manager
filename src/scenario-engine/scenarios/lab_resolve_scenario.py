"""lab_resolve scenario — Resolve a CML lab (import or reuse).

Resolves a CML lab topology for a pod session. Either reuses an existing
lab (if lab_reuse_enabled) or imports a fresh one from topology YAML.

Input:
    topology_yaml: str — CML topology YAML content
    worker_ip: str — Target CML worker IP
    worker_cml_username: str — CML API username
    worker_cml_password: str — CML API password
    existing_lab_id: str | None — Previously resolved lab ID (reuse case)
    lab_reuse_enabled: bool — Whether to attempt reuse (default: False)

Output (completed):
    lab_id: str — The resolved CML lab ID
    lab_title: str | None — Lab title from CML
    freshly_imported: bool — Whether a fresh import occurred
"""

from __future__ import annotations

import logging
from typing import Any

from application.services.scenario_context import ScenarioContext
from application.services.scenario_registry import ScenarioResult, scenario

logger = logging.getLogger(__name__)


@scenario(
    name="lab_resolve",
    version="v1",
    description="Resolve a CML lab topology — import fresh or reuse existing",
)
class LabResolveScenario:
    """Resolve a CML lab for a session.

    Uses the 'cml' adapter from context.adapters to interact with the CML API.
    """

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topology_yaml": {"type": "string", "description": "CML topology YAML content"},
            "worker_ip": {"type": "string"},
            "worker_cml_username": {"type": "string"},
            "worker_cml_password": {"type": "string"},
            "existing_lab_id": {"type": ["string", "null"]},
            "lab_reuse_enabled": {"type": "boolean", "default": False},
        },
        "required": ["topology_yaml", "worker_ip", "worker_cml_username", "worker_cml_password"],
    }

    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "lab_id": {"type": "string"},
            "lab_title": {"type": ["string", "null"]},
            "freshly_imported": {"type": "boolean"},
        },
        "required": ["lab_id", "freshly_imported"],
    }

    async def execute(self, input_data: dict[str, Any], context: ScenarioContext) -> ScenarioResult:
        """Execute lab resolution.

        Resolution chain:
        1. If existing_lab_id provided and reuse enabled → verify it exists, reuse
        2. Otherwise → import topology_yaml as a new lab
        3. Return lab_id, lab_title, and freshly_imported flag
        """
        topology_yaml = input_data.get("topology_yaml")
        worker_ip = input_data.get("worker_ip")
        username = input_data.get("worker_cml_username")
        password = input_data.get("worker_cml_password")
        existing_lab_id = input_data.get("existing_lab_id")
        lab_reuse_enabled = input_data.get("lab_reuse_enabled", False)

        if not topology_yaml:
            return ScenarioResult.failed("topology_yaml is required")
        if not worker_ip:
            return ScenarioResult.failed("worker_ip is required")

        # Get CML adapter
        cml = context.adapters.require("cml")

        # Attempt reuse if enabled and existing lab ID provided
        if lab_reuse_enabled and existing_lab_id:
            context.logger.info("Attempting lab reuse for %s on %s", existing_lab_id, worker_ip)

            if context.cancellation_event.is_set():
                return ScenarioResult.cancelled()

            try:
                lab_state = await cml.get_lab_state(
                    host=worker_ip,
                    lab_id=existing_lab_id,
                    username=username,
                    password=password,
                )
                if lab_state is not None:
                    # Lab exists — reuse it
                    lab_title = await self._get_lab_title(cml, worker_ip, existing_lab_id, username, password)
                    context.logger.info("♻️ Reusing existing lab %s", existing_lab_id)
                    await context.report_progress(100, f"Reusing lab {existing_lab_id}")
                    return ScenarioResult.completed(
                        output_data={
                            "lab_id": existing_lab_id,
                            "lab_title": lab_title,
                            "freshly_imported": False,
                        }
                    )
                else:
                    context.logger.info("Existing lab %s not found — importing fresh", existing_lab_id)
            except Exception as e:
                context.logger.warning("Reuse check failed for %s: %s — importing fresh", existing_lab_id, e)

        # Import fresh lab
        if context.cancellation_event.is_set():
            return ScenarioResult.cancelled()

        await context.report_progress(30, "Importing lab topology...")

        try:
            lab_id = await cml.import_lab(
                host=worker_ip,
                topology_yaml=topology_yaml,
                username=username,
                password=password,
            )
        except Exception as e:
            return ScenarioResult.failed(f"Lab import failed: {e}")

        if not lab_id:
            return ScenarioResult.failed("Lab import returned empty lab_id")

        # Get lab title
        lab_title = await self._get_lab_title(cml, worker_ip, lab_id, username, password)

        context.logger.info("📦 Imported fresh lab %s", lab_id)
        await context.report_progress(100, f"Lab {lab_id} imported")

        return ScenarioResult.completed(
            output_data={
                "lab_id": lab_id,
                "lab_title": lab_title,
                "freshly_imported": True,
            }
        )

    async def _get_lab_title(self, cml: Any, host: str, lab_id: str, username: str, password: str) -> str | None:
        """Fetch lab title (best-effort)."""
        try:
            lab_info = await cml.get_lab(host=host, lab_id=lab_id, username=username, password=password)
            return lab_info.title if lab_info else None
        except Exception:
            return None
