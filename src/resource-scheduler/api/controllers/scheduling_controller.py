"""Scheduling Controller for placement preview (dry-run).

Provides the dry-run preview endpoint that runs the real PlacementEngine
algorithm without executing the placement decision.

AD-SCHED-001: Architectural approach — expose PlacementEngine.schedule_preview()
via REST endpoint for read-only placement analysis.

AD-SCHED-002: UX decisions — all authenticated users can call preview
(read-only operation, no admin restriction).
"""

import json
import logging
from dataclasses import asdict
from typing import Any

from application.services.placement_engine import PlacementEngine
from fastapi import APIRouter, Depends, HTTPException
from lcm_core.integration.clients import ControlPlaneApiClient, EtcdClient
from pydantic import BaseModel, Field

from api.dependencies import get_current_user

logger = logging.getLogger(__name__)


class PlacementPreviewRequest(BaseModel):
    """Request body for placement preview (dry-run).

    Attributes:
        definition_id: ID of the LabletDefinition to preview scheduling for.
        timeslot_start: Optional start time (ISO 8601) for create-session preview.
        timeslot_end: Optional end time (ISO 8601) for create-session preview.
    """

    definition_id: str = Field(..., description="LabletDefinition ID to preview scheduling for")
    timeslot_start: str | None = Field(None, description="Optional timeslot start (ISO 8601)")
    timeslot_end: str | None = Field(None, description="Optional timeslot end (ISO 8601)")


class SchedulingController:
    """Scheduling controller for dry-run placement preview.

    Provides endpoints for:
    - POST /scheduling/preview — Dry-run placement preview (all authenticated users)
    """

    def __init__(
        self,
        placement_engine: PlacementEngine,
        api_client: ControlPlaneApiClient,
        etcd_client: EtcdClient,
    ):
        """Initialize scheduling controller.

        Args:
            placement_engine: PlacementEngine singleton for placement algorithm.
            api_client: ControlPlaneApiClient for fetching workers/definitions.
            etcd_client: EtcdClient for real-time capacity data.
        """
        self._placement_engine = placement_engine
        self._api_client = api_client
        self._etcd_client = etcd_client
        self.router = APIRouter(prefix="/scheduling", tags=["Scheduling"])
        self._register_routes()

    async def _fetch_etcd_capacities(self) -> dict[str, dict[str, Any]]:
        """Fetch all worker capacity data from etcd.

        Replicates the same logic as SchedulerHostedService._refresh_etcd_capacities
        for on-demand use in the preview endpoint.

        Returns:
            Dict of worker_id → capacity data, empty dict if etcd unavailable.
        """
        try:
            raw_data = await self._etcd_client.get_prefix("/workers/")
            capacities: dict[str, dict[str, Any]] = {}

            for key, value in raw_data.items():
                if not key.endswith("/capacity"):
                    continue
                try:
                    data = json.loads(value)
                    worker_id = data.get("worker_id", "")
                    if worker_id:
                        capacities[worker_id] = data
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in etcd key {key}")

            return capacities
        except Exception as e:
            logger.warning(f"Failed to fetch etcd capacities: {e}")
            return {}

    def _register_routes(self) -> None:
        """Register scheduling routes."""

        @self.router.post(
            "/preview",
            summary="Placement Preview (Dry Run)",
            description=(
                "Run the real PlacementEngine algorithm without executing the decision. "
                "Returns candidate scores, per-worker rejection reasons, and estimated "
                "resource utilization after placement. Available to all authenticated users."
            ),
        )
        async def preview_placement(
            request: PlacementPreviewRequest,
            user: dict = Depends(get_current_user),
        ) -> dict[str, Any]:
            """Dry-run placement preview.

            Runs PlacementEngine.schedule_preview() with current worker state
            and returns an enriched result without side effects.

            Args:
                request: Preview request with definition_id and optional timeslot.
                user: Authenticated user (any role — read-only operation).

            Returns:
                Enriched placement analysis with decision, candidates, rejections,
                and utilization forecast.

            Raises:
                HTTPException: 404 if definition not found, 502 if upstream unavailable.
            """
            username = user.get("username", "unknown")
            logger.info(f"Placement preview requested by {username} for definition {request.definition_id}")

            # Fetch definition from Control Plane API
            try:
                definition = await self._api_client.get_lablet_definition(request.definition_id)
            except Exception as e:
                logger.error(f"Failed to fetch definition {request.definition_id}: {e}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to fetch definition from Control Plane API: {e}",
                )

            if not definition:
                raise HTTPException(
                    status_code=404,
                    detail=f"Definition '{request.definition_id}' not found",
                )

            # Fetch active workers
            try:
                workers = await self._api_client.get_workers(status="RUNNING")
            except Exception as e:
                logger.error(f"Failed to fetch workers: {e}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to fetch workers from Control Plane API: {e}",
                )

            # Fetch real-time etcd capacities (best-effort)
            etcd_capacities = await self._fetch_etcd_capacities()

            # Fetch templates (best-effort, for scale-up recommendation)
            templates: list[dict[str, Any]] | None = None
            try:
                templates = await self._api_client.get_worker_templates()
            except Exception as e:
                logger.warning(f"Failed to fetch templates: {e}")

            # Build synthetic instance stub for the preview
            instance_stub: dict[str, Any] = {
                "id": "preview-stub",
                "definition_id": request.definition_id,
                "status": "PENDING_SCHEDULE",
            }
            if request.timeslot_start:
                instance_stub["timeslot_start"] = request.timeslot_start
            if request.timeslot_end:
                instance_stub["timeslot_end"] = request.timeslot_end

            # Run the placement preview (pure, no side effects)
            preview_result = self._placement_engine.schedule_preview(
                instance=instance_stub,
                definition=definition,
                workers=workers or [],
                etcd_capacities=etcd_capacities or None,
                templates=templates,
            )

            logger.info(
                f"Placement preview for {request.definition_id}: action={preview_result.decision.action}, candidates={len(preview_result.candidates)}, rejections={len(preview_result.rejections)}"
            )

            # Serialize dataclass tree to dict for JSON response
            result = asdict(preview_result)

            # Add metadata
            result["requested_by"] = username
            result["preview"] = True

            return result
