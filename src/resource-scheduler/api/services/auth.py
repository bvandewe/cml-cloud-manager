"""Authentication service with dual authentication support.

Provides session-based and JWT Bearer token authentication for the Resource Scheduler service.
"""

import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
import jwt
from infrastructure import InMemorySessionStore, RedisSessionStore, SessionStore
from jwt import algorithms
from starlette.responses import Response

if TYPE_CHECKING:
    from fastapi import FastAPI, Request
    from neuroglia.hosting.web import WebApplicationBuilder


@dataclass
class AuthSettings:
    """Authentication settings for DualAuthService.

    Reads from environment variables with sensible defaults.
    """

    # Keycloak - read from environment
    keycloak_url: str = field(default_factory=lambda: os.getenv("KEYCLOAK_URL", "http://localhost:8041"))
    keycloak_url_internal: str | None = field(default_factory=lambda: os.getenv("KEYCLOAK_URL_INTERNAL"))
    keycloak_realm: str = field(default_factory=lambda: os.getenv("KEYCLOAK_REALM", "aix"))
    keycloak_client_id: str = field(default_factory=lambda: os.getenv("KEYCLOAK_CLIENT_ID", "lcm-public"))
    keycloak_client_secret: str = field(default_factory=lambda: os.getenv("KEYCLOAK_CLIENT_SECRET", ""))

    # Token validation
    verify_issuer: bool = True
    expected_issuer: str = ""
    verify_audience: bool = True
    expected_audience: list[str] | None = None

    # Session
    session_max_duration_minutes: int = 120
    refresh_auto_leeway_seconds: int = 60

    # Redis
    redis_enabled: bool = False
    redis_url: str = "redis://redis:6379/0"
    redis_key_prefix: str = "rs_session:"  # Unique prefix for resource-scheduler


