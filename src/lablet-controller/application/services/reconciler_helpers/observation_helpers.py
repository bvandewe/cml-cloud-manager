"""Resource observation helpers.

ADR-038 Task 3: Extracted from LabletReconciler._observe_and_report().
"""

import asyncio
import logging

from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.integration.clients import ControlPlaneApiClient

from application.services.resource_observer import ResourceObserver
from application.settings import Settings

logger = logging.getLogger(__name__)


async def observe_and_report(
    instance: LabletSessionReadModel,
    resource_observer: ResourceObserver | None,
    api: ControlPlaneApiClient,
    settings: Settings,
) -> None:
    """Observe live CML lab resources and report to CPA.

    Best-effort: failures are logged but do not block session lifecycle.
    AD-OLR-001: Observation at COLLECTING/STOPPING boundary.
    ADR-030: Resource & Port Observation — "Learn from Live"

    Args:
        instance: Session with a running lab to observe.
        resource_observer: Resource observer (may be None if not configured).
        api: Control Plane API client.
        settings: Application settings (for timeout and enabled flag).
    """
    if not settings.resource_observation_enabled:
        logger.debug(f"Resource observation disabled — skipping for session {instance.id}")
        return

    if not resource_observer:
        logger.debug(f"Resource observer not configured — skipping observation for session {instance.id}")
        return

    try:
        timeout = settings.resource_observation_timeout_seconds
        observation = await asyncio.wait_for(
            resource_observer.observe(
                host=instance.worker_ip,
                lab_id=instance.cml_lab_id,
                username=instance.worker_cml_username,
                password=instance.worker_cml_password,
            ),
            timeout=timeout,
        )
        if observation:
            await api.report_resource_observations(
                session_id=instance.id,
                observed_resources=observation.to_dict(),
                observed_ports=observation.observed_ports,
            )
            logger.info(
                f"Resource observation reported for session {instance.id}: "
                f"cpu={observation.total_cpu_cores}, mem={observation.total_memory_mb}MB, "
                f"nodes={observation.actual_node_count}, ports={len(observation.observed_ports)}"
            )
        else:
            logger.warning(f"No resource observation available for session {instance.id}")
    except TimeoutError:
        logger.warning(f"Resource observation timed out for session {instance.id} (timeout={settings.resource_observation_timeout_seconds}s)")
    except Exception as e:
        logger.warning(f"Resource observation failed for session {instance.id}: {e}")
