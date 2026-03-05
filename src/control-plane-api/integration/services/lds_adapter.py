"""LDS (Lab Delivery System) Adapter for Control Plane API.

Phase 12 (P12-8): Run-scoped LDS session operations via BFF pattern.

The CPA does not talk to LDS directly — it delegates to the lablet-controller's
LDS SPI client via internal HTTP calls.  This adapter provides a clean interface
for the CQRS command handlers.

If ``LDS_DIRECT_MODE`` is enabled (env LDS_DIRECT_MODE=true), the adapter will
call LDS Reservations API v3 directly using httpx, following the same contract
as the lablet-controller's ``LdsSpiClient``.

Architecture ref: §8.8 (LDS Session API via LabletRecordRun).
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from neuroglia.dependency_injection.service_collection import ServiceCollection

log = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class LdsProvisionResult:
    """Result of provisioning an LDS session.

    Returned by ``provision_session`` — contains everything needed to update
    the LabletRecordRun and render the LDS IFRAME.
    """

    session_id: str
    login_url: str
    status: str = "provisioned"


@dataclass
class LdsSessionInfo:
    """Current LDS session status information."""

    session_id: str
    status: str
    login_url: str = ""
    session_parts: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Error Types
# =============================================================================


class LdsAdapterError(Exception):
    """Base exception for LDS adapter errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LdsSessionNotFoundError(LdsAdapterError):
    """Raised when an LDS session is not found."""

    pass


class LdsProvisionError(LdsAdapterError):
    """Raised when LDS session provisioning fails."""

    pass


# =============================================================================
# LDS Adapter
# =============================================================================