class DualAuthService:
    """Service for authentication operations supporting both session and JWT auth."""

    _log = logging.getLogger("AuthService")

    # JWKS cache
    _jwks_cache: dict | None = None
    _jwks_ttl_seconds: int = 3600

    def __init__(self, session_store: SessionStore, settings: AuthSettings | None = None):
        """Initialize auth service with session store."""
        self.session_store = session_store
        self.settings = settings or AuthSettings()

    def _jwks_url(self) -> str:
        """Construct JWKS endpoint URL."""
        base = self.settings.keycloak_url_internal or self.settings.keycloak_url
        return f"{base}/realms/{self.settings.keycloak_realm}/protocol/openid-connect/certs"

    def _fetch_jwks(self) -> dict | None:
        """Fetch JWKS from Keycloak with caching."""
        now = time.time()
        if self._jwks_cache and (now - self._jwks_cache.get("fetched_at", 0) < self._jwks_ttl_seconds):
            return self._jwks_cache
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(self._jwks_url())
                resp.raise_for_status()
                data = resp.json()
                if "keys" in data:
                    self._jwks_cache = {"keys": data["keys"], "fetched_at": now}
                    return self._jwks_cache
        except Exception as e:
            self._log.warning(f"JWKS fetch failed: {e}")
            return None
        return None

    def _get_public_key_for_token(self, token: str) -> Any | None:
        """Resolve RSA public key from JWKS."""
        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception:
            return None
        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg")
        if not kid or alg != "RS256":
            return None
        jwks = self._fetch_jwks()
        if not jwks:
            return None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                try:
                    return algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
                except Exception:
                    return None
        return None

    def get_user_from_session(self, session_id: str) -> dict | None:
        """Get user info from session ID."""
        if not session_id:
            return None
        session = self.session_store.get_session(session_id)
        if session:
            return session.get("user_info")
        return None

    def get_user_from_jwt(self, token: str) -> dict | None:
        """Get user info from JWT token."""
        if not token:
            return None

        public_key = self._get_public_key_for_token(token)
        if public_key:
            try:
                verify_aud = self.settings.verify_audience and bool(self.settings.expected_audience)
                options = {"verify_aud": verify_aud}
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    audience=self.settings.expected_audience if verify_aud else None,
                    options=options,
                )

                if self.settings.verify_issuer and self.settings.expected_issuer:
                    iss = payload.get("iss")
                    if iss != self.settings.expected_issuer:
                        self._log.info(f"Issuer mismatch: got '{iss}', expected '{self.settings.expected_issuer}'")
                        return None

                return self._map_claims(payload)
            except jwt.ExpiredSignatureError:
                self._log.info("Token expired")
            except jwt.InvalidTokenError as e:
                self._log.info(f"Token invalid: {e}")

        return None

    def _map_claims(self, payload: dict) -> dict:
        """Normalize JWT claims to internal user representation."""
        roles: list[Any] = []
        if isinstance(payload.get("realm_access"), dict):
            roles = payload.get("realm_access", {}).get("roles", []) or []
        elif isinstance(payload.get("roles"), list):
            roles = list(payload.get("roles") or [])
        return {
            "sub": payload.get("sub"),
            "username": payload.get("preferred_username") or payload.get("username"),
            "user_id": payload.get("user_id") or payload.get("sub"),
            "email": payload.get("email"),
            "name": payload.get("name") or payload.get("given_name"),
            "roles": roles,
        }

    def authenticate(self, session_id: str | None = None, token: str | None = None) -> dict | None:
        """Authenticate user via session or JWT token."""
        # Try session-based authentication first
        if session_id:
            user = self.get_user_from_session(session_id)
            if user:
                return user

        # Try JWT Bearer token authentication
        if token:
            user = self.get_user_from_jwt(token)
            if user:
                return user

        return None

    @staticmethod
    def configure(builder: "WebApplicationBuilder", settings: AuthSettings | None = None) -> None:
        """Configure authentication services in the application builder."""
        log = logging.getLogger(__name__)
        auth_settings = settings or AuthSettings()

        # Create session store
        session_store: SessionStore
        if auth_settings.redis_enabled:
            log.info(f"🔴 Using RedisSessionStore (url={auth_settings.redis_url})")
            try:
                session_store = RedisSessionStore(
                    redis_url=auth_settings.redis_url,
                    session_max_duration_minutes=auth_settings.session_max_duration_minutes,
                    key_prefix=auth_settings.redis_key_prefix,
                )
                if session_store.ping():
                    log.info("✅ Redis connection successful")
                else:
                    log.warning("⚠️ Redis ping failed - falling back to InMemory")
                    session_store = InMemorySessionStore(session_max_duration_minutes=auth_settings.session_max_duration_minutes)
            except Exception as e:
                log.error(f"❌ Failed to connect to Redis: {e}")
                session_store = InMemorySessionStore(session_max_duration_minutes=auth_settings.session_max_duration_minutes)
        else:
            log.info("💾 Using InMemorySessionStore")
            session_store = InMemorySessionStore(session_max_duration_minutes=auth_settings.session_max_duration_minutes)

        # Register services
        builder.services.add_singleton(SessionStore, singleton=session_store)
        auth_service = DualAuthService(session_store, auth_settings)

        # Pre-warm JWKS cache
        try:
            auth_service._fetch_jwks()
            log.info("🔐 JWKS cache pre-warmed")
        except Exception as e:
            log.debug(f"JWKS pre-warm skipped: {e}")

        builder.services.add_singleton(DualAuthService, singleton=auth_service)

    @staticmethod
    def configure_middleware(app: "FastAPI") -> None:
        """Configure authentication middleware for the FastAPI application."""

        @app.middleware("http")
        async def inject_auth_service(request: "Request", call_next: Callable[["Request"], Awaitable[Response]]) -> Response:
            """Inject AuthService into request state."""
            request.state.auth_service = app.state.services.get_required_service(DualAuthService)
            response = await call_next(request)
            return response
