"""Session store for managing user authentication sessions.

Provides both in-memory (development) and Redis (production) session storage.
Each service should use a unique key_prefix to avoid session collisions.
"""

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
    def create_session(self, tokens: dict, user_info: dict) -> str:
        """Create a new session and return session ID."""
        pass

    @abstractmethod
    def get_session(self, session_id: str) -> dict | None:
        """Retrieve session data by session ID."""
        pass

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        pass

    @abstractmethod
    def refresh_session(self, session_id: str, new_tokens: dict) -> None:
        """Update session with new tokens after refresh."""
        pass


class InMemorySessionStore(SessionStore):
    """Simple in-memory session store for development.

    Warning: Sessions are lost on application restart.
    For production, use RedisSessionStore.
    """

    def __init__(self, session_max_duration_minutes: int = 60):
        """Initialize the in-memory session store."""
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


class RedisSessionStore(SessionStore):
    """Redis-based session store for production use.

    Provides stateless, distributed session storage suitable for
    horizontal scaling.
    """

    def __init__(
        self,
        redis_url: str,
        session_max_duration_minutes: int = 480,
        key_prefix: str = "session:",
    ):
        """Initialize the Redis session store."""
        if not REDIS_AVAILABLE:
            raise RuntimeError("redis package is required for RedisSessionStore.")

        self._client = redis.from_url(redis_url, decode_responses=True)
        self._session_timeout_seconds = int(timedelta(minutes=session_max_duration_minutes).total_seconds())
        self._key_prefix = key_prefix

    def _make_key(self, session_id: str) -> str:
        """Create Redis key from session ID."""
        return f"{self._key_prefix}{session_id}"

    def create_session(self, tokens: dict, user_info: dict, session_timeout_seconds: int | None = None) -> str:
        """Create a new session and return session ID.

        Args:
            tokens: Dict containing access_token, refresh_token, id_token, etc.
            user_info: Dict containing user information from OIDC userinfo endpoint
            session_timeout_seconds: Optional custom duration for this session, overriding the store default.

        Returns:
            Session ID string
        """
        session_id = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)

        # Determine the session timeout for this specific session
        current_session_timeout = session_timeout_seconds if session_timeout_seconds is not None else self._session_timeout_seconds

        session_data = {
            "tokens": tokens,
            "user_info": user_info,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=current_session_timeout)).isoformat(),
            "session_timeout_seconds": current_session_timeout,
        }

        key = self._make_key(session_id)
        self._client.setex(key, current_session_timeout, json.dumps(session_data))

        return session_id

    def get_session(self, session_id: str) -> dict | None:
        """Retrieve session data by session ID."""
        key = self._make_key(session_id)
        data = self._client.get(key)

        if not data:
            return None

        session = json.loads(cast(str, data))
        session["created_at"] = datetime.fromisoformat(session["created_at"])
        session["expires_at"] = datetime.fromisoformat(session["expires_at"])

        return session

    def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        key = self._make_key(session_id)
        self._client.delete(key)

    def refresh_session(self, session_id: str, new_tokens: dict, session_timeout_seconds: int | None = None) -> None:
        """Update session with new tokens after refresh.

        Args:
            session_id: The session identifier
            new_tokens: Updated token dict
            session_timeout_seconds: Optional custom duration for this session, overriding the store default.
        """
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
        """Check if Redis connection is healthy."""
        try:
            result = self._client.ping()
            return bool(result) if not isinstance(result, bool) else result
        except Exception:
            return False