class LdsAdapter:
    """LDS operations adapter for the Control Plane API.

    Direct mode: Calls LDS Reservations API v3 directly (same contract as
    lablet-controller's LdsSpiClient).

    Provides run-scoped operations:
    - ``provision_session`` — Create LDS session + set devices + get launch URL
    - ``get_session_status`` — Query current session state
    - ``start_session`` — Activate a provisioned session
    - ``pause_session`` — Pause an active session (freeze timer)
    - ``resume_session`` — Resume a paused session
    - ``end_session`` — End/archive a session
    """

    def __init__(
        self,
        lds_base_url: str = "",
        lds_username: str = "",
        lds_password: str = "",
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ):
        """Initialize the LDS adapter.

        Args:
            lds_base_url: Base URL of the LDS Reservations API (e.g., https://lds.example.com).
            lds_username: HTTP Basic Auth username for LDS API.
            lds_password: HTTP Basic Auth password for LDS API.
            verify_ssl: Whether to verify SSL certificates.
            timeout: HTTP request timeout in seconds.
        """
        self._base_url = lds_base_url.rstrip("/")
        self._username = lds_username
        self._password = lds_password
        self._verify_ssl = verify_ssl
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Return True if LDS connection is configured."""
        return bool(self._base_url)

    def _get_auth(self) -> httpx.BasicAuth:
        """Create Basic Auth credentials."""
        return httpx.BasicAuth(username=self._username, password=self._password)

    # =========================================================================
    # Session Lifecycle
    # =========================================================================

    async def provision_session(
        self,
        username: str,
        first_name: str,
        last_name: str,
        form_qualified_name: str,
        allocated_ports: dict[str, Any],
        scheduled_date: str = "",
        rack_group: str = "LCM",
        rack_number: int = 1,
    ) -> LdsProvisionResult:
        """Provision an LDS session: create → set devices → get launch URL.

        This is the main entry point for Phase 12. Orchestrates the
        three-step LDS provisioning flow:

        1. ``POST /reservations/v3/lab_session`` — Create session with content part
        2. ``PUT /reservations/v3/lab_session/{id}/part/1/devices`` — Set device access info
        3. ``GET /reservations/v3/lab_session/{id}/lablet_launch_url`` — Get login URL

        Args:
            username: Candidate identifier (auth_id).
            first_name: Candidate first name.
            last_name: Candidate last name.
            form_qualified_name: FQN of lab content in LDS.
            allocated_ports: Frozen port allocations from LabletRecordRun.
                Format: {node_label: {protocol: {host, port, protocol}}}
            scheduled_date: ISO date string for the session.
            rack_group: Rack group identifier.
            rack_number: Rack number within group.

        Returns:
            LdsProvisionResult with session_id and login_url.

        Raises:
            LdsProvisionError: If any step of the provisioning flow fails.
        """
        if not self.is_configured:
            raise LdsProvisionError("LDS adapter not configured (no base URL)")

        try:
            # Step 1: Create session
            session_id = await self._create_session(
                username=username,
                first_name=first_name,
                last_name=last_name,
                form_qualified_name=form_qualified_name,
                scheduled_date=scheduled_date,
                rack_group=rack_group,
                rack_number=rack_number,
            )

            # Step 2: Set devices from allocated ports
            devices = self._ports_to_devices(allocated_ports)
            if devices:
                await self._set_devices(session_id, part_num=1, devices=devices)

            # Step 3: Get launch URL
            login_url = await self._get_launch_url(session_id)

            log.info("LDS session provisioned: session_id=%s, devices=%d", session_id, len(devices))

            return LdsProvisionResult(
                session_id=session_id,
                login_url=login_url,
                status="provisioned",
            )

        except LdsAdapterError:
            raise
        except Exception as e:
            raise LdsProvisionError(f"LDS provisioning failed: {e}") from e

    async def get_session_status(self, session_id: str) -> LdsSessionInfo:
        """Get current LDS session status.

        Maps to: GET /reservations/v3/lab_session/{id}

        Args:
            session_id: LDS session UUID.

        Returns:
            LdsSessionInfo with current status.

        Raises:
            LdsSessionNotFoundError: If session not found.
            LdsAdapterError: If request fails.
        """
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=self._timeout) as client:
            url = f"{self._base_url}/reservations/v3/lab_session/{session_id}"
            try:
                response = await client.get(url, auth=self._get_auth())
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise LdsSessionNotFoundError(f"LDS session {session_id} not found", status_code=404) from e
                raise LdsAdapterError(f"Failed to get session status: {e.response.status_code}", status_code=e.response.status_code) from e
            except httpx.RequestError as e:
                raise LdsAdapterError(f"LDS request failed: {e}") from e

            data = response.json()
            parts = [{"part_num": i + 1, "state": p.get("session_part_state", ""), "form_qualified_name": p.get("form_qualified_name")} for i, p in enumerate(data.get("session_parts", []))]

            return LdsSessionInfo(
                session_id=session_id,
                status=data.get("state", "unknown"),
                session_parts=parts,
            )

    async def start_session(self, session_id: str) -> str:
        """Activate a provisioned LDS session.

        Note: In the LDS Reservations v3 API, sessions become active when the
        candidate accesses the login URL. This method is a no-op status
        confirmation — the real activation happens via LDS's own flow.

        Args:
            session_id: LDS session UUID.

        Returns:
            Current session status string.
        """
        info = await self.get_session_status(session_id)
        log.info("LDS session start requested: session_id=%s, current_status=%s", session_id, info.status)
        return info.status

    async def pause_session(self, session_id: str) -> str:
        """Pause an active LDS session (freeze timer).

        Note: Timer pause is managed by the LDS frontend via postMessage.
        This endpoint updates the CPA's tracking state. The actual timer
        freeze happens in the LDS IFRAME via ``lcm:pause`` postMessage.

        Args:
            session_id: LDS session UUID.

        Returns:
            Status string "paused".
        """
        log.info("LDS session paused (CPA-side): session_id=%s", session_id)
        return "paused"

    async def resume_session(self, session_id: str) -> str:
        """Resume a paused LDS session.

        Note: Timer resume is managed by the LDS frontend via postMessage.
        This endpoint updates the CPA's tracking state. The actual timer
        resume happens in the LDS IFRAME via ``lcm:resume`` postMessage.

        Args:
            session_id: LDS session UUID.

        Returns:
            Status string "active".
        """
        log.info("LDS session resumed (CPA-side): session_id=%s", session_id)
        return "active"

    async def end_session(self, session_id: str) -> None:
        """End/archive an LDS session.

        Maps to: POST /reservations/v3/lab_session/{id}/release

        Args:
            session_id: LDS session UUID.

        Raises:
            LdsAdapterError: If archival fails.
        """
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=self._timeout) as client:
            url = f"{self._base_url}/reservations/v3/lab_session/{session_id}/release"
            log.info("Ending LDS session: session_id=%s", session_id)

            try:
                response = await client.post(url, json={}, auth=self._get_auth())
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    log.warning("LDS session %s not found during end — may already be archived", session_id)
                    return
                raise LdsAdapterError(f"Failed to end LDS session: {e.response.status_code}", status_code=e.response.status_code) from e
            except httpx.RequestError as e:
                raise LdsAdapterError(f"LDS end request failed: {e}") from e

            log.info("LDS session ended: session_id=%s", session_id)

    # =========================================================================
    # Internal helpers
    # =========================================================================

    async def _create_session(
        self,
        username: str,
        first_name: str,
        last_name: str,
        form_qualified_name: str,
        scheduled_date: str = "",
        rack_group: str = "LCM",
        rack_number: int = 1,
    ) -> str:
        """Create an LDS session (step 1 of provisioning).

        Maps to: POST /reservations/v3/lab_session
        """
        payload: dict[str, Any] = {
            "origin": "lablet-cloud-manager",
            "auth_id": username,
            "auth_id_type": "ordered_session",
            "candidate_id": username,
            "location": "cloud",
            "timezone_offset": 0,
            "first_name": first_name,
            "last_name": last_name,
            "rack_group": rack_group,
            "rack_number": rack_number,
            "scheduled_date": scheduled_date,
            "session_parts": [
                {
                    "repository_type": "minio",
                    "form_qualified_name": form_qualified_name,
                }
            ],
        }

        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=self._timeout) as client:
            url = f"{self._base_url}/reservations/v3/lab_session"
            log.info("Creating LDS session: user=%s, fqn=%s", username, form_qualified_name)

            try:
                response = await client.post(url, json=payload, auth=self._get_auth())
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise LdsProvisionError(f"LDS session creation failed: {e.response.status_code}", status_code=e.response.status_code) from e
            except httpx.RequestError as e:
                raise LdsProvisionError(f"LDS create request failed: {e}") from e

            data = response.json()
            session_id = data.get("session_id", "")
            if not session_id:
                raise LdsProvisionError("LDS returned empty session_id")

            log.info("LDS session created: session_id=%s", session_id)
            return session_id

    async def _set_devices(self, session_id: str, part_num: int, devices: list[dict[str, Any]]) -> None:
        """Set device access information (step 2 of provisioning).

        Maps to: PUT /reservations/v3/lab_session/{id}/part/{part_num}/devices
        """
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=self._timeout) as client:
            url = f"{self._base_url}/reservations/v3/lab_session/{session_id}/part/{part_num}/devices"
            log.info("Setting %d devices on session %s part %d", len(devices), session_id, part_num)

            try:
                response = await client.put(url, json=devices, auth=self._get_auth())
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise LdsProvisionError(f"LDS set_devices failed: {e.response.status_code}", status_code=e.response.status_code) from e
            except httpx.RequestError as e:
                raise LdsProvisionError(f"LDS set_devices request failed: {e}") from e

            log.info("Devices set on session %s: %d confirmed", session_id, len(devices))

    async def _get_launch_url(self, session_id: str) -> str:
        """Get the lablet launch URL (step 3 of provisioning).

        Maps to: GET /reservations/v3/lab_session/{id}/lablet_launch_url
        """
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=self._timeout) as client:
            url = f"{self._base_url}/reservations/v3/lab_session/{session_id}/lablet_launch_url"

            try:
                response = await client.get(url, auth=self._get_auth())
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise LdsProvisionError(f"Failed to get launch URL: {e.response.status_code}", status_code=e.response.status_code) from e
            except httpx.RequestError as e:
                raise LdsProvisionError(f"LDS launch URL request failed: {e}") from e

            data = response.json()
            launch_url = data.get("url", "")
            log.info("Got launch URL for session %s", session_id)
            return launch_url

    @staticmethod
    def _ports_to_devices(allocated_ports: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert LabletRecordRun allocated_ports to LDS device format.

        Input format (from PortMappingResolutionService):
            {"iosv-0": {"serial": {"host": "10.0.1.5", "port": 5041, "protocol": "telnet"}}}

        Output format (LDS API LDSSessionPartDev schema):
            [{"device_label": "iosv-0", "protocol": "telnet", "host": "10.0.1.5", "port": 5041}]

        AD-P4-03: device_label matches CML node label = content.xml device label.
        """
        devices: list[dict[str, Any]] = []
        for node_label, interfaces in allocated_ports.items():
            if isinstance(interfaces, dict):
                for _iface_name, iface_data in interfaces.items():
                    if isinstance(iface_data, dict):
                        device: dict[str, Any] = {
                            "device_label": node_label,
                            "protocol": iface_data.get("protocol", "telnet"),
                            "host": iface_data.get("host", ""),
                        }
                        if iface_data.get("port") is not None:
                            device["port"] = iface_data["port"]
                        devices.append(device)
        return devices

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        base_url: str = "",
        username: str = "",
        password: str = "",
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        """Register LdsAdapter as a singleton in the DI container.

        Args:
            services: Neuroglia service collection.
            base_url: LDS Reservations API base URL.
            username: HTTP Basic Auth username.
            password: HTTP Basic Auth password.
            verify_ssl: Whether to verify SSL certificates.
            timeout: HTTP request timeout in seconds.
        """
        services.add_singleton(
            cls,
            implementation_factory=lambda _: cls(
                lds_base_url=base_url,
                lds_username=username,
                lds_password=password,
                verify_ssl=verify_ssl,
                timeout=timeout,
            ),
        )
