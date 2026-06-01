"""Authentication API controller with OAuth2/OIDC flow."""

import logging
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode

import jwt
from classy_fastapi.decorators import get, post
from fastapi import Cookie, HTTPException, status
from fastapi.responses import RedirectResponse
from keycloak import KeycloakOpenID
from keycloak.exceptions import KeycloakConnectionError
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase

from application.settings import app_settings
from domain.events import UserLoggedInDomainEvent
from infrastructure import SessionStore

logger = logging.getLogger(__name__)


class AuthController(ControllerBase):
    """Portable Controller for OAuth2/OIDC authentication with Keycloak.

    Flow:
    1. User clicks login → GET /api/auth/login → Redirect to Keycloak
    2. User enters credentials at Keycloak
    3. Keycloak redirects → GET /api/auth/callback?code=xxx
    4. Backend exchanges code for tokens
    5. Backend creates session, sets httpOnly cookie
    6. User accesses app with cookie automatically sent
    """

    def __init__(self, service_provider: ServiceProviderBase, mapper: Mapper, mediator: Mediator):
        super().__init__(service_provider, mapper, mediator)

        # Initialize Keycloak client with CONFIDENTIAL backend client
        # This client has client_secret for secure token exchange
        self.keycloak = KeycloakOpenID(
            server_url=app_settings.keycloak_url_internal,
            client_id=app_settings.keycloak_client_id,
            realm_name=app_settings.keycloak_realm,
            client_secret_key=app_settings.keycloak_client_secret,
        )

        # Get session store from DI container as Controllers cant define additional dependencies
        session_store = service_provider.get_service(SessionStore)
        if session_store is None:
            raise RuntimeError("SessionStore not found in service provider")
        self.session_store: SessionStore = session_store

    @get("/login")
    async def login(self):
        """Initiate OAuth2 login - redirect user to Keycloak login page.

        Returns:
            Redirect to Keycloak authorization endpoint, or
            Redirect to home with error parameter if Keycloak is unavailable
        """
        try:
            # Generate state parameter for CSRF protection
            state = secrets.token_urlsafe(16)

            # Build Keycloak authorization URL
            # Note: Request roles scope to include user roles in token/userinfo
            auth_url = self.keycloak.auth_url(
                redirect_uri=f"{app_settings.app_url}/api/auth/callback",
                scope="openid profile email roles",
                state=state,
            )

            return RedirectResponse(url=auth_url)
        except KeycloakConnectionError as e:
            # Keycloak is unavailable - redirect to home with error parameter
            logger.error(f"Keycloak connection error during login: {e}")
            error_params = urlencode({"auth_error": "keycloak_unavailable"})
            return RedirectResponse(url=f"/?{error_params}", status_code=status.HTTP_303_SEE_OTHER)

    @get("/callback")
    async def callback(self, code: str, state: str):
        """Handle OAuth2 callback from Keycloak.

        Args:
            code: Authorization code from Keycloak
            state: CSRF protection token

        Returns:
            Redirect to application home page with session cookie set
        """
        try:
            # Exchange authorization code for tokens
            tokens = self.keycloak.token(
                grant_type="authorization_code",
                code=code,
                redirect_uri=f"{app_settings.app_url}/api/auth/callback",
            )

            # Get user information using access token
            user_info = self.keycloak.userinfo(tokens["access_token"])

            # Extract roles from access token
            # Note: Keycloak includes roles in access token's realm_access claim,
            # but userinfo endpoint may not return them by default
            try:
                # Decode access token to extract realm roles (already validated by Keycloak)
                access_token_decoded = jwt.decode(tokens["access_token"], options={"verify_signature": False})

                # Get realm roles from token
                realm_roles = access_token_decoded.get("realm_access", {}).get("roles", [])

                # Add roles to user_info if present in token
                if realm_roles:
                    # Filter out default Keycloak roles (offline_access, uma_authorization)
                    user_roles = [
                        role
                        for role in realm_roles
                        if role
                        not in [
                            "offline_access",
                            "uma_authorization",
                            "default-roles-lablet-cloud-manager",
                        ]
                    ]
                    user_info["roles"] = user_roles

            except Exception as e:
                # Log error but continue - roles are optional for basic authentication
                print(f"Warning: Could not extract roles from access token: {e}")

            # Extract dynamic expiry from tokens if available
            refresh_expires_in = tokens.get("refresh_expires_in")
            session_timeout_seconds = int(refresh_expires_in) if refresh_expires_in is not None else app_settings.session_max_duration_minutes * 60

            # Create server-side session
            session_id = self.session_store.create_session(tokens, user_info, session_timeout_seconds)
            aggregate_id = str(user_info.get("sub") or user_info.get("user_id") or user_info.get("preferred_username") or session_id)
            if self.mediator:
                await self.mediator.publish_async(
                    UserLoggedInDomainEvent(
                        aggregate_id=aggregate_id,
                        username=user_info.get("preferred_username") or "unknown",
                        login_at=datetime.now(),
                    )
                )
            # Create redirect response
            redirect = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

            # Set httpOnly cookie on the redirect response
            redirect.set_cookie(
                key="session_id",
                value=session_id,
                httponly=True,
                secure=app_settings.environment == "production",
                samesite="lax",
                max_age=session_timeout_seconds,
                path="/",
            )

            return redirect

        except Exception as e:
            # Log error and redirect to login
            print(f"OAuth2 callback error: {e}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed")

    @get("/session")
    async def get_session_info(self, session_id: str | None = Cookie(None)):
        """Get session information including expiration time.

        Returns:
            Dict with session info: { "authenticated": bool, "expires_at": str|null, "expires_in_seconds": int|null }
        """
        if not session_id:
            return {
                "authenticated": False,
                "expires_at": None,
                "expires_in_seconds": None,
            }

        session = self.session_store.get_session(session_id)
        if not session:
            return {
                "authenticated": False,
                "expires_at": None,
                "expires_in_seconds": None,
            }

        expires_at = session.get("expires_at")
        if expires_at:
            now = datetime.now(timezone.utc)
            # Ensure expires_at is datetime object
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            elif not expires_at.tzinfo:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            expires_in_seconds = int((expires_at - now).total_seconds())
            session_timeout = session.get("session_timeout_seconds", app_settings.session_max_duration_minutes * 60)
            return {
                "authenticated": True,
                "expires_at": expires_at.isoformat(),
                "expires_in_seconds": max(0, expires_in_seconds),
                "session_idle_timeout_minutes": session_timeout // 60,
                "session_expiration_warning_minutes": app_settings.session_expiration_warning_minutes,
                # Deprecated: use session_idle_timeout_minutes instead
                "session_max_duration_minutes": session_timeout // 60,
            }

        return {
            "authenticated": True,
            "expires_at": None,
            "expires_in_seconds": None,
            "session_idle_timeout_minutes": app_settings.sso_session_idle_timeout_minutes,
            "session_expiration_warning_minutes": app_settings.session_expiration_warning_minutes,
            # Deprecated: use session_idle_timeout_minutes instead
            "session_max_duration_minutes": app_settings.sso_session_idle_timeout_minutes,
        }

    @post("/refresh")
    async def refresh(self, session_id: str | None = Cookie(None)):
        """Refresh session tokens using Keycloak refresh token.

        Returns new access/id tokens and updates the session store.
        """
        if not session_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing session cookie",
            )
        session = self.session_store.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session",
            )
        session_tokens = session.get("tokens", {})
        refresh_token = session_tokens.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No refresh token available",
            )
        try:
            new_tokens = self.keycloak.refresh_token(refresh_token)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Refresh failed: {e}")

        if "refresh_token" not in new_tokens:
            new_tokens["refresh_token"] = refresh_token
        if "id_token" not in new_tokens and session_tokens.get("id_token"):
            new_tokens["id_token"] = session_tokens.get("id_token")

        refresh_expires_in = new_tokens.get("refresh_expires_in")
        session_timeout_seconds = int(refresh_expires_in) if refresh_expires_in is not None else None

        self.session_store.refresh_session(session_id, new_tokens, session_timeout_seconds)
        return {
            "access_token": new_tokens.get("access_token"),
            "id_token": new_tokens.get("id_token"),
        }

    @get("/logout")
    async def logout(self, session_id: str | None = Cookie(None)):
        """Logout user - clear session and redirect to Keycloak logout.

        Args:
            session_id: Current session ID from cookie

        Returns:
            Redirect to Keycloak logout endpoint
        """
        id_token = None
        refresh_token = None

        # Get id_token from session if available
        if session_id:
            session = self.session_store.get_session(session_id)
            if session:
                tokens = session.get("tokens", {})
                id_token = tokens.get("id_token")
                refresh_token = tokens.get("refresh_token")
            # Delete server-side session
            self.session_store.delete_session(session_id)

        params = {
            "post_logout_redirect_uri": f"{app_settings.app_url}/",
            "client_id": app_settings.keycloak_client_id,
        }
        if id_token:
            params["id_token_hint"] = id_token
        elif refresh_token:
            params["refresh_token"] = refresh_token

        # Build Keycloak logout URL with encoded parameters
        logout_url = f"{app_settings.keycloak_url}/realms/{app_settings.keycloak_realm}/protocol/openid-connect/logout?{urlencode(params)}"

        # Create redirect and clear cookie
        redirect = RedirectResponse(url=logout_url, status_code=status.HTTP_303_SEE_OTHER)
        redirect.delete_cookie("session_id", path="/")

        return redirect

    @get("/user")
    async def get_current_user(self, session_id: str | None = Cookie(None)):
        """Get current authenticated user information.

        Args:
            session_id: Session ID from cookie

        Returns:
            User information from Keycloak

        Raises:
            HTTPException: 401 if not authenticated or session expired
        """
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        # Retrieve session
        session = self.session_store.get_session(session_id)

        if not session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

        # Return user info (never expose tokens to browser)
        return session["user_info"]

    @get("/check-admin")
    async def check_admin(self, session_id: str | None = Cookie(None)):
        """Check if current user has admin role.

        Used by Nginx auth_request.
        """
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

        session = self.session_store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

        user_info = session.get("user_info", {})
        roles = user_info.get("roles", [])

        if "admin" not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")

        return {"status": "ok"}

    @post("/extend-session")
    async def extend_session(self, session_id: str = Cookie(None)) -> dict:
        """Extend the current session by refreshing Keycloak tokens.

        This performs a real token refresh with Keycloak, which:
        - Issues a new access token (resets accessTokenLifespan)
        - Issues a new refresh token (resets ssoSessionIdleTimeout)
        - Resets Keycloak's SSO idle timeout counter

        The session expiry is always derived from Keycloak's refresh_expires_in.
        """
        if not session_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No session")

        session = self.session_store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

        # Get refresh token from session
        session_tokens = session.get("tokens", {})
        refresh_token = session_tokens.get("refresh_token")
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No refresh token available — please log in again",
            )

        try:
            new_tokens = self.keycloak.refresh_token(refresh_token)
        except Exception as e:
            logger.warning(f"Extend-session token refresh failed: {e}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Token refresh failed: {e}")

        # Preserve tokens that Keycloak may not re-issue
        if "refresh_token" not in new_tokens:
            new_tokens["refresh_token"] = refresh_token
        if "id_token" not in new_tokens and session_tokens.get("id_token"):
            new_tokens["id_token"] = session_tokens.get("id_token")

        # Derive session timeout from Keycloak's refresh_expires_in (= ssoSessionIdleTimeout)
        refresh_expires_in = new_tokens.get("refresh_expires_in")
        session_timeout_seconds = int(refresh_expires_in) if refresh_expires_in is not None else None

        self.session_store.refresh_session(session_id, new_tokens, session_timeout_seconds)

        # Return updated expiry info so frontend can update its state
        updated_session = self.session_store.get_session(session_id)
        expires_at = updated_session.get("expires_at") if updated_session else None
        expires_in = None
        if expires_at:
            now = datetime.now(timezone.utc)
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            elif not expires_at.tzinfo:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expires_in = max(0, int((expires_at - now).total_seconds()))

        return {
            "message": "Session extended",
            "expires_in_seconds": expires_in,
            "session_expiration_warning_minutes": app_settings.session_expiration_warning_minutes,
        }
