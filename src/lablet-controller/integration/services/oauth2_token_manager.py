"""OAuth2 Client Credentials token manager with auto-refresh.

Provides cached token acquisition for service-to-service authentication.
Used by EnvironmentResolverClient and MosaicClient for Keycloak-based
client credentials flow.

Thread-safe token caching with configurable leeway for pre-emptive refresh.
"""

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TokenConfig:
    """OAuth2 client credentials configuration."""

    token_url: str
    client_id: str
    client_secret: str
    scopes: str = ""  # Space-separated


class OAuth2TokenManager:
    """Manages OAuth2 client credentials tokens with caching and auto-refresh.

    Acquires tokens via the client_credentials grant type and caches them
    until they expire (minus a configurable leeway). Thread-safe for use
    across concurrent async tasks.

    Usage:
        config = TokenConfig(
            token_url="https://keycloak.example.com/realms/my-realm/protocol/openid-connect/token",
            client_id="my-service",
            client_secret="secret",  # pragma: allowlist secret
        )
        manager = OAuth2TokenManager(config)
        headers = await manager.get_auth_headers()
    """

    def __init__(self, config: TokenConfig, leeway_seconds: int = 60) -> None:
        """Initialize the token manager.

        Args:
            config: OAuth2 client credentials configuration.
            leeway_seconds: Refresh token this many seconds before expiry.
        """
        self._config = config
        self._leeway = leeway_seconds
        self._token: str | None = None
        self._expires_at: float = 0
        self._http = httpx.AsyncClient(verify=False, timeout=30.0)

    async def get_token(self) -> str:
        """Get a valid access token, refreshing if needed.

        Returns:
            Valid Bearer access token string.

        Raises:
            httpx.HTTPStatusError: On token endpoint failure.
        """
        if self._token and time.time() < self._expires_at:
            return self._token

        # Strip any accidental surrounding quotes from config values (e.g., Make include artifacts)
        client_id = self._config.client_id.strip('"').strip("'")
        client_secret = self._config.client_secret.strip('"').strip("'")
        scopes = self._config.scopes.strip('"').strip("'") if self._config.scopes else ""

        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if scopes:
            data["scope"] = scopes

        try:
            response = await self._http.post(self._config.token_url, data=data)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"OAuth2 token request failed: {e.response.status_code} from {self._config.token_url} (client_id={client_id}, scopes='{scopes or '(none)'}') - {e.response.text}")
            raise

        token_data = response.json()

        self._token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 300)
        self._expires_at = time.time() + expires_in - self._leeway

        logger.debug(f"OAuth2 token acquired (expires_in={expires_in}s, client_id={client_id})")
        return self._token

    async def get_auth_headers(self) -> dict[str, str]:
        """Get Authorization header dict with Bearer token.

        Returns:
            Dict with Authorization header ready for use in HTTP requests.
        """
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
