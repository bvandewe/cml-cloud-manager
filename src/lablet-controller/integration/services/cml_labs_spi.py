"""CML Labs SPI Client for Lablet Controller.

Service Provider Interface (SPI) for CML Labs API operations.
Handles lab lifecycle: import, start, stop, wipe, delete.

Domain: Application Layer (Workloads)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from neuroglia.dependency_injection.service_collection import ServiceCollection

logger = logging.getLogger(__name__)


class LabState(str, Enum):
    """CML Lab states."""

    DEFINED_ON_CORE = "DEFINED_ON_CORE"
    STOPPED = "STOPPED"
    STARTED = "STARTED"
    BOOTED = "BOOTED"
    QUEUED = "QUEUED"


@dataclass
class LabInfo:
    """CML Lab information."""

    id: str
    title: str
    state: LabState
    owner: str | None = None
    description: str | None = None
    notes: str | None = None
    owner_username: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    node_count: int = 0
    link_count: int = 0


@dataclass
class NodeInfo:
    """CML Lab node information."""

    id: str
    label: str
    node_definition: str
    state: str
    cpu_limit: int | None = None
    ram: int | None = None
    config: str | None = None
    x: int = 0
    y: int = 0
    tags: list[str] | None = None  # Node tags (e.g. ["serial:5041", "vnc:5044"])


@dataclass
class InterfaceInfo:
    """CML Lab node interface information."""

    id: str
    label: str
    node_id: str
    slot: int | None = None
    state: str | None = None
    mac_address: str | None = None
    ip4: list[str] | None = None


@dataclass
class LinkInfo:
    """CML Lab link information."""

    id: str
    label: str | None = None
    state: str | None = None
    node_a: str | None = None  # Node A ID
    node_b: str | None = None  # Node B ID
    interface_a: str | None = None  # Interface A ID
    interface_b: str | None = None  # Interface B ID


@dataclass
class SimulationStats:
    """CML lab simulation statistics — runtime resource metrics.

    ADR-030: Captures per-node CPU/state data from the CML simulation_stats API.
    """

    lab_id: str
    nodes: dict[str, Any]  # Per-node simulation data (CPU, state, etc.)
    links: dict[str, Any]  # Per-link simulation data
    raw: dict[str, Any]  # Full raw response for future use


@dataclass
class LabTopology:
    """Complete lab topology with nodes and interfaces."""

    lab: LabInfo
    nodes: list[NodeInfo]
    interfaces: dict[str, list[InterfaceInfo]]  # node_id -> interfaces


class CmlLabsSpiClient:
    """CML Labs API Service Provider Interface.

    Handles lab lifecycle management via CML Labs API:
    - Lab CRUD operations
    - Lab state management (start, stop, wipe)
    - Lab import from topology YAML
    - Node and interface queries
    """

    def __init__(
        self,
        default_username: str = "admin",
        default_password: str = "",
        timeout: float = 60.0,
        verify_ssl: bool = False,
    ):
        """Initialize the CML Labs SPI client.

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
        """Authenticate and get bearer token."""
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
        **kwargs,
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

    async def list_labs(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
    ) -> list[LabInfo]:
        """List all labs on a CML worker.

        Args:
            host: CML worker host/IP.
            username: API username.
            password: API password.

        Returns:
            List of LabInfo objects.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            response = await self._authenticated_request(
                client,
                "GET",
                f"https://{host}/api/v0/labs",
                host,
                username,
                password,
            )

            labs = []
            for lab_id in response.json():
                # Get lab details
                lab_info = await self.get_lab(host, lab_id, username, password)
                if lab_info:
                    labs.append(lab_info)

            return labs

    async def get_lab(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> LabInfo | None:
        """Get lab information.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            LabInfo or None if not found.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                response = await self._authenticated_request(
                    client,
                    "GET",
                    f"https://{host}/api/v0/labs/{lab_id}",
                    host,
                    username,
                    password,
                )

                data = response.json()

                # Parse timestamps from CML API
                created_at = None
                if data.get("created"):
                    try:
                        created_at = datetime.fromisoformat(data["created"])
                    except (ValueError, TypeError):
                        pass
                modified_at = None
                if data.get("modified"):
                    try:
                        modified_at = datetime.fromisoformat(data["modified"])
                    except (ValueError, TypeError):
                        pass

                return LabInfo(
                    id=lab_id,
                    title=data.get("lab_title", data.get("title", "")),
                    state=LabState(data.get("state", "DEFINED_ON_CORE")),
                    owner=data.get("owner"),
                    description=data.get("lab_description"),
                    notes=data.get("lab_notes"),
                    owner_username=data.get("owner_username"),
                    node_count=data.get("node_count", 0),
                    link_count=data.get("link_count", 0),
                    created_at=created_at,
                    modified_at=modified_at,
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return None
                raise

    async def get_lab_state(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> LabState | None:
        """Get lab state.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            LabState or None if not found.
        """
        lab = await self.get_lab(host, lab_id, username, password)
        return lab.state if lab else None

    async def import_lab(
        self,
        host: str,
        topology_yaml: str,
        title: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> str:
        """Import a lab from YAML topology.

        Args:
            host: CML worker host/IP.
            topology_yaml: YAML topology definition.
            title: Optional lab title override.
            username: API username.
            password: API password.

        Returns:
            New lab ID.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            params = {}
            if title:
                params["title"] = title

            response = await self._authenticated_request(
                client,
                "POST",
                f"https://{host}/api/v0/import",
                host,
                username,
                password,
                params=params,
                content=topology_yaml,
                headers={"Content-Type": "application/x-yaml"},
            )

            data = response.json()
            lab_id = data.get("id")
            logger.info(f"Imported lab {lab_id} on {host}")
            return lab_id

    async def start_lab(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> bool:
        """Start a lab.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            True if start initiated successfully.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            await self._authenticated_request(
                client,
                "PUT",
                f"https://{host}/api/v0/labs/{lab_id}/start",
                host,
                username,
                password,
            )

            logger.info(f"Started lab {lab_id} on {host}")
            return True

    async def stop_lab(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> bool:
        """Stop a lab.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            True if stop initiated successfully.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            await self._authenticated_request(
                client,
                "PUT",
                f"https://{host}/api/v0/labs/{lab_id}/stop",
                host,
                username,
                password,
            )

            logger.info(f"Stopped lab {lab_id} on {host}")
            return True

    async def wipe_lab(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> bool:
        """Wipe a lab (destroy all VMs but keep topology).

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            True if wipe successful.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            await self._authenticated_request(
                client,
                "PUT",
                f"https://{host}/api/v0/labs/{lab_id}/wipe",
                host,
                username,
                password,
            )

            logger.info(f"Wiped lab {lab_id} on {host}")
            return True

    async def delete_lab(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> bool:
        """Delete a lab completely.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            True if deletion successful.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            await self._authenticated_request(
                client,
                "DELETE",
                f"https://{host}/api/v0/labs/{lab_id}",
                host,
                username,
                password,
            )

            logger.info(f"Deleted lab {lab_id} on {host}")
            return True

    async def download_lab(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> str:
        """Download lab topology as YAML.

        ADR-017: Used by BFF endpoint for lab download.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            YAML topology string.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            response = await self._authenticated_request(
                client,
                "GET",
                f"https://{host}/api/v0/labs/{lab_id}/download",
                host,
                username,
                password,
                headers={"Accept": "application/x-yaml"},
            )

            logger.info(f"Downloaded lab {lab_id} from {host} ({len(response.text)} bytes)")
            return response.text

    async def patch_node_tags(
        self,
        host: str,
        lab_id: str,
        node_id: str,
        tags: list[str],
        username: str | None = None,
        password: str | None = None,
    ) -> dict:
        """Update tags on a CML lab node.

        Uses PATCH /api/v0/labs/{lab_id}/nodes/{node_id} with NodeUpdate schema.
        Tags are fully replaced (not merged) — caller must provide the
        complete tag list.

        AD-TAGS-001: Required by the ``tags_sync`` pipeline step to write
        allocated port numbers back to CML node tags (e.g., ``["serial:3001",
        "vnc:3002"]``).  Tags persist across start/stop/wipe — they are
        topology-level metadata.

        Args:
            host: CML worker host/IP.
            lab_id: CML lab ID.
            node_id: CML node ID within the lab.
            tags: Complete list of tags (e.g., ``["serial:3001", "vnc:3002"]``).
            username: API username.
            password: API password.

        Returns:
            Updated node dict from CML API.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            response = await self._authenticated_request(
                client,
                "PATCH",
                f"https://{host}/api/v0/labs/{lab_id}/nodes/{node_id}",
                host,
                username,
                password,
                json={"tags": tags},
            )

            data = response.json()
            logger.info(f"Patched tags on node {node_id} in lab {lab_id} on {host}: {tags}")
            return data

    async def get_lab_nodes(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> list[NodeInfo]:
        """Get nodes in a lab.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            List of NodeInfo objects.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            response = await self._authenticated_request(
                client,
                "GET",
                f"https://{host}/api/v0/labs/{lab_id}/nodes",
                host,
                username,
                password,
            )

            # Ensure we have a valid token for per-node detail calls
            token = await self._authenticate(client, host, username, password)

            nodes = []
            for node_id in response.json():
                # Get node details
                node_response = await client.get(
                    f"https://{host}/api/v0/labs/{lab_id}/nodes/{node_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if node_response.status_code == 200:
                    data = node_response.json()
                    nodes.append(
                        NodeInfo(
                            id=node_id,
                            label=data.get("label", ""),
                            node_definition=data.get("node_definition", ""),
                            state=data.get("state", ""),
                            cpu_limit=data.get("cpu_limit"),
                            ram=data.get("ram"),
                            config=data.get("configuration"),
                            x=data.get("x", 0),
                            y=data.get("y", 0),
                            tags=data.get("tags"),
                        )
                    )

            return nodes

    async def get_lab_links(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> list[LinkInfo]:
        """Get links in a lab.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            List of LinkInfo objects.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            response = await self._authenticated_request(
                client,
                "GET",
                f"https://{host}/api/v0/labs/{lab_id}/links",
                host,
                username,
                password,
            )

            # Ensure we have a valid token for per-link detail calls
            token = await self._authenticate(client, host, username, password)

            links = []
            for link_id in response.json():
                # Get link details
                link_response = await client.get(
                    f"https://{host}/api/v0/labs/{lab_id}/links/{link_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if link_response.status_code == 200:
                    data = link_response.json()
                    links.append(
                        LinkInfo(
                            id=link_id,
                            label=data.get("label"),
                            state=data.get("state"),
                            node_a=data.get("node_a"),
                            node_b=data.get("node_b"),
                            interface_a=data.get("interface_a"),
                            interface_b=data.get("interface_b"),
                        )
                    )

            return links

    async def get_lab_simulation_stats(
        self,
        host: str,
        lab_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> SimulationStats | None:
        """Get runtime simulation statistics for a lab.

        CML API: GET /api/v0/labs/{lab_id}/simulation_stats

        Returns per-node CPU consumption and link state.
        Only available when the lab is in BOOTED state.

        ADR-030: Used by ResourceObserver for runtime metrics.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            username: API username.
            password: API password.

        Returns:
            SimulationStats or None if unavailable.
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                response = await self._authenticated_request(
                    client,
                    "GET",
                    f"https://{host}/api/v0/labs/{lab_id}/simulation_stats",
                    host,
                    username,
                    password,
                )
                data = response.json()
                return SimulationStats(
                    lab_id=lab_id,
                    nodes=data.get("nodes", {}),
                    links=data.get("links", {}),
                    raw=data,
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (404, 409):
                    # 404: lab not found; 409: lab not in BOOTED state
                    logger.debug(f"simulation_stats unavailable for lab {lab_id}: {e.response.status_code}")
                    return None
                raise
            except Exception as e:
                logger.warning(f"Failed to get simulation_stats for lab {lab_id} on {host}: {e}")
                return None

    async def get_node_interfaces(
        self,
        host: str,
        lab_id: str,
        node_id: str,
        username: str | None = None,
        password: str | None = None,
    ) -> list[InterfaceInfo]:
        """Get interfaces for a specific node.

        CML API: GET /api/v0/labs/{lab_id}/nodes/{node_id}/interfaces
        then GET /api/v0/labs/{lab_id}/interfaces/{iface_id} for each.

        Returns interface details including IP addresses (only available
        when node is booted).

        ADR-030: Used by ResourceObserver for port observation.

        Args:
            host: CML worker host/IP.
            lab_id: Lab ID.
            node_id: Node ID.
            username: API username.
            password: API password.

        Returns:
            List of InterfaceInfo objects (empty on failure).
        """
        username = username or self._default_username
        password = password or self._default_password

        async with httpx.AsyncClient(
            verify=self._verify_ssl,
            timeout=self._timeout,
        ) as client:
            try:
                response = await self._authenticated_request(
                    client,
                    "GET",
                    f"https://{host}/api/v0/labs/{lab_id}/nodes/{node_id}/interfaces",
                    host,
                    username,
                    password,
                )

                # Ensure we have a valid token for per-interface detail calls
                token = await self._authenticate(client, host, username, password)

                interfaces: list[InterfaceInfo] = []
                # Response is a list of interface IDs
                for iface_id in response.json():
                    iface_response = await client.get(
                        f"https://{host}/api/v0/labs/{lab_id}/interfaces/{iface_id}",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if iface_response.status_code == 200:
                        data = iface_response.json()
                        interfaces.append(
                            InterfaceInfo(
                                id=str(iface_id),
                                label=data.get("label", ""),
                                node_id=node_id,
                                slot=data.get("slot"),
                                state=data.get("state"),
                                mac_address=data.get("mac_address"),
                                ip4=data.get("ip4", []),
                            )
                        )
                return interfaces
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    return []
                raise
            except Exception as e:
                logger.warning(f"Failed to get interfaces for node {node_id} in lab {lab_id}: {e}")
                return []

    def clear_token_cache(self, host: str | None = None) -> None:
        """Clear cached authentication tokens."""
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
        timeout: float = 60.0,
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
