"""Session store for managing user authentication sessions."""

import json
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import cast

try:
    import redis  # type: ignore[import]

    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False


class SessionStore(ABC):
    """Abstract base class for session storage."""

    @abstractmethod
    def create_session(self, tokens: dict, user_info: dict, session_timeout_seconds: int | None = None) -> str:
        """Create a new session and return session ID.

        Args:
            tokens: Dict containing access_token, refresh_token, id_token, etc.
            user_info: Dict containing user information from OIDC userinfo endpoint
            session_timeout_seconds: Optional custom duration for this session, overriding the store default.

        Returns:
            Session ID string
        """
        pass

    @abstractmethod
    def get_session(self, session_id: str) -> dict | None:
        """Retrieve session data by session ID.

        Args:
            session_id: The session identifier

        Returns:
            Dict with 'tokens' and 'user_info' keys, or None if not found/expired
        """
        pass

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """Delete a session.

        Args:
            session_id: The session identifier to delete
        """
        pass

    @abstractmethod
    def refresh_session(self, session_id: str, new_tokens: dict, session_timeout_seconds: int | None = None) -> None:
        """Update session with new tokens after refresh.

        Args:
            session_id: The session identifier
            new_tokens: Updated token dict
            session_timeout_seconds: Optional custom duration for this session, overriding the store default.
        """
        pass


class InMemorySessionStore(SessionStore):
    """Simple in-memory session store for development.

    Warning: Sessions are lost on application restart.
    For production, use RedisSessionStore or similar.
    """

    def __init__(self, session_max_duration_minutes: int = 60):
        """Initialize the in-memory session store.

        Args:
            session_max_duration_minutes: How long sessions remain valid in minutes (default: 60 minutes / 1 hour)
        """
        self._sessions: dict[str, dict] = {}
        self._session_timeout = timedelta(minutes=session_max_duration_minutes)

    def create_session(self, tokens: dict, user_info: dict, session_timeout_seconds: int | None = None) -> str:
        """Create a new session and return session ID."""
        session_id = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)

        timeout = timedelta(seconds=session_timeout_seconds) if session_timeout_seconds is not None else self._session_timeout

        self._sessions[session_id] = {
            "tokens": tokens,
            "user_info": user_info,
            "created_at": now,
            "expires_at": now + timeout,
            "session_timeout_seconds": session_timeout_seconds or int(self._session_timeout.total_seconds()),
        }

        return session_id

    def get_session(self, session_id: str) -> dict | None:
        """Retrieve session data by session ID."""
        session = self._sessions.get(session_id)

        if not session:
            return None

        # Check if session expired
        if session["expires_at"] < datetime.now(timezone.utc):
            # Clean up expired session
            self.delete_session(session_id)
            return None

        return session

    def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        self._sessions.pop(session_id, None)

    def refresh_session(self, session_id: str, new_tokens: dict, session_timeout_seconds: int | None = None) -> None:
        """Update session with new tokens after refresh."""
        session = self._sessions.get(session_id)

        if session:
            existing_tokens = session.get("tokens", {})
            merged_tokens = dict(existing_tokens)
            merged_tokens.update(new_tokens)
            session["tokens"] = merged_tokens
            if session_timeout_seconds is not None:
                session["session_timeout_seconds"] = session_timeout_seconds
            timeout = timedelta(seconds=session.get("session_timeout_seconds", int(self._session_timeout.total_seconds())))
            # Extend expiration time
            session["expires_at"] = datetime.now(timezone.utc) + timeout

    def cleanup_expired_sessions(self) -> int:
        """Remove all expired sessions (optional maintenance method).

        Returns:
            Number of sessions cleaned up
        """
        now = datetime.now(timezone.utc)
        expired = [sid for sid, session in self._sessions.items() if session["expires_at"] < now]

        for sid in expired:
            self.delete_session(sid)

        return len(expired)


class RedisSessionStore(SessionStore):
    """Redis-based session store for production use.

    Provides stateless, distributed session storage suitable for
    horizontal scaling in Kubernetes and other orchestration platforms.
    Sessions are automatically expired by Redis using TTL.
    """

    def __init__(
        self,
        redis_url: str,
        session_max_duration_minutes: int = 480,
        key_prefix: str = "session:",
    ):
        """Initialize the Redis session store.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
            session_max_duration_minutes: How long sessions remain valid in minutes (default: 480 minutes / 8 hours)
            key_prefix: Prefix for all session keys in Redis (default: "session:")

        Raises:
            RuntimeError: If redis package is not installed
        """
        if not REDIS_AVAILABLE:
            raise RuntimeError("redis package is required for RedisSessionStore. Install with: pip install redis")

        self._client = redis.from_url(redis_url, decode_responses=True)  # type: ignore[union-attr]
        self._session_timeout_seconds = int(timedelta(minutes=session_max_duration_minutes).total_seconds())
        self._key_prefix = key_prefix

    def _make_key(self, session_id: str) -> str:
        """Create Redis key from session ID."""
        return f"{self._key_prefix}{session_id}"

    def create_session(self, tokens: dict, user_info: dict, session_timeout_seconds: int | None = None) -> str:
        """Create a new session and return session ID."""
        session_id = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)

        timeout_seconds = session_timeout_seconds if session_timeout_seconds is not None else self._session_timeout_seconds

        session_data = {
            "tokens": tokens,
            "user_info": user_info,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=timeout_seconds)).isoformat(),
            "session_timeout_seconds": timeout_seconds,
        }

        # Store session in Redis with automatic expiration
        key = self._make_key(session_id)
        self._client.setex(key, timeout_seconds, json.dumps(session_data))

        return session_id

    def get_session(self, session_id: str) -> dict | None:
        """Retrieve session data by session ID."""
        key = self._make_key(session_id)
        data = self._client.get(key)

        if not data:
            return None

        session = json.loads(cast(str, data))

        # Convert ISO format strings back to datetime objects
        session["created_at"] = datetime.fromisoformat(session["created_at"])
        session["expires_at"] = datetime.fromisoformat(session["expires_at"])

        return session

    def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        key = self._make_key(session_id)
        self._client.delete(key)

    def refresh_session(self, session_id: str, new_tokens: dict, session_timeout_seconds: int | None = None) -> None:
        """Update session with new tokens after refresh."""
        # Get existing session
        session = self.get_session(session_id)

        if not session:
            return

        existing_tokens = session.get("tokens", {})
        merged_tokens = dict(existing_tokens)
        merged_tokens.update(new_tokens)
        session["tokens"] = merged_tokens

        if session_timeout_seconds is not None:
            session["session_timeout_seconds"] = session_timeout_seconds

        timeout_seconds = session.get("session_timeout_seconds", self._session_timeout_seconds)

        # Extend expiration time
        now = datetime.now(timezone.utc)
        session["expires_at"] = now + timedelta(seconds=timeout_seconds)

        # Convert datetime objects to ISO format for JSON serialization
        session_data = {
            "tokens": session["tokens"],
            "user_info": session["user_info"],
            "created_at": session["created_at"].isoformat(),
            "expires_at": session["expires_at"].isoformat(),
            "session_timeout_seconds": timeout_seconds,
        }

        # Store updated session with renewed TTL
        key = self._make_key(session_id)
        self._client.setex(key, timeout_seconds, json.dumps(session_data))

    def ping(self) -> bool:
        """Check if Redis connection is healthy.

        Returns:
            True if Redis is responding, False otherwise
        """
        try:
            result = self._client.ping()
            return bool(result) if not isinstance(result, bool) else result
        except Exception:
            return False
