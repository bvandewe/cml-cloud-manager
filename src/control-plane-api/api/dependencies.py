"""FastAPI dependencies for authentication.

Note: These dependencies bridge FastAPI's dependency injection with Neuroglia's DI container.
Since FastAPI dependencies can't directly access the service provider, we retrieve the
AuthService from the request state, which is injected by middleware.

Enhancements:
- Explicit 401 feedback for expired bearer tokens (helps clients refresh/re-authorize).
- Adds RFC6750-compliant `WWW-Authenticate` header with error details.
"""

import time

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.services import DualAuthService

# Optional bearer token (won't raise error if missing)
security_optional = HTTPBearer(auto_error=False, scheme_name="oauth2")


def get_auth_service(request: Request) -> DualAuthService:
    """Get AuthService from request state (injected by middleware).

    Args:
        request: FastAPI request object with state

    Returns:
        AuthService instance from Neuroglia DI container

    Raises:
        RuntimeError: If AuthService not found in request state
    """
    auth_service = getattr(request.state, "auth_service", None)
    if auth_service is None:
        raise RuntimeError("AuthService not found in request state. Ensure DI middleware is properly configured.")
    return auth_service


async def get_current_user(
    request: Request,
    session_id: str | None = Cookie(None),
    credentials: HTTPAuthorizationCredentials | None = Security(security_optional),
) -> dict:
    """Get current user from either session cookie OR JWT Bearer token.

    Supports dual authentication modes:
    1. Session-based (OAuth2) - for browser/UI clients
    2. JWT Bearer token - for API/3rd party clients

    Args:
        request: FastAPI request object
        session_id: Session ID from cookie (OAuth2 flow)
        credentials: JWT Bearer token from Authorization header

    Returns:
        User information dictionary with roles

    Raises:
        HTTPException: 401 if not authenticated via either method
    """
    auth_service = get_auth_service(request)

    # Extract token from credentials if present
    token = credentials.credentials if credentials else None

    # Pre-check bearer token expiry to provide clearer error feedback (Swagger tokens are not auto-refreshed)
    decode_failed = False
    if token:
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
            raise  # re-raise our explicit expired error
        except (jwt.PyJWTError, ValueError, TypeError):
            decode_failed = True

    if decode_failed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token format.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Malformed token"'},
        )

    # Authenticate via session or JWT (session auto-refresh logic handled in AuthService)
    user = auth_service.authenticate(session_id=session_id, token=token)

    if user is None:
        # Distinguish missing vs invalid token for better client hints
        if token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired bearer token.",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Invalid or expired token"'},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Provide either session cookie or Bearer token.",
            headers={"WWW-Authenticate": 'Bearer realm="lablet-cloud-manager"'},
        )

    return user


def require_roles(*required_roles: str):
    """Dependency factory to require specific roles.

    Usage:
        @get("/admin")
        async def admin_endpoint(user: dict = Depends(require_roles("admin"))):
            ...

    Args:
        *required_roles: One or more role names required

    Returns:
        FastAPI dependency function that checks roles
    """

    async def role_checker(user: dict = Depends(get_current_user)) -> dict:
        user_roles = user.get("roles", [])
        if not any(role in user_roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(required_roles)}",
            )
        return user

    return role_checker
