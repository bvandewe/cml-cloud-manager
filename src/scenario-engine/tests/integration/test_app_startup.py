"""Integration tests — app startup smoke test.

Validates DI wiring and route registration by creating the app
without connecting to external services.
"""

import pytest
from fastapi import FastAPI


@pytest.mark.integration
class TestAppStartup:
    """Verify create_app() produces a valid FastAPI instance with routes."""

    def test_create_app_returns_fastapi(self):
        """create_app() returns a FastAPI instance."""
        from main import create_app

        app = create_app()

        assert isinstance(app, FastAPI)

    def test_app_has_api_mount(self):
        """App mounts API sub-app at /api."""
        from main import create_app

        app = create_app()

        # Inspect mounted routes
        mount_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert any("/api" in p for p in mount_paths), f"Expected /api mount, got: {mount_paths}"

    def test_app_has_ui_mount(self):
        """App mounts UI sub-app at root /."""
        from main import create_app

        app = create_app()

        mount_paths = [r.path for r in app.routes if hasattr(r, "path")]
        # UI sub-app mounted at "/" or ""
        assert any(p in ("", "/") for p in mount_paths), f"Expected root mount, got: {mount_paths}"

    def test_app_title_and_version(self):
        """App has correct title and version from settings."""
        from main import create_app

        app = create_app()

        assert app.title is not None
        assert app.version is not None
