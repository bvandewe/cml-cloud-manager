"""Environment Resolver client for resolving FQN to service base URLs.

Calls the Environment Resolver service to get environment-specific URLs
(Mosaic base URL, LDS base URL, etc.) for a given form_qualified_name.

The Environment Resolver is the single source of truth for service discovery
in the Cisco certification platform ecosystem.

Authentication: Optional OAuth2 client credentials via Keycloak.
"""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from integration.services.oauth2_token_manager import OAuth2TokenManager, TokenConfig

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection
    from neuroglia.dependency_injection.service_provider import ServiceProviderBase

logger = logging.getLogger(__name__)


class EnvironmentResolverError(Exception):
    """Error from the Environment Resolver service."""

    def __init__(self, message: str, status_code: int | None = None, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


@dataclass
class ResolvedEnvironment:
    """Resolved environment URLs from the Environment Resolver service.

    Contains service base URLs resolved for a specific form_qualified_name
    and environment (e.g., CERTS-DEV, CERTS-PROD).
    """

    mosaic_base_url: str
    lds_base_url: str | None = None
    minio_base_url: str | None = None
    mozart_base_url: str | None = None
    grading_engine_base_url: str | None = None
    variables_generator_base_url: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)  # Full response for extensibility


class EnvironmentResolverClient:
    """Client for the Environment Resolver service.

    Resolves a form_qualified_name to environment-specific service URLs.
    Used by ContentSyncService to determine where to download content
    (Mosaic) and where to notify (LDS, Grading Engine).

    Configuration:
        ENVIRONMENT_RESOLVER_URL: Service base URL
        ENVIRONMENT_RESOLVER_ENVIRONMENT: Default environment (e.g., CERTS-DEV)
        ENVIRONMENT_RESOLVER_TOKEN_URL: Optional OAuth2 token endpoint
        ENVIRONMENT_RESOLVER_CLIENT_ID: Optional OAuth2 client ID
        ENVIRONMENT_RESOLVER_CLIENT_SECRET: Optional OAuth2 client secret
    """

    def __init__(
        self,
        base_url: str,
        default_environment: str = "CERTS-DEV",
        token_manager: OAuth2TokenManager | None = None,
    ) -> None:
        """Initialize the Environment Resolver client.

        Args:
            base_url: Environment Resolver service base URL.
            default_environment: Default environment name for resolution.
            token_manager: Optional OAuth2 token manager for authentication.
        """
        self._base_url = base_url.rstrip("/")
        self._default_environment = default_environment
        self._token_manager = token_manager
        self._http = httpx.AsyncClient(verify=False, timeout=30.0)

    async def resolve(
        self,
        qualified_name: str,
        environment: str | None = None,
    ) -> ResolvedEnvironment:
        """Resolve a form qualified name to environment-specific URLs.

        Calls: POST {base_url}/resolve
        Body: {"qualifiedName": "...", "environment": "..."}

        Args:
            qualified_name: The form qualified name from the LabletDefinition.
            environment: Override environment (default: configured default).

        Returns:
            ResolvedEnvironment with parsed URLs.

        Raises:
            EnvironmentResolverError: On non-2xx response or missing data.
        """
        env = environment or self._default_environment
        headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}

        if self._token_manager:
            auth_headers = await self._token_manager.get_auth_headers()
            headers.update(auth_headers)

        payload = {
            "qualifiedName": qualified_name,
            "environment": env,
        }

        logger.info(f"Resolving environment for FQN='{qualified_name}' env='{env}'")

        try:
            response = await self._http.post(
                f"{self._base_url}/resolve",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise EnvironmentResolverError(
                f"Environment resolution failed for FQN='{qualified_name}': {e.response.status_code}",
                status_code=e.response.status_code,
            ) from e

        data = response.json()

        mosaic_url = data.get("MOSAIC_BASE_URL", "").rstrip("/")
        if not mosaic_url:
            raise EnvironmentResolverError(f"No MOSAIC_BASE_URL resolved for FQN='{qualified_name}' env='{env}'")

        result = ResolvedEnvironment(
            mosaic_base_url=mosaic_url,
            lds_base_url=data.get("PYLDS_BASE_URL"),
            minio_base_url=data.get("MINIO_BASE_URL"),
            mozart_base_url=data.get("MOZART_BASE_URL"),
            grading_engine_base_url=data.get("GRADING_ENGINE_BASE_URL"),
            variables_generator_base_url=data.get("VARIABLES_GENERATOR_BASE_URL"),
            raw_response=data,
        )

        logger.info(f"Resolved: mosaic={result.mosaic_base_url}, lds={result.lds_base_url}")
        return result

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
        if self._token_manager:
            await self._token_manager.close()

    # =========================================================================
    # DI Configuration
    # =========================================================================

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        base_url: str,
        default_environment: str = "CERTS-DEV",
        token_config: TokenConfig | None = None,
    ) -> None:
        """Register EnvironmentResolverClient as singleton in DI container.

        Args:
            services: Neuroglia service collection.
            base_url: Environment Resolver service base URL.
            default_environment: Default environment name.
            token_config: Optional OAuth2 client credentials config.
        """

        def factory(sp: "ServiceProviderBase") -> "EnvironmentResolverClient":
            token_manager = None
            if token_config and token_config.token_url:
                token_manager = OAuth2TokenManager(token_config)
            return cls(
                base_url=base_url,
                default_environment=default_environment,
                token_manager=token_manager,
            )

        services.add_singleton(cls, implementation_type=cls, implementation_factory=factory)
        logger.info(f"✅ EnvironmentResolverClient configured (url={base_url}, env={default_environment})")
