"""Download Lab YAML Command - retrieves lab topology in YAML format (ADR-017 BFF Pattern).

ADR-017: Lab download uses the BFF (Backend for Frontend) pattern:
1. Control-plane-api receives download request from UI
2. Control-plane-api proxies to lablet-controller's /labs/{host}/{lab_id}/download endpoint
3. Lablet-controller calls CML API and returns YAML
4. Control-plane-api returns YAML to UI

This is a read-only operation — no state change, immediate response.
"""

import logging
from dataclasses import dataclass

import httpx
from neuroglia.core.operation_result import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace

from application.settings import Settings
from domain.repositories.cml_worker_repository import CMLWorkerRepository

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DownloadLabCommand(Command[OperationResult[str]]):
    """Command to download a lab's topology as YAML.

    ADR-017: BFF pattern - control-plane-api proxies to lablet-controller.

    Attributes:
        worker_id: CMLWorker aggregate ID (resolved to host IP for the proxy call).
        lab_id: CML lab UUID.
    """

    worker_id: str
    lab_id: str


class DownloadLabCommandHandler(CommandHandler[DownloadLabCommand, OperationResult[str]]):
    """Handler for DownloadLabCommand — proxies lab download through lablet-controller.

    ADR-017 BFF: CPA → lablet-controller → CML API.
    """

    def __init__(
        self,
        worker_repository: CMLWorkerRepository,
        settings: Settings,
    ):
        """Initialize handler.

        Args:
            worker_repository: Repository for resolving worker host IP.
            settings: Application settings (lablet_controller_url, internal_api_key).
        """
        super().__init__()
        self._worker_repository = worker_repository
        self._settings = settings

    async def handle_async(self, request: DownloadLabCommand, cancellation_token=None) -> OperationResult[str]:
        """Download lab topology as YAML via lablet-controller BFF proxy.

        Flow:
        1. Resolve worker_id → worker host IP
        2. Call lablet-controller: GET /labs/{host}/{lab_id}/download
        3. Return YAML content
        """
        with tracer.start_as_current_span("download_lab_command") as span:
            span.set_attribute("worker.id", request.worker_id)
            span.set_attribute("lab.id", request.lab_id)
            span.set_attribute("adr", "ADR-017")
            span.set_attribute("pattern", "BFF-proxy")

            log.info("Downloading lab %s from worker %s via lablet-controller", request.lab_id, request.worker_id)

            # 1. Resolve worker to get CML host IP
            worker = await self._worker_repository.get_by_id_async(request.worker_id)
            if not worker:
                return self.not_found("Worker", f"Worker {request.worker_id} not found")

            if not worker.state.https_endpoint:
                return self.bad_request("Worker does not have HTTPS endpoint configured")

            endpoint = worker.get_effective_endpoint(self._settings.use_private_ip_for_monitoring)

            try:
                # 2. Proxy through lablet-controller
                url = f"{self._settings.lablet_controller_url}/labs/{endpoint}/{request.lab_id}/download"
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(
                        url,
                        headers={
                            "X-API-Key": self._settings.internal_api_key,
                            "Accept": "application/x-yaml",
                        },
                    )
                    response.raise_for_status()
                    yaml_content = response.text

                log.info("Successfully downloaded lab %s (%d bytes)", request.lab_id, len(yaml_content))
                return self.ok(yaml_content)

            except httpx.HTTPStatusError as e:
                error_msg = f"Lablet-controller returned {e.response.status_code} for lab download"
                log.error("%s: %s", error_msg, e.response.text[:200])
                if e.response.status_code == 404:
                    return self.not_found("Lab", f"Lab {request.lab_id} not found on worker")
                return self.internal_server_error(error_msg)
            except httpx.ConnectError:
                error_msg = "Cannot reach lablet-controller for lab download"
                log.error(error_msg)
                return self.service_unavailable(error_msg)
            except Exception as e:
                log.error("Failed to download lab %s: %s", request.lab_id, e)
                return self.internal_server_error(f"Failed to download lab: {str(e)}")
