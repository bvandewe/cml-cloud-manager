"""Test data factories and builders.

Provides reusable factory classes for creating test data with sensible defaults
and easy customization.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

# ============================================================================
# TOKEN FACTORY
# ============================================================================


class TokenFactory:
    """Factory for creating JWT tokens and auth-related test data."""

    @staticmethod
    def create_tokens(
        access_token: str | None = None,
        refresh_token: str | None = None,
        id_token: str | None = None,
    ) -> dict[str, str]:
        """Create a tokens dictionary."""
        tokens: dict[str, str] = {
            "access_token": access_token or "test_access_token",
            "refresh_token": refresh_token or "test_refresh_token",
            "id_token": id_token or "test_id_token",
        }
        return tokens

    @staticmethod
    def create_user_info(
        sub: str | None = None,
        email: str | None = None,
        name: str | None = None,
        roles: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create user info dictionary."""
        user_info: dict[str, Any] = {
            "sub": sub or str(uuid4()),
            "email": email or "test@example.com",
            "name": name or "Test User",
            "roles": roles or ["user"],
            **kwargs,
        }
        return user_info

    @staticmethod
    def create_jwt_claims(
        sub: str | None = None,
        username: str | None = None,
        roles: list[str] | None = None,
        exp_minutes: int = 15,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create JWT claims dictionary."""
        now: datetime = datetime.now(timezone.utc)
        claims: dict[str, Any] = {
            "sub": sub or str(uuid4()),
            "username": username or "testuser",
            "roles": roles or ["user"],
            "exp": now + timedelta(minutes=exp_minutes),
            "iat": now,
            **kwargs,
        }
        return claims


# ============================================================================
# SESSION FACTORY
# ============================================================================


class SessionFactory:
    """Factory for creating session data."""

    @staticmethod
    def create_session_data(
        tokens: dict[str, str] | None = None,
        user_info: dict[str, Any] | None = None,
    ) -> tuple[dict[str, str], dict[str, Any]]:
        """Create tokens and user_info for a session."""
        session_tokens: dict[str, str] = tokens or TokenFactory.create_tokens()
        session_user_info: dict[str, Any] = user_info or TokenFactory.create_user_info()
        return (session_tokens, session_user_info)
