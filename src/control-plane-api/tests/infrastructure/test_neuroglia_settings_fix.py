"""Test to verify Neuroglia v0.6.8 properly registers Settings as singleton instance.

This test verifies that the bug documented in notes/NEUROGLIA_SETTINGS_LAMBDA_BUG.md
has been fixed in Neuroglia v0.6.8+.

The bug was that WebApplicationBuilder registered Settings using a lambda function,
which caused AttributeError when the DI container tried to inspect it.
"""

import pytest
from neuroglia.hosting.web import WebApplicationBuilder

from application.settings import Settings, app_settings


def test_settings_registered_as_singleton_not_lambda() -> None:
    """Verify Settings is registered as singleton instance, not lambda (Neuroglia v0.6.8+ fix)."""
    builder = WebApplicationBuilder(app_settings=app_settings)

    # Find the settings descriptor
    settings_descriptor = None
    for descriptor in builder.services:
        if descriptor.service_type == Settings:
            settings_descriptor = descriptor
            break

    assert settings_descriptor is not None, "Settings should be registered in DI container"

    # In the buggy version (v0.6.6), implementation_type was `lambda: app_settings`
    # In the fixed version (v0.6.8+), it should be the singleton instance or not a bare callable
    impl_type = settings_descriptor.implementation_type

    # Check that it's NOT a lambda/function without being a class
    is_bare_callable = callable(impl_type) and not isinstance(impl_type, type)

    assert not is_bare_callable, (
        f"Settings implementation_type should not be a lambda/function. " f"Got: {impl_type} (type: {type(impl_type).__name__}). " f"This suggests the Neuroglia bug is not fixed."
    )


def test_settings_can_be_resolved_from_di_container() -> None:
    """Verify Settings can be resolved from DI container without AttributeError."""
    builder = WebApplicationBuilder(app_settings=app_settings)
    provider = builder.services.build()

    # This would raise AttributeError: 'function' object has no attribute '__origin__'
    # in Neuroglia v0.6.6 when Settings was registered as lambda
    resolved_settings = provider.get_service(Settings)

    assert resolved_settings is not None
    assert isinstance(resolved_settings, Settings)
    assert resolved_settings.app_name == app_settings.app_name


def test_settings_resolves_without_attribute_error() -> None:
    """Integration test: Verify the specific bug from v0.6.6 is fixed.

    In Neuroglia v0.6.6, this test would fail with:
    AttributeError: 'function' object has no attribute '__origin__'

    In v0.6.8+, this should pass because Settings is registered as singleton instance.
    """
    builder = WebApplicationBuilder(app_settings=app_settings)
    provider = builder.services.build()

    # This is the exact operation that failed in v0.6.6
    # when Settings was registered as lambda: app_settings
    try:
        resolved = provider.get_service(Settings)
        assert resolved is not None
        assert isinstance(resolved, Settings)
    except AttributeError as e:
        if "'function' object has no attribute '__origin__'" in str(e):
            pytest.fail("The Neuroglia v0.6.6 lambda bug still exists! " "Settings is registered as lambda instead of singleton instance.")
        raise
