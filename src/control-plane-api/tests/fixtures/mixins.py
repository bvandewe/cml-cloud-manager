"""Test mixins for reusable test patterns.

Provides base classes with common testing utilities for assertions,
async operations, and test patterns.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from unittest.mock import AsyncMock

T = TypeVar("T")


# ============================================================================
# ASYNC TEST MIXINS
# ============================================================================


class AsyncTestMixin:
    """Mixin providing utilities for async tests."""

    @staticmethod
    async def await_with_timeout(coro: Awaitable[T], timeout: float = 5.0, error_msg: str | None = None) -> T:
        """Await a coroutine with timeout."""
        try:
            result: T = await asyncio.wait_for(coro, timeout=timeout)
            return result
        except asyncio.TimeoutError as e:
            msg: str = error_msg or f"Operation timed out after {timeout}s"
            raise AssertionError(msg) from e

    @staticmethod
    async def wait_for_condition(
        condition: Callable[[], bool],
        timeout: float = 5.0,
        poll_interval: float = 0.1,
        error_msg: str | None = None,
    ) -> None:
        """Wait for a condition to become true."""
        loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        start_time: float = loop.time()
        while not condition():
            if loop.time() - start_time > timeout:
                msg: str = error_msg or f"Condition not met within {timeout}s"
                raise AssertionError(msg)
            await asyncio.sleep(poll_interval)


# ============================================================================
# ASSERTION MIXINS
# ============================================================================


class AssertionMixin:
    """Mixin providing custom assertion helpers."""

    @staticmethod
    def assert_dict_contains(actual: dict[str, Any], expected: dict[str, Any]) -> None:
        """Assert actual dict contains all key-value pairs from expected dict."""
        for key, value in expected.items():
            assert key in actual, f"Key '{key}' not found in actual dict"
            assert actual[key] == value, f"Value for key '{key}' doesn't match: {actual[key]} != {value}"

    @staticmethod
    def assert_list_length(actual: list[Any], expected_length: int) -> None:
        """Assert list has expected length with helpful error message."""
        actual_length: int = len(actual)
        assert actual_length == expected_length, f"Expected list length {expected_length}, got {actual_length}"


# ============================================================================
# MOCK HELPER MIXINS
# ============================================================================


class MockHelperMixin:
    """Mixin providing utilities for working with mocks."""

    @staticmethod
    def create_async_mock(return_value: Any = None) -> AsyncMock:
        """Create an AsyncMock with optional return value."""
        mock: AsyncMock = AsyncMock()
        mock.return_value = return_value
        return mock

    @staticmethod
    def assert_mock_called_once_with_partial(mock: AsyncMock, **expected_kwargs: Any) -> None:
        """Assert mock was called once and call args contain expected kwargs."""
        call_count: int = mock.call_count
        assert call_count == 1, f"Expected 1 call, got {call_count}"
        call_kwargs: dict[str, Any] = dict(mock.call_args.kwargs) if mock.call_args else {}
        for key, value in expected_kwargs.items():
            assert key in call_kwargs, f"Expected kwarg '{key}' not found in call args"
            actual_value: Any = call_kwargs[key]
            assert actual_value == value, f"Expected {key}={value}, got {key}={actual_value}"


# ============================================================================
# SESSION TEST MIXIN
# ============================================================================


class SessionTestMixin:
    """Mixin providing utilities for testing session-related functionality."""

    @staticmethod
    def create_test_session(session_store: Any, tokens: dict[str, str], user_info: dict[str, Any]) -> str:
        """Create a test session and return the session ID."""
        session_id: str = session_store.create_session(tokens, user_info)
        return session_id

    @staticmethod
    def assert_session_exists(session_store: Any, session_id: str) -> None:
        """Assert a session exists in the store."""
        session: dict[str, Any] | None = session_store.get_session(session_id)
        assert session is not None, f"Session {session_id} not found"

    @staticmethod
    def assert_session_not_exists(session_store: Any, session_id: str) -> None:
        """Assert a session does not exist in the store."""
        session: dict[str, Any] | None = session_store.get_session(session_id)
        assert session is None, f"Session {session_id} should not exist"


# ============================================================================
# COMBINED TEST BASE
# ============================================================================


class BaseTestCase(
    AsyncTestMixin,
    AssertionMixin,
    MockHelperMixin,
    SessionTestMixin,
):
    """Combined base test class with all mixins.

    Use this as a base class for test classes that need multiple utilities.
    """

    pass
