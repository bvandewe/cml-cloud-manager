"""Worker details resolution and caching helpers.

ADR-038 Task 3: Extracted from LabletReconciler._enrich_with_worker_details(),
_get_cached_worker(), and _extract_host_from_worker().
"""

import logging

from lcm_core.domain.entities import LabletSessionReadModel
from lcm_core.integration.clients import ControlPlaneApiClient

from application.settings import Settings

logger = logging.getLogger(__name__)


async def enrich_with_worker_details(
    session: LabletSessionReadModel,
    api: ControlPlaneApiClient,
    settings: Settings,
    worker_cache: dict[str, dict],
) -> None:
    """Enrich a session read model with worker connection details.

    The CPA DTO only includes worker_id.  Connection details (IP, credentials)
    are resolved from the CMLWorker aggregate via CPA and cached locally.

    Args:
        session: The session to enrich (mutated in-place).
        api: Control Plane API client.
        settings: Application settings (for credential resolution).
        worker_cache: Mutable cache dict (caller owns lifetime).
    """
    if not session.worker_id:
        return

    worker = await get_cached_worker(session.worker_id, api, worker_cache)
    if not worker:
        return

    # Resolve host IP (private or public based on settings)
    session.worker_ip = extract_host_from_worker(worker, settings)

    # Resolve CML credentials: per-worker or global fallback
    session.worker_cml_username = settings.cml_worker_api_username
    session.worker_cml_password = settings.cml_worker_api_password

    # Resolve AWS region
    session.worker_aws_region = worker.get("aws_region")


async def get_cached_worker(
    worker_id: str,
    api: ControlPlaneApiClient,
    worker_cache: dict[str, dict],
) -> dict | None:
    """Get worker data from cache or CPA.

    Args:
        worker_id: CML worker ID.
        api: Control Plane API client.
        worker_cache: Mutable cache dict (caller owns lifetime).

    Returns:
        Worker data dictionary, or None if unavailable.
    """
    if worker_id in worker_cache:
        return worker_cache[worker_id]

    try:
        worker = await api.get_worker(worker_id)
        if not worker:
            logger.warning(f"Worker {worker_id} not found via CPA")
            return None

        worker_cache[worker_id] = worker
        return worker

    except Exception as e:
        logger.error(f"Failed to resolve worker {worker_id}: {e}")
        return None


def extract_host_from_worker(worker: dict, settings: Settings) -> str | None:
    """Extract host address from worker data.

    Args:
        worker: Worker data from Control Plane API.
        settings: Application settings (for IP preference).

    Returns:
        Host address string, or None if unavailable.
    """
    if settings.use_private_ip_for_monitoring:
        host = worker.get("private_ip") or worker.get("public_ip")
    else:
        host = worker.get("public_ip") or worker.get("private_ip")

    # Fallback to https_endpoint
    if not host:
        https_endpoint = worker.get("https_endpoint", "")
        if https_endpoint:
            host = https_endpoint.replace("https://", "").split(":")[0]

    return host or None
