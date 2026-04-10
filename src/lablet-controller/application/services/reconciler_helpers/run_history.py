"""Lab run history recording helper.

ADR-038 Task 3: Extracted from LabletReconciler._record_lab_run_completed().
"""

import logging
from datetime import datetime, timezone

from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.integration.clients import ControlPlaneApiClient

from application.services.reconciler_helpers.lab_record_helpers import find_lab_record_id

logger = logging.getLogger(__name__)


async def record_lab_run_completed(
    instance: LabletSessionReadModel,
    api: ControlPlaneApiClient,
    lab_run_started_at: dict[str, datetime],
) -> bool:
    """Record a completed lab run via CPA.

    Called during STOPPING phase. Creates a LabRunRecord documenting
    the start→stop execution cycle.

    Args:
        instance: The LabletSession whose run is ending.
        api: Control Plane API client.
        lab_run_started_at: Mutable tracking dict (session_id → start time).

    Returns:
        True if the run was recorded successfully, False otherwise.
    """
    if not instance.cml_lab_id or not instance.worker_id:
        return False

    try:
        lab_record_id = await find_lab_record_id(instance.cml_lab_id, instance.worker_id, api)
        if not lab_record_id:
            return False

        # Get run start time from tracking dict, or use timeslot_start as fallback
        started_at = lab_run_started_at.pop(instance.id, None)
        started_at_str = started_at.isoformat() if started_at else None
        stopped_at_str = datetime.now(timezone.utc).isoformat()

        await api.record_lab_run_completed(
            lab_record_id=lab_record_id,
            started_at=started_at_str,
            stopped_at=stopped_at_str,
            started_by="lablet-controller",
            stop_reason="timeslot_end",
            lablet_session_id=instance.id,
            final_state="stopped",
        )
        logger.info(f"📝 Recorded lab run for session {instance.id}")
        return True

    except Exception as e:
        logger.warning(f"Failed to record lab run for session {instance.id}: {e}")
        return False
