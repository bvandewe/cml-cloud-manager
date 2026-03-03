"""Pytest configuration and shared fixtures for all tests.

This module provides:
- Test configuration and markers
- Shared fixtures for core components (session stores, auth services)
- Database and service mocks
- Test data factories
"""

import asyncio
import os
import sys
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from _pytest.config import Config
from motor.core import AgnosticDatabase
from motor.motor_asyncio import AsyncIOMotorClient

# Add src to Python path for imports
src_path: Path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Import after path setup
from api.services.auth import DualAuthService  # noqa: E402
from application.settings import app_settings  # noqa: E402
from infrastructure import InMemorySessionStore, SessionStore  # noqa: E402

# ============================================================================
# PYTEST CONFIGURATION
# ============================================================================


def pytest_configure(config: Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, no external dependencies)")
    config.addinivalue_line("markers", "integration: Integration tests (may use external services)")
    config.addinivalue_line("markers", "slow: Slow tests (may take several seconds)")
    config.addinivalue_line("markers", "asyncio: Async tests")
    config.addinivalue_line("markers", "auth: Authentication/authorization tests")
    config.addinivalue_line("markers", "repository: Repository layer tests")
    config.addinivalue_line("markers", "command: Command handler tests")
    config.addinivalue_line("markers", "query: Query handler tests")


# ============================================================================
# EVENT LOOP FIXTURES
# ============================================================================


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop: asyncio.AbstractEventLoop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# SESSION STORE FIXTURES
# ============================================================================


@pytest.fixture
def session_store() -> SessionStore:
    """Provide an in-memory session store for testing."""
    return InMemorySessionStore(session_max_duration_minutes=60)


@pytest.fixture
def session_timeout() -> int:
    """Configurable session timeout in hours."""
    return 1


# ============================================================================
# AUTH SERVICE FIXTURES
# ============================================================================


@pytest.fixture
def auth_service(session_store: SessionStore) -> DualAuthService:
    """Provide a DualAuthService instance for testing."""
    return DualAuthService(session_store)


# ============================================================================
# MONGODB FIXTURES
# ============================================================================


@pytest.fixture
async def mongo_client() -> AsyncGenerator[AsyncIOMotorClient, None]:
    """Provide a MongoDB client for integration tests.

    Uses test database to avoid polluting production data.
    Skips tests if MongoDB is not reachable (avoids hanging).
    """
    connection_string: str = os.getenv(
        "MONGO_CONNECTION_STRING",
        "mongodb://root:password123@localhost:8043/?authSource=admin",
    )
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        connection_string,
        serverSelectionTimeoutMS=5000,
    )
    # Verify connectivity before yielding — skip if unreachable
    try:
        await client.admin.command("ping")
    except Exception:
        client.close()
        pytest.skip("MongoDB is not available — skipping integration tests")
    yield client
    client.close()


@pytest.fixture
async def mongo_db(
    mongo_client: AsyncIOMotorClient,
) -> AsyncGenerator[AgnosticDatabase, None]:
    """Provide a test database that is cleaned after each test."""
    test_db_name: str = "test_lablet_cloud_manager"
    db: AgnosticDatabase = mongo_client[test_db_name]
    yield db
    # Cleanup: drop all collections after test
    collection_names: list[str] = await db.list_collection_names()
    for collection_name in collection_names:
        await db[collection_name].drop()


# ============================================================================
# REPOSITORY FIXTURES
# ============================================================================


@pytest.fixture
def mock_repository() -> MagicMock:
    """Provide a mock repository for testing command/query handlers."""
    mock: MagicMock = MagicMock()
    mock.get_all_async = AsyncMock(return_value=[])
    mock.get_by_id_async = AsyncMock(return_value=None)
    mock.get_by_assignee_async = AsyncMock(return_value=[])
    mock.get_by_department_async = AsyncMock(return_value=[])
    mock.add_async = AsyncMock()
    mock.update_async = AsyncMock()
    mock.delete_async = AsyncMock(return_value=True)
    return mock


# ============================================================================
# TEST SETTINGS FIXTURES
# ============================================================================


@pytest.fixture
def test_settings() -> Any:
    """Provide test-specific application settings."""
    return app_settings


# ============================================================================
# CLEANUP FIXTURES
# ============================================================================


@pytest.fixture(autouse=True)
def reset_environment() -> Generator[None, None, None]:
    """Reset environment variables after each test."""
    original_env: dict[str, str] = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)
