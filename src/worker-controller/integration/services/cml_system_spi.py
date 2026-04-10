"""CML System SPI Client for Worker Controller.

Service Provider Interface (SPI) for CML Worker system operations.
Handles system stats, health checks, and license management.

CML API Reference: CML v2.9 OpenAPI Spec
    - GET /api/v0/system_information (no auth)
    - GET /api/v0/system_stats (auth required)
    - GET /api/v0/system_health (auth required)
    - GET /api/v0/licensing (auth required)
    - POST /api/v0/licensing/registration (auth required)
    - POST /api/v0/licensing/deregistration (auth required)
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

logger = logging.getLogger(__name__)


# =============================================================================
# Data Transfer Objects — Matching CML v2.9 API Response Structures
# =============================================================================


@dataclass
class CmlCpuStats:
    """CPU statistics from CML system_stats.all.cpu or computes.*.stats.cpu."""

    count: int = 0
    percent: float = 0.0


@dataclass
class CmlMemoryStats:
    """Memory statistics from CML system_stats.all.memory (values in bytes)."""

    total: int = 0
    free: int = 0
    used: int = 0


@dataclass
class CmlDiskStats:
    """Disk statistics from CML system_stats.all.disk (values in bytes)."""

    total: int = 0
    free: int = 0
    used: int = 0


@dataclass
class CmlDomInfo:
    """Domain info from CML system_stats.computes.*.stats.dominfo."""

    allocated_cpus: int = 0
    allocated_memory: int = 0
    total_nodes: int = 0
    total_orphans: int = 0
    running_nodes: int = 0
    running_orphans: int = 0


@dataclass
class CmlComputeNodeStats:
    """Per-compute-node statistics from CML system_stats.computes.*.stats."""

    cpu: CmlCpuStats = field(default_factory=CmlCpuStats)
    memory: CmlMemoryStats = field(default_factory=CmlMemoryStats)
    disk: CmlDiskStats = field(default_factory=CmlDiskStats)
    dominfo: CmlDomInfo = field(default_factory=CmlDomInfo)


@dataclass
class CmlComputeNode:
    """A compute host from CML system_stats.computes.<uuid>."""

    compute_id: str
    hostname: str
    is_controller: bool
    stats: CmlComputeNodeStats = field(default_factory=CmlComputeNodeStats)


@dataclass
class CmlSystemStats:
    """Full CML system statistics from GET /api/v0/system_stats.

    Captures the nested structure:
    - all: aggregate stats across all compute hosts
    - controller: controller-specific disk stats
    - computes: per-host stats with cpu/memory/disk/dominfo
    """

    # Aggregate stats (all compute hosts combined)
    cpu: CmlCpuStats = field(default_factory=CmlCpuStats)
    memory: CmlMemoryStats = field(default_factory=CmlMemoryStats)
    disk: CmlDiskStats = field(default_factory=CmlDiskStats)

    # Controller disk stats
    controller_disk: CmlDiskStats = field(default_factory=CmlDiskStats)

    # Per-compute-host stats (keyed by compute UUID)
    computes: list[CmlComputeNode] = field(default_factory=list)

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "CmlSystemStats":
        """Parse the CML /api/v0/system_stats JSON response.

        Args:
            data: Raw JSON response from CML API.

        Returns:
            Fully-populated CmlSystemStats.
        """
        # Parse "all" section (aggregate stats)
        all_data = data.get("all", {})
        cpu_data = all_data.get("cpu", {})
        memory_data = all_data.get("memory", {})
        disk_data = all_data.get("disk", {})

        cpu = CmlCpuStats(
            count=cpu_data.get("count", 0),
            percent=cpu_data.get("percent", 0.0),
        )
        memory = CmlMemoryStats(
            total=int(memory_data.get("total", 0)),
            free=int(memory_data.get("free", 0)),
            used=int(memory_data.get("used", 0)),
        )
        disk = CmlDiskStats(
            total=int(disk_data.get("total", 0)),
            free=int(disk_data.get("free", 0)),
            used=int(disk_data.get("used", 0)),
        )

        # Parse "controller" section (controller disk only)
        controller_data = data.get("controller", {})
        controller_disk_data = controller_data.get("disk", {})
        controller_disk = CmlDiskStats(
            total=int(controller_disk_data.get("total", 0)),
            free=int(controller_disk_data.get("free", 0)),
            used=int(controller_disk_data.get("used", 0)),
        )

        # Parse "computes" section (per-host stats with dominfo)
        computes_data = data.get("computes", {})
        computes: list[CmlComputeNode] = []
        for compute_id, compute_info in computes_data.items():
            stats_data = compute_info.get("stats", {})
            node_cpu = stats_data.get("cpu", {})
            node_mem = stats_data.get("memory", {})
            node_disk = stats_data.get("disk", {})
            node_dom = stats_data.get("dominfo", {})

            node = CmlComputeNode(
                compute_id=compute_id,
                hostname=compute_info.get("hostname", "unknown"),
                is_controller=compute_info.get("is_controller", False),
                stats=CmlComputeNodeStats(
                    cpu=CmlCpuStats(
                        count=node_cpu.get("count", 0),
                        percent=node_cpu.get("percent", 0.0),
                    ),
                    memory=CmlMemoryStats(
                        total=int(node_mem.get("total", 0)),
                        free=int(node_mem.get("free", 0)),
                        used=int(node_mem.get("used", 0)),
                    ),
                    disk=CmlDiskStats(
                        total=int(node_disk.get("total", 0)),
                        free=int(node_disk.get("free", 0)),
                        used=int(node_disk.get("used", 0)),
                    ),
                    dominfo=CmlDomInfo(
                        allocated_cpus=node_dom.get("allocated_cpus", 0),
                        allocated_memory=node_dom.get("allocated_memory", 0),
                        total_nodes=node_dom.get("total_nodes", 0),
                        total_orphans=node_dom.get("total_orphans", 0),
                        running_nodes=node_dom.get("running_nodes", 0),
                        running_orphans=node_dom.get("running_orphans", 0),
                    ),
                ),
            )
            computes.append(node)

        return cls(
            cpu=cpu,
            memory=memory,
            disk=disk,
            controller_disk=controller_disk,
            computes=computes,
        )


@dataclass
class CmlSystemInfo:
    """CML Worker system information from GET /api/v0/system_information."""

    version: str
    ready: bool
    hostname: str | None = None
    product: str = "CML"


@dataclass
class CmlComputeHealth:
    """Health status of a single compute node from system_health.computes.<uuid>."""

    compute_id: str
    hostname: str
    is_controller: bool = False
    kvm_vmx_enabled: bool | None = None
    enough_cpus: bool | None = None
    lld_connected: bool = False
    lld_synced: bool | None = None
    libvirt: bool | None = None
    fabric: bool | None = None
    device_mux: bool | None = None
    refplat_images_available: bool | None = None
    docker_shim: bool | None = None
    valid: bool | None = None
    admission_state: str = "UNREGISTERED"


@dataclass
class CmlControllerHealth:
    """Controller health from system_health.controller."""

    core_connected: bool = False
    nodes_loaded: bool = False
    images_loaded: bool = False
    valid: bool = False


@dataclass
class CmlSystemHealth:
    """Full CML system health from GET /api/v0/system_health.

    Captures overall validity, licensing status, per-compute health,
    and controller health.
    """

    valid: bool | None = None
    is_licensed: bool | None = None
    is_enterprise: bool = False
    computes: list[CmlComputeHealth] = field(default_factory=list)
    controller: CmlControllerHealth = field(default_factory=CmlControllerHealth)

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "CmlSystemHealth":
        """Parse the CML /api/v0/system_health JSON response.

        Args:
            data: Raw JSON response from CML API.

        Returns:
            Fully-populated CmlSystemHealth.
        """
        # Parse per-compute health
        computes_data = data.get("computes", {})
        computes: list[CmlComputeHealth] = []
        for compute_id, health_info in computes_data.items():
            computes.append(
                CmlComputeHealth(
                    compute_id=compute_id,
                    hostname=health_info.get("hostname", "unknown"),
                    is_controller=health_info.get("is_controller", False),
                    kvm_vmx_enabled=health_info.get("kvm_vmx_enabled"),
                    enough_cpus=health_info.get("enough_cpus"),
                    lld_connected=health_info.get("lld_connected", False),
                    lld_synced=health_info.get("lld_synced"),
                    libvirt=health_info.get("libvirt"),
                    fabric=health_info.get("fabric"),
                    device_mux=health_info.get("device_mux"),
                    refplat_images_available=health_info.get("refplat_images_available"),
                    docker_shim=health_info.get("docker_shim"),
                    valid=health_info.get("valid"),
                    admission_state=health_info.get("admission_state", "UNREGISTERED"),
                )
            )

        # Parse controller health
        controller_data = data.get("controller", {})
        controller = CmlControllerHealth(
            core_connected=controller_data.get("core_connected", False),
            nodes_loaded=controller_data.get("nodes_loaded", False),
            images_loaded=controller_data.get("images_loaded", False),
            valid=controller_data.get("valid", False),
        )

        return cls(
            valid=data.get("valid"),
            is_licensed=data.get("is_licensed"),
            is_enterprise=data.get("is_enterprise", False),
            computes=computes,
            controller=controller,
        )


@dataclass
class CmlLicenseInfo:
    """CML Worker license information from GET /api/v0/licensing.

    Parsed from nested registration/authorization/features/product_license structure.
    """

    # Derived fields
    is_valid: bool
    registration_status: str  # COMPLETED, IN_PROGRESS, NOT_REGISTERED, etc.
    authorization_status: str  # IN_COMPLIANCE, OUT_OF_COMPLIANCE, etc.
    node_limit: int  # from features[0].max (base license)
    nodes_in_use: int  # from features[0].in_use (base license)
    expires_at: str | None = None  # registration.expires
    authorization_expires_at: str | None = None  # authorization.expires
    product: str | None = None  # product_license.active
    is_enterprise: bool = False  # product_license.is_enterprise
    smart_account: str | None = None
    virtual_account: str | None = None

    # Raw data for pass-through to CPA
    features: list[dict[str, Any]] = field(default_factory=list)
    # Full raw CML API response for License Details modal
    raw_response: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "CmlLicenseInfo":
        """Parse the CML /api/v0/licensing JSON response.

        Args:
            data: Raw JSON response from CML API.

        Returns:
            Fully-populated CmlLicenseInfo.
        """
        registration = data.get("registration", {})
        authorization = data.get("authorization", {})
        features = data.get("features", [])
        product_license = data.get("product_license", {})

        registration_status = registration.get("status", "NOT_REGISTERED")
        authorization_status = authorization.get("status", "UNKNOWN")

        # Determine validity: registered + in compliance
        is_valid = registration_status in ("COMPLETED", "REGISTERED") and authorization_status in ("IN_COMPLIANCE", "AUTHORIZED")

        # Extract node limits from features
        node_limit = 0
        nodes_in_use = 0
        raw_features: list[dict[str, Any]] = []
        for feat in features:
            raw_features.append(dict(feat))  # Copy for pass-through
            # Sum up max across all feature types for total node capacity
            node_limit += feat.get("max", 0)
            nodes_in_use += feat.get("in_use", 0)

        return cls(
            is_valid=is_valid,
            registration_status=registration_status,
            authorization_status=authorization_status,
            node_limit=node_limit,
            nodes_in_use=nodes_in_use,
            expires_at=registration.get("expires"),
            authorization_expires_at=authorization.get("expires"),
            product=product_license.get("active"),
            is_enterprise=product_license.get("is_enterprise", False),
            smart_account=registration.get("smart_account"),
            virtual_account=registration.get("virtual_account"),
            features=raw_features,
            raw_response=dict(data),  # Preserve full response for License Details modal
        )


class CmlSystemSpiClient:
    """CML System API Service Provider Interface.

    Handles communication with CML Worker system API for:
    - System stats (cpu, memory, disk)
    - System information (version, health)
    - License status
    """

    def __init__(
        self,
        default_username: str = "admin",
        default_password: str = "",
        timeout: float = 30.0,
        verify_ssl: bool = False,
    ):
        """Initialize the CML System SPI client.

        Args:
            default_username: Default CML API username.
            default_password: Default CML API password.
            timeout: HTTP request timeout.
            verify_ssl: Whether to verify SSL certificates.
        """
        self._default_username = default_username
        self._default_password = default_password
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._token_cache: dict[str, str] = {}  # host -> token

    async def _authenticate(
        self,
        client: httpx.AsyncClient,
        host: str,
        username: str,
        password: str,
        force_refresh: bool = False,
    ) -> str:
        """Authenticate and get bearer token.

        Args:
            client: HTTP client.
            host: CML worker host.
            username: API username.
            password: API password.
            force_refresh: If True, bypass cache and re-authenticate.

        Returns:
            Bearer token.
        """
        cache_key = f"{host}:{username}"
        if not force_refresh and cache_key in self._token_cache:
            return self._token_cache[cache_key]

        # Clear stale token before re-authenticating
        self._token_cache.pop(cache_key, None)

        url = f"https://{host}/api/v0/authenticate"

        response = await client.post(
            url,
            json={"username": username, "password": password},
        )
        response.raise_for_status()

        token = response.json()
        self._token_cache[cache_key] = token
        logger.debug(f"Authenticated with CML at {host} (user={username}, refreshed={force_refresh})")
        return token

    def _invalidate_token(self, host: str, username: str) -> None:
        """Invalidate a cached token for a specific host and username.

        Args:
            host: CML worker host.
            username: API username.
        """
        cache_key = f"{host}:{username}"
        if cache_key in self._token_cache:
            del self._token_cache[cache_key]
            logger.debug(f"Invalidated cached CML token for {host} (user={username})")

    async def _authenticated_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        host: str,
        username: str,
        password: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make an authenticated request with automatic retry on 401.

        If the first attempt returns 401 (expired token), invalidates the
        cached token, re-authenticates, and retries the request once.

        Args:
            client: HTTP client.
            method: HTTP method (GET, POST, PUT, DELETE).
            url: Request URL.
            host: CML worker host (for auth).
            username: API username.
            password: API password.
            **kwargs: Additional kwargs passed to httpx request.

        Returns:
            httpx.Response on success.

        Raises:
            httpx.HTTPStatusError: If retry also fails.
        """
        token = await self._authenticate(client, host, username, password)
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        response = await client.request(method, url, headers=headers, **kwargs)

        if response.status_code == 401:
            # Token expired — invalidate, re-authenticate, retry once
            logger.info(f"CML token expired for {host}, re-authenticating...")
            self._invalidate_token(host, username)
            token = await self._authenticate(client, host, username, password, force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            response = await client.request(method, url, headers=headers, **kwargs)

        response.raise_for_status()
        return response

    async def get_system_info(self, host: str) -> CmlSystemInfo:
        """Get CML system information (no auth required).

        Args:
            host: CML worker host/IP.

        Returns:
            CmlSystemInfo with version and readiness.
        """
        url = f"https://{host}/api/v0/system_information"

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                return CmlSystemInfo(
                    version=data.get("version", "unknown"),
                    ready=data.get("ready", False),
                    hostname=data.get("hostname"),
                    product=data.get("product", "CML"),
                )
            except httpx.HTTPError as e:
                logger.error(f"Error getting system info from {host}: {type(e).__name__}: {e}")
                raise

    async def get_system_stats(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> CmlSystemStats:
        """Get CML system statistics (requires auth).

        Calls GET /api/v0/system_stats which returns nested structure:
        - all: {cpu: {count, percent}, memory: {total, free, used}, disk: {total, free, used}}
        - controller: {disk: {total, free, used}}
        - computes: {<uuid>: {hostname, is_controller, stats: {cpu, memory, disk, dominfo}}}

        Args:
            host: CML worker host/IP.
            username: API username (uses default if not provided).
            password: API password (uses default if not provided).

        Returns:
            CmlSystemStats with full cpu, memory, disk, compute node data.
        """
        username = username or self._default_username
        password = password or self._default_password
        url = f"https://{host}/api/v0/system_stats"

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                response = await self._authenticated_request(
                    client,
                    "GET",
                    url,
                    host,
                    username,
                    password,
                )
                data = response.json()

                return CmlSystemStats.from_api_response(data)
            except httpx.HTTPError as e:
                logger.error(f"Error getting system stats from {host}: {type(e).__name__}: {e}")
                raise

    async def get_system_health(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> CmlSystemHealth:
        """Get CML system health (requires auth).

        Calls GET /api/v0/system_health which returns:
        - valid: overall system health
        - is_licensed: license status
        - is_enterprise: enterprise edition flag
        - computes: {<uuid>: {kvm_vmx_enabled, enough_cpus, lld_connected, ...}}
        - controller: {core_connected, nodes_loaded, images_loaded, valid}

        Args:
            host: CML worker host/IP.
            username: API username (uses default if not provided).
            password: API password (uses default if not provided).

        Returns:
            CmlSystemHealth with full health data.
        """
        username = username or self._default_username
        password = password or self._default_password
        url = f"https://{host}/api/v0/system_health"

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                response = await self._authenticated_request(
                    client,
                    "GET",
                    url,
                    host,
                    username,
                    password,
                )
                data = response.json()

                return CmlSystemHealth.from_api_response(data)
            except httpx.HTTPError as e:
                logger.error(f"Error getting system health from {host}: {type(e).__name__}: {e}")
                raise

    async def get_license_info(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> CmlLicenseInfo:
        """Get CML license information.

        Calls GET /api/v0/licensing which returns nested structure:
        - registration: {status, smart_account, virtual_account, expires, ...}
        - authorization: {status, expires, ...}
        - features: [{name, in_use, status, max, ...}]
        - product_license: {active, is_enterprise}
        - udi: {hostname, product_uuid}

        Args:
            host: CML worker host/IP.
            username: API username (uses default if not provided).
            password: API password (uses default if not provided).

        Returns:
            CmlLicenseInfo with parsed license status.
        """
        username = username or self._default_username
        password = password or self._default_password
        url = f"https://{host}/api/v0/licensing"

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                response = await self._authenticated_request(
                    client,
                    "GET",
                    url,
                    host,
                    username,
                    password,
                )
                data = response.json()

                return CmlLicenseInfo.from_api_response(data)
            except httpx.HTTPError as e:
                logger.error(f"Error getting license info from {host}: {type(e).__name__}: {e}")
                raise

    async def register_license(
        self,
        host: str,
        token: str,
        username: str | None = None,
        password: str | None = None,
        reregister: bool = False,
    ) -> tuple[bool, str]:
        """Register a license on the CML worker.

        ADR-016: Called by worker-controller during license reconciliation.

        Args:
            host: CML worker host/IP.
            token: License token to register.
            username: API username (uses default if not provided).
            password: API password (uses default if not provided).
            reregister: Whether to re-register an existing license.

        Returns:
            Tuple of (success, message).
        """
        username = username or self._default_username
        password = password or self._default_password
        url = f"https://{host}/api/v0/licensing/registration"

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                payload = {"token": token}
                if reregister:
                    payload["reregister"] = True

                await self._authenticated_request(
                    client,
                    "POST",
                    url,
                    host,
                    username,
                    password,
                    json=payload,
                )

                logger.info(f"✅ License registration initiated on {host}")
                return True, "Registration initiated"

            except httpx.HTTPStatusError as e:
                error_msg = f"License registration failed: {e.response.status_code}"
                try:
                    error_data = e.response.json()
                    if isinstance(error_data, dict):
                        error_msg = error_data.get("message", error_msg)
                except Exception:
                    pass
                logger.error(f"❌ {error_msg} on {host}")
                return False, error_msg
            except httpx.HTTPError as e:
                logger.error(f"Error registering license on {host}: {type(e).__name__}: {e}")
                return False, f"{type(e).__name__}: {e}"

    async def deregister_license(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> tuple[bool, str]:
        """Deregister the license from the CML worker.

        ADR-016: Called by worker-controller during license reconciliation.

        Args:
            host: CML worker host/IP.
            username: API username (uses default if not provided).
            password: API password (uses default if not provided).

        Returns:
            Tuple of (success, message).
        """
        username = username or self._default_username
        password = password or self._default_password
        url = f"https://{host}/api/v0/licensing/deregistration"

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                await self._authenticated_request(
                    client,
                    "POST",
                    url,
                    host,
                    username,
                    password,
                )

                logger.info(f"✅ License deregistration completed on {host}")
                return True, "Deregistration completed"

            except httpx.HTTPStatusError as e:
                error_msg = f"License deregistration failed: {e.response.status_code}"
                try:
                    error_data = e.response.json()
                    if isinstance(error_data, dict):
                        error_msg = error_data.get("message", error_msg)
                except Exception:
                    pass
                logger.error(f"❌ {error_msg} on {host}")
                return False, error_msg
            except httpx.HTTPError as e:
                logger.error(f"Error deregistering license on {host}: {type(e).__name__}: {e}")
                return False, f"{type(e).__name__}: {e}"

    async def get_telemetry_events(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch telemetry events from a CML worker.

        Delegates CML API call per ADR-015: external CML calls are made
        by controllers, not the control-plane-api.

        Endpoint: GET /api/v0/telemetry/events (auth required)
        Returns ALL telemetry events — no server-side filtering parameters.

        Args:
            host: CML worker host/IP.
            username: API username (uses default if not provided).
            password: API password (uses default if not provided).

        Returns:
            List of event dicts with category, timestamp, and data.
            Empty list if the endpoint is unreachable or returns an error.
        """
        username = username or self._default_username
        password = password or self._default_password
        url = f"https://{host}/api/v0/telemetry/events"

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                response = await self._authenticated_request(
                    client,
                    "GET",
                    url,
                    host,
                    username,
                    password,
                )
                events = response.json()
                logger.debug(f"Retrieved {len(events)} telemetry events from {host}")
                return events
            except httpx.HTTPError as e:
                logger.error(f"Error fetching telemetry events from {host}: {type(e).__name__}: {e}")
                raise

    async def check_health(self, host: str) -> tuple[bool, str]:
        """Quick health check for a CML worker.

        Args:
            host: CML worker host/IP.

        Returns:
            Tuple of (is_healthy, message).
        """
        try:
            info = await self.get_system_info(host)
            if info.ready:
                return True, f"CML {info.version} ready"
            else:
                return False, f"CML {info.version} not ready"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def clear_token_cache(self, host: str | None = None) -> None:
        """Clear cached authentication tokens.

        Args:
            host: Specific host to clear, or None for all.
        """
        if host:
            self._token_cache = {k: v for k, v in self._token_cache.items() if not k.startswith(host)}
        else:
            self._token_cache.clear()

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        default_username: str = "admin",
        default_password: str = "",
        timeout: float = 30.0,
        verify_ssl: bool = False,
    ) -> None:
        """Configure DI registration.

        Args:
            services: Neuroglia service collection.
            default_username: Default CML API username.
            default_password: Default CML API password.
            timeout: HTTP request timeout.
            verify_ssl: Whether to verify SSL certificates.
        """
        services.add_singleton(
            cls,
            implementation_factory=lambda _: cls(
                default_username=default_username,
                default_password=default_password,
                timeout=timeout,
                verify_ssl=verify_ssl,
            ),
        )
