"""Tests for the Step Handler Registry (ADR-038).

Tests:
- Handler registration via @step_handler decorator
- Handler lookup via get_handler()
- Unknown handler returns None
- Duplicate registration warning
- StepResult factory methods
- StepResult.to_dict() conversion
- Full dispatch flow with params
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.models.pipeline_context import PipelineContext
from application.services.step_registry import (
    StepResult,
    clear_registry,
    get_all_handlers,
    get_handler,
    step_handler,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure each test starts with a clean registry."""
    clear_registry()
    yield
    clear_registry()


# ── StepResult tests ──────────────────────────────────


class TestStepResult:
    def test_completed(self):
        result = StepResult.completed({"key": "value"})
        assert result.status == "completed"
        assert result.result_data == {"key": "value"}
        assert result.error is None
        assert result.reason is None

    def test_completed_empty(self):
        result = StepResult.completed()
        assert result.status == "completed"
        assert result.result_data == {}

    def test_skipped(self):
        result = StepResult.skipped("No port template")
        assert result.status == "skipped"
        assert result.reason == "No port template"
        assert result.result_data == {}
        assert result.error is None

    def test_failed(self):
        result = StepResult.failed("Connection refused")
        assert result.status == "failed"
        assert result.error == "Connection refused"
        assert result.result_data == {}

    def test_to_dict_completed(self):
        result = StepResult.completed({"cml_lab_id": "abc"})
        d = result.to_dict()
        assert d == {"status": "completed", "result_data": {"cml_lab_id": "abc"}}

    def test_to_dict_failed(self):
        result = StepResult.failed("Timeout")
        d = result.to_dict()
        assert d == {"status": "failed", "error": "Timeout"}

    def test_to_dict_skipped(self):
        result = StepResult.skipped("Not applicable")
        d = result.to_dict()
        assert d == {"status": "skipped", "reason": "Not applicable"}


# ── Registry tests ──────────────────────────────────


class TestStepHandlerRegistry:
    def test_register_and_lookup(self):
        @step_handler("my_step")
        async def my_step_fn(instance, progress, context, params=None):
            return StepResult.completed()

        handler = get_handler("my_step")
        assert handler is my_step_fn

    def test_unknown_handler_returns_none(self):
        assert get_handler("nonexistent") is None

    def test_get_all_handlers(self):
        @step_handler("step_a")
        async def step_a(instance, progress, context, params=None):
            return StepResult.completed()

        @step_handler("step_b")
        async def step_b(instance, progress, context, params=None):
            return StepResult.completed()

        all_handlers = get_all_handlers()
        assert "step_a" in all_handlers
        assert "step_b" in all_handlers
        assert len(all_handlers) == 2

    def test_clear_registry(self):
        @step_handler("temp_step")
        async def temp(instance, progress, context, params=None):
            return StepResult.completed()

        assert get_handler("temp_step") is not None
        clear_registry()
        assert get_handler("temp_step") is None

    def test_duplicate_registration_overwrites(self):
        @step_handler("dup")
        async def first(instance, progress, context, params=None):
            return StepResult.completed({"version": 1})

        @step_handler("dup")
        async def second(instance, progress, context, params=None):
            return StepResult.completed({"version": 2})

        assert get_handler("dup") is second


# ── Integration: handler with params ────────────────


class TestStepHandlerWithParams:
    @pytest.mark.asyncio
    async def test_handler_receives_params(self):
        received_params: dict = {}

        @step_handler("parameterized")
        async def parameterized_handler(instance, progress, context, params=None):
            received_params.update(params or {})
            return StepResult.completed({"action_done": params.get("action") if params else None})

        handler = get_handler("parameterized")
        assert handler is not None

        # Create minimal mock context
        mock_session = MagicMock()
        mock_context = MagicMock(spec=PipelineContext)

        result = await handler(
            mock_session,
            {},
            mock_context,
            params={"action": "transfer_file", "target_node": "ubuntu-desktop"},
        )

        assert result.status == "completed"
        assert result.result_data["action_done"] == "transfer_file"
        assert received_params["action"] == "transfer_file"
        assert received_params["target_node"] == "ubuntu-desktop"

    @pytest.mark.asyncio
    async def test_handler_params_none_by_default(self):
        @step_handler("no_params")
        async def no_params_handler(instance, progress, context, params=None):
            return StepResult.completed({"has_params": params is not None})

        handler = get_handler("no_params")
        mock_session = MagicMock()
        mock_context = MagicMock(spec=PipelineContext)

        result = await handler(mock_session, {}, mock_context)
        assert result.status == "completed"
        assert result.result_data["has_params"] is False
