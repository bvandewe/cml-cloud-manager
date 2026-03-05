"""FastAPI dependencies for authentication.

Provides authentication dependencies for admin endpoints.
Uses DualAuthService for JWT validation via Keycloak.
"""

import logging
import time

import jwt
from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.services import DualAuthService

logger = logging.getLogger(__name__)

# Optional bearer token (won't raise error if missing)
security_optional = HTTPBearer(auto_error=False, scheme_name="oauth2")


def get_auth_service(request: Request) -> DualAuthService:
    """Get AuthService from request state (injected by middleware).

    Args:
        request: FastAPI request object with state

    Returns:
        DualAuthService instance

    Raises:
        RuntimeError: If AuthService not found in request state
    """
    auth_service = getattr(request.state, "auth_service", None)
    if auth_service is None:
        raise RuntimeError("AuthService not found in request state. Ensure DualAuthService.configure_middleware is called.")
    return auth_service


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security_optional),
) -> dict:
    """Get current user from JWT Bearer token.

    Args:
        request: FastAPI request object
        credentials: JWT Bearer token from Authorization header

    Returns:
        User information dictionary with roles

    Raises:
        HTTPException: 401 if not authenticated
    """
    auth_service = get_auth_service(request)
    token = credentials.credentials if credentials else None

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization required. Provide Bearer token.",
            headers={"WWW-Authenticate": 'Bearer realm="worker-controller"'},
        )

    # Check token expiry for clear error feedback
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        exp = unverified.get("exp")
        if isinstance(exp, int) and exp < int(time.time()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token expired. Re-authorize to obtain a new access token.",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="The access token expired"'},
            )
    except HTTPException:
        raise
    except (jwt.PyJWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token format.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Malformed token"'},
        )

    # Validate token via DualAuthService
    user = auth_service.get_user_from_jwt(token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired bearer token.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Invalid or expired token"'},
        )

    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Require user to have admin role.

    Args:
        user: Authenticated user from get_current_user

    Returns:
        User dictionary if admin

    Raises:
        HTTPException: 403 if user is not an admin
    """
    user_roles = user.get("roles", [])
    admin_roles = ["admin", "lcm-admin", "realm-admin"]

    if not any(role in user_roles for role in admin_roles):
        logger.warning(f"Access denied for user {user.get('username')}: missing admin role")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Admin role required. User roles: {user_roles}",
        )

    return user
