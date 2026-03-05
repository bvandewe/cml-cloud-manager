"""LDS (Lab Delivery System) SPI Client for Lablet Controller.

Service Provider Interface (SPI) for LDS Reservations API v3.
Handles lab session lifecycle: create, set devices, get info, archive.

The SPI abstraction keeps the domain agnostic to the specific LDS
implementation — callers work with generic session concepts.

AD-P4-02: Multi-region deployment support via YAML configuration.
AD-P4-03: Device mapping uses CML node label = device_label.

Domain: Integration Layer (Lab Delivery)
Authentication: HTTP Basic Auth (per LDS API v3)
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import yaml

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class DeviceAccessInfo:
    """Device access information for LDS session provisioning.

    Maps to LDS API `LDSSessionPartDev` schema:
    - device_label (required): Node label from CML topology / content.xml
    - protocol (required): "telnet", "ssh", "vnc", "web"
    - host (required): Worker IP address
    - port (optional): Allocated port number
    - password (optional): Device VNC/access password
    """

    device_label: str
    protocol: str
    host: str
    port: int | None = None
    password: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        """Convert to LDS API request format (LDSSessionPartDev schema)."""
        result: dict[str, Any] = {
            "device_label": self.device_label,
            "protocol": self.protocol,
            "host": self.host,
        }
        if self.port is not None:
            result["port"] = self.port
        if self.password is not None:
            result["password"] = self.password
        return result


@dataclass
class SessionPartInfo:
    """LDS Session Part information."""

    part_num: int
    form_qualified_name: str | None = None
    track: str | None = None
    exam_version: str | None = None
    repository_type: str = "minio"
    session_part_state: str = ""


@dataclass
class LdsSessionInfo:
    """LDS session information returned from the API.

    Wraps the essential fields from the LDS API response.
    """

    session_id: str
    login_url: str
    status: str
    session_parts: list[SessionPartInfo] = field(default_factory=list)

    @classmethod
    def from_api_response(cls, data: dict[str, Any], login_url: str = "") -> "LdsSessionInfo":
        """Create from LDS API GET /lab_session/{id} response."""
        parts = []
        for idx, part_data in enumerate(data.get("session_parts", []), start=1):
            parts.append(
                SessionPartInfo(
                    part_num=idx,
                    form_qualified_name=part_data.get("form_qualified_name"),
                    track=part_data.get("track"),
                    exam_version=part_data.get("exam_version"),
                    repository_type=part_data.get("repository_type", "minio"),
                    session_part_state=part_data.get("session_part_state", ""),
                )
            )

        return cls(
            session_id=data.get("id", ""),
            login_url=login_url,
            status=data.get("state", ""),
            session_parts=parts,
        )


# =============================================================================
# LDS Deployment Configuration
# =============================================================================


@dataclass
class LdsDeploymentConfig:
    """Configuration for a single LDS deployment instance.

    Loaded from config/lds_deployments.yaml.
    """

    region: str
    base_url: str
    username: str
    password: str
    timeout_seconds: float = 30.0
    label: str = ""

    @classmethod
    def from_dict(cls, region: str, data: dict[str, Any]) -> "LdsDeploymentConfig":
        """Create from YAML config dictionary."""
        return cls(
            region=region,
            base_url=data.get("base_url", "").rstrip("/"),
            username=data.get("username", ""),
            password=data.get("password", ""),
            timeout_seconds=float(data.get("timeout_seconds", 30)),
            label=data.get("label", f"LDS {region}"),
        )


def load_lds_deployment_configs(config_path: str | None = None) -> tuple[dict[str, LdsDeploymentConfig], str]:
    """Load LDS deployment configurations from YAML file.

    Follows the same pattern as worker-controller's load_aws_region_configs().

    Args:
        config_path: Optional explicit path to YAML config file.

    Returns:
        Tuple of (region -> config mapping, default_region name).
    """
    if not config_path:
        candidates = [
            Path("config/lds_deployments.yaml"),
            Path("/app/config/lds_deployments.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = str(candidate)
                break

    if not config_path:
        logger.warning("No lds_deployments.yaml found. LDS integration will be unavailable.")
        return {}, ""

    path = Path(config_path)
    if not path.exists():
        logger.warning(f"LDS deployments config not found at {config_path}.")
        return {}, ""

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse lds_deployments.yaml: {e}")
        return {}, ""

    if not data or "deployments" not in data:
        logger.warning("No 'deployments' key found in lds_deployments.yaml")
        return {}, ""

    default_region = data.get("default_region", "")
    configs: dict[str, LdsDeploymentConfig] = {}

    for region_name, region_data in data["deployments"].items():
        configs[region_name] = LdsDeploymentConfig.from_dict(region_name, region_data)
        logger.info(f"Loaded LDS deployment config: {region_name} ({configs[region_name].label})")

    if default_region and default_region not in configs:
        logger.warning(f"Default region '{default_region}' not found in deployments. Using first available.")
        default_region = next(iter(configs)) if configs else ""

    return configs, default_region


# =============================================================================
# Error Types
# =============================================================================


class LdsSpiError(Exception):
    """Base exception for LDS SPI errors."""

    def __init__(self, message: str, status_code: int | None = None, response: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class LdsSessionNotFoundError(LdsSpiError):
    """Raised when an LDS session is not found."""

    pass


class LdsDeploymentNotFoundError(LdsSpiError):
    """Raised when no LDS deployment is configured for a region."""

    pass


# =============================================================================
# LDS SPI Client
# =============================================================================


class LdsSpiClient:
    """LDS Reservations API v3 Service Provider Interface.

    Handles lab session lifecycle management:
    - Session creation with content parts
    - Device access information provisioning
    - Session info retrieval and status confirmation
    - Lablet launch URL retrieval
    - Session finalization (archival)

    Multi-region: Selects the appropriate LDS deployment based on
    the worker's AWS region. Falls back to default deployment.

    Authentication: HTTP Basic Auth per LDS API v3 specification.
    """

    def __init__(
        self,
        deployments: dict[str, LdsDeploymentConfig] | None = None,
        default_region: str = "",
        verify_ssl: bool = True,
    ):
        """Initialize the LDS SPI client.

        Args:
            deployments: Region-to-deployment config mapping.
            default_region: Default region when no match found.
            verify_ssl: Whether to verify SSL certificates.
        """
        self._deployments = deployments or {}
        self._default_region = default_region
        self._verify_ssl = verify_ssl

    def _get_deployment(self, region: str | None = None) -> LdsDeploymentConfig:
        """Get the LDS deployment config for the given region.

        Args:
            region: AWS region identifier.

        Returns:
            LdsDeploymentConfig for the region.

        Raises:
            LdsDeploymentNotFoundError: If no deployment found for region.
        """
        # Try exact region match
        if region and region in self._deployments:
            return self._deployments[region]

        # Fall back to default
        if self._default_region and self._default_region in self._deployments:
            logger.info(f"No LDS deployment for region '{region}', using default '{self._default_region}'")
            return self._deployments[self._default_region]

        # No deployment available
        available = list(self._deployments.keys()) if self._deployments else []
        raise LdsDeploymentNotFoundError(f"No LDS deployment configured for region '{region}'. Available: {available}")

    def _get_auth(self, deployment: LdsDeploymentConfig) -> httpx.BasicAuth:
        """Create Basic Auth credentials for the deployment."""
        return httpx.BasicAuth(username=deployment.username, password=deployment.password)

    # =========================================================================
    # Session Lifecycle
    # =========================================================================

    async def create_session(
        self,
        username: str,
        first_name: str,
        last_name: str,
        scheduled_date: str,
        form_qualified_name: str,
        region: str | None = None,
        rack_group: str = "LCM",
        rack_number: int = 1,
        variables: dict[str, str] | None = None,
    ) -> LdsSessionInfo:
        """Create an LDS session with a content part.

        Maps to: POST /reservations/v3/lab_session

        Creates a session with one session_part referencing the lab content
        by form_qualified_name (MinIO repository type).

        Args:
            username: User/candidate identifier (auth_id).
            first_name: Candidate first name.
            last_name: Candidate last name.
            scheduled_date: ISO date string for the session.
            form_qualified_name: FQN of the lab content in LDS.
            region: AWS region to select LDS deployment.
            rack_group: Rack group identifier.
            rack_number: Rack number within group.
            variables: Optional content variables.

        Returns:
            LdsSessionInfo with session_id and login_url.

        Raises:
            LdsSpiError: If session creation fails.
        """
        deployment = self._get_deployment(region)

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
                    **({"variables": variables} if variables else {}),
                }
            ],
        }

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=deployment.timeout_seconds,
        ) as client:
            url = f"{deployment.base_url}/reservations/v3/lab_session"
            logger.info(f"Creating LDS session on {deployment.label} for user={username}, fqn={form_qualified_name}")

            try:
                response = await client.post(
                    url,
                    json=payload,
                    auth=self._get_auth(deployment),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"LDS session creation failed: {e.response.status_code} - {e.response.text}")
                raise LdsSpiError(
                    f"Failed to create LDS session: {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e
            except httpx.RequestError as e:
                logger.error(f"LDS session creation request failed: {e}")
                raise LdsSpiError(f"LDS request failed: {e}") from e

            data = response.json()
            session_id = data.get("session_id", "")

            logger.info(f"LDS session created: {session_id} on {deployment.label}")

            return LdsSessionInfo(
                session_id=session_id,
                login_url="",  # Retrieved separately via get_lablet_launch_url
                status="SESSION_PENDING",
            )

    async def set_devices(
        self,
        session_id: str,
        part_num: int,
        devices: list[DeviceAccessInfo],
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        """Set device access information for a session part.

        Maps to: PUT /reservations/v3/lab_session/{id}/part/{part_num}/devices

        Replaces any existing devices for the session part.

        Args:
            session_id: LDS session UUID.
            part_num: Session part number (1-based).
            devices: Device access information list.
            region: AWS region to select LDS deployment.

        Returns:
            List of device dicts as confirmed by LDS.

        Raises:
            LdsSpiError: If device update fails.
        """
        deployment = self._get_deployment(region)

        device_payload = [d.to_api_dict() for d in devices]

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=deployment.timeout_seconds,
        ) as client:
            url = f"{deployment.base_url}/reservations/v3/lab_session/{session_id}/part/{part_num}/devices"
            logger.info(f"Setting {len(devices)} devices on session {session_id} part {part_num}")

            try:
                response = await client.put(
                    url,
                    json=device_payload,
                    auth=self._get_auth(deployment),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"LDS set_devices failed: {e.response.status_code} - {e.response.text}")
                raise LdsSpiError(
                    f"Failed to set devices: {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e

            result = response.json()
            logger.info(f"Devices set on session {session_id}: {len(result)} devices confirmed")
            return list(result)

    async def get_session_info(
        self,
        session_id: str,
        region: str | None = None,
    ) -> LdsSessionInfo:
        """Get session details including status and parts.

        Maps to: GET /reservations/v3/lab_session/{id}

        Used to confirm session is pending and properly provisioned.

        Args:
            session_id: LDS session UUID.
            region: AWS region to select LDS deployment.

        Returns:
            LdsSessionInfo with current status.

        Raises:
            LdsSessionNotFoundError: If session not found.
            LdsSpiError: If request fails.
        """
        deployment = self._get_deployment(region)

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=deployment.timeout_seconds,
        ) as client:
            url = f"{deployment.base_url}/reservations/v3/lab_session/{session_id}"
            logger.debug(f"Getting session info for {session_id}")

            try:
                response = await client.get(
                    url,
                    auth=self._get_auth(deployment),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise LdsSessionNotFoundError(f"LDS session {session_id} not found", status_code=404) from e
                raise LdsSpiError(
                    f"Failed to get session info: {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e

            data = response.json()
            return LdsSessionInfo.from_api_response(data)

    async def get_lablet_launch_url(
        self,
        session_id: str,
        region: str | None = None,
    ) -> str:
        """Get the JWT-signed lablet launch URL for a session.

        Maps to: GET /reservations/v3/lab_session/{id}/lablet_launch_url

        This is the URL that users open to access the lab in lablet mode.
        Stored as session_login_url on the LabletSession.

        Args:
            session_id: LDS session UUID.
            region: AWS region to select LDS deployment.

        Returns:
            Launch URL string.

        Raises:
            LdsSpiError: If request fails.
        """
        deployment = self._get_deployment(region)

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=deployment.timeout_seconds,
        ) as client:
            url = f"{deployment.base_url}/reservations/v3/lab_session/{session_id}/lablet_launch_url"
            logger.debug(f"Getting lablet launch URL for session {session_id}")

            try:
                response = await client.get(
                    url,
                    auth=self._get_auth(deployment),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise LdsSpiError(
                    f"Failed to get launch URL: {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e

            data = response.json()
            launch_url = data.get("url", "")
            logger.info(f"Got lablet launch URL for session {session_id}")
            return launch_url

    async def archive_session(
        self,
        session_id: str,
        region: str | None = None,
    ) -> None:
        """Finalize (archive) an LDS session.

        Maps to: POST /reservations/v3/lab_session/{id}/release

        Called when instance reaches TERMINATED to clean up the LDS session.
        Graceful: failures are logged but do not propagate.

        Args:
            session_id: LDS session UUID.
            region: AWS region to select LDS deployment.

        Raises:
            LdsSpiError: If archival fails.
        """
        deployment = self._get_deployment(region)

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=deployment.timeout_seconds,
        ) as client:
            url = f"{deployment.base_url}/reservations/v3/lab_session/{session_id}/release"
            logger.info(f"Archiving LDS session {session_id} on {deployment.label}")

            try:
                response = await client.post(
                    url,
                    json={},  # LDS API expects a body (nullable object) for this endpoint; send empty JSON object to avoid HTTP 415
                    auth=self._get_auth(deployment),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"LDS session archival failed: {e.response.status_code} - {e.response.text}")
                raise LdsSpiError(
                    f"Failed to archive session: {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e

            logger.info(f"LDS session {session_id} archived successfully")

    # =========================================================================
    # Content Synchronization (AD-CS-001)
    # =========================================================================

    async def sync_content(
        self,
        form_qualified_name: str,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Trigger LDS to refresh content from MinIO for the given FQN.

        Calls: PUT /reservations/v3/lab_folder/minio/{form_qualified_name}
        Auth: HTTP Basic Auth per deployment.

        This tells LDS to re-read the content package from MinIO/RustFS
        for the specified form_qualified_name, ensuring LDS serves the
        latest version to users.

        Args:
            form_qualified_name: The FQN as stored in the LabletDefinition.
            region: Optional region override (uses default_region if None).

        Returns:
            LabFolder response dict from LDS (includes Version, Size, etc.).

        Raises:
            LdsSpiError: On non-2xx response.
        """
        deployment = self._get_deployment(region)

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=deployment.timeout_seconds,
        ) as client:
            url = f"{deployment.base_url}/reservations/v3/lab_folder/minio/{form_qualified_name}"
            logger.info(f"LDS sync_content: PUT {url} (deployment={deployment.label})")

            try:
                response = await client.put(
                    url,
                    auth=self._get_auth(deployment),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"LDS sync_content failed: {e.response.status_code} - {e.response.text}")
                raise LdsSpiError(
                    f"LDS sync_content failed for '{form_qualified_name}': {e.response.status_code}",
                    status_code=e.response.status_code,
                ) from e
            except httpx.RequestError as e:
                logger.error(f"LDS sync_content request failed: {e}")
                raise LdsSpiError(f"LDS sync_content request failed: {e}") from e

            data = response.json()
            logger.info(f"LDS sync_content success for '{form_qualified_name}': version={data.get('Version')}")
            return data

    # =========================================================================
    # Utility
    # =========================================================================

    @property
    def available_regions(self) -> list[str]:
        """List configured LDS deployment regions."""
        return list(self._deployments.keys())

    @property
    def default_region(self) -> str:
        """Get the default deployment region."""
        return self._default_region

    def has_deployment(self, region: str) -> bool:
        """Check if an LDS deployment exists for the given region."""
        return region in self._deployments

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        config_path: str | None = None,
        verify_ssl: bool = True,
    ) -> None:
        """Configure DI registration.

        Loads LDS deployment configurations from YAML and registers
        the client as a singleton.

        Args:
            services: Neuroglia service collection.
            config_path: Optional explicit path to lds_deployments.yaml.
            verify_ssl: Whether to verify SSL certificates.
        """
        deployments, default_region = load_lds_deployment_configs(config_path)

        services.add_singleton(
            cls,
            implementation_factory=lambda _: cls(
                deployments=deployments,
                default_region=default_region,
                verify_ssl=verify_ssl,
            ),
        )
