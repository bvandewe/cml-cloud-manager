"""lab_start scenario — Start a CML lab and poll for convergence.

Starts the CML lab and polls until all nodes are STARTED + converged.
Handles fast-path (already converged), start initiation, and polling.

Input:
    lab_id: str — CML lab ID to start
    worker_ip: str — Target CML worker IP
    worker_cml_username: str — CML API username
    worker_cml_password: str — CML API password
    poll_interval: int — Seconds between state polls (default: 20)

Output (completed):
    lab_id: str — The CML lab ID
    lab_state: str — Final lab state ("CONVERGED")
    poll_count: int — Number of polls required
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from application.services.scenario_context import ScenarioContext
from application.services.scenario_registry import ScenarioResult, scenario

logger = logging.getLogger(__name__)

# Lab state constants (mirrors CML API states)
_STATE_STARTED = "STARTED"
_STATE_STOPPED = "STOPPED"
_STATE_DEFINED_ON_CORE = "DEFINED_ON_CORE"
_STATE_QUEUED = "QUEUED"


@scenario(
    name="lab_start",
    version="v1",
    description="Start a CML lab and poll until all nodes converge",
)
class LabStartScenario:
    """Start a CML lab and wait for convergence.

    Uses the 'cml' adapter from context.adapters to interact with the CML API.
    Timeout is enforced by the JobExecutionService (asyncio.wait_for), so the
    polling loop is safe from hanging.
    """

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "lab_id": {"type": "string", "description": "CML lab ID to start"},
            "worker_ip": {"type": "string"},
            "worker_cml_username": {"type": "string"},
            "worker_cml_password": {"type": "string"},
            "poll_interval": {"type": "integer", "default": 20, "description": "Seconds between polls"},
        },
        "required": ["lab_id", "worker_ip", "worker_cml_username", "worker_cml_password"],
    }

    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "lab_id": {"type": "string"},
            "lab_state": {"type": "string"},
            "poll_count": {"type": "integer"},
        },
        "required": ["lab_id", "lab_state"],
    }

    async def execute(self, input_data: dict[str, Any], context: ScenarioContext) -> ScenarioResult:
        """Execute lab start and convergence polling.

        Flow:
        1. Get current lab state
        2. If already STARTED + converged → fast-path return
        3. If STOPPED/DEFINED_ON_CORE → initiate start
        4. Poll until STARTED + converged (bounded by executor timeout)
        """
        lab_id = input_data.get("lab_id")
        worker_ip = input_data.get("worker_ip")
        username = input_data.get("worker_cml_username")
        password = input_data.get("worker_cml_password")
        poll_interval = input_data.get("poll_interval", 20)

        if not lab_id:
            return ScenarioResult.failed("lab_id is required")
        if not worker_ip:
            return ScenarioResult.failed("worker_ip is required")

        cml = context.adapters.require("cml")

        # Get initial lab state
        try:
            lab_state = await cml.get_lab_state(
                host=worker_ip,
                lab_id=lab_id,
                username=username,
                password=password,
            )
        except Exception as e:
            return ScenarioResult.failed(f"Failed to get lab state: {e}")

        # Ghost lab check
        if lab_state is None:
            context.logger.error("👻 Lab %s not found on worker %s", lab_id, worker_ip)
            return ScenarioResult.failed(f"Lab {lab_id} not found on worker (ghost lab)")

        # Fast-path: already STARTED + converged
        if lab_state == _STATE_STARTED:
            converged = await self._check_convergence(cml, worker_ip, lab_id, username, password, context)
            if converged:
                context.logger.info("Lab %s already STARTED and converged", lab_id)
                await context.report_progress(100, "Lab already converged")
                return ScenarioResult.completed(output_data={"lab_id": lab_id, "lab_state": "CONVERGED", "poll_count": 0})

        # Start if needed
        if lab_state in (_STATE_STOPPED, _STATE_DEFINED_ON_CORE):
            if context.cancellation_event.is_set():
                return ScenarioResult.cancelled()

            try:
                await cml.start_lab(
                    host=worker_ip,
                    lab_id=lab_id,
                    username=username,
                    password=password,
                )
                context.logger.info("Lab %s start initiated", lab_id)
                await context.report_progress(10, "Lab start initiated")
            except Exception as e:
                return ScenarioResult.failed(f"Failed to start lab: {e}")

        # Polling loop (bounded by executor's asyncio.wait_for timeout)
        poll_count = 0
        while True:
            if context.cancellation_event.is_set():
                return ScenarioResult.cancelled()

            await asyncio.sleep(poll_interval)
            poll_count += 1

            try:
                lab_state = await cml.get_lab_state(
                    host=worker_ip,
                    lab_id=lab_id,
                    username=username,
                    password=password,
                )
            except Exception as e:
                context.logger.warning("Lab %s state poll #%d failed: %s", lab_id, poll_count, e)
                continue

            if lab_state == _STATE_QUEUED:
                context.logger.debug("Lab %s still QUEUED (poll #%d)", lab_id, poll_count)
                await context.report_progress(20, f"Lab queued (poll #{poll_count})")
                continue

            if lab_state != _STATE_STARTED:
                return ScenarioResult.failed(f"Lab entered unexpected state '{lab_state}' while waiting for convergence")

            # Check convergence
            converged = await self._check_convergence(cml, worker_ip, lab_id, username, password, context)
            if converged:
                context.logger.info("Lab %s converged after %d polls", lab_id, poll_count)
                await context.report_progress(100, f"Lab converged after {poll_count} polls")
                return ScenarioResult.completed(output_data={"lab_id": lab_id, "lab_state": "CONVERGED", "poll_count": poll_count})

            # Progress estimation (cap at 90%)
            progress_pct = min(20 + poll_count * 10, 90)
            await context.report_progress(progress_pct, f"Waiting for convergence (poll #{poll_count})")

    async def _check_convergence(
        self,
        cml: Any,
        host: str,
        lab_id: str,
        username: str,
        password: str,
        context: ScenarioContext,
    ) -> bool:
        """Check if all lab nodes are converged."""
        try:
            return await cml.check_if_converged(
                host=host,
                lab_id=lab_id,
                username=username,
                password=password,
            )
        except Exception as e:
            context.logger.warning("Convergence check failed for lab %s: %s", lab_id, e)
            return False
