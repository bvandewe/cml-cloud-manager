"""Unit tests for ADR-034 LifecyclePhaseHandler — managed asyncio.Task wrapper.

Covers:
- Start/stop lifecycle: start creates task, stop cancels, idempotent start
- is_running property: True while task running, False after completion
- Result access: .result populated on success, .error on crash
- Pipeline attempt tracking: increments on each start()
- Completion callbacks: _on_complete and _on_error invoked correctly
- No auto-terminate: handler does NOT call terminate on failure (AD-PIPELINE-007)

Pattern: Matches test_pipeline_executor.py style — plain fixtures, AsyncMock/MagicMock,
pytest-asyncio auto mode.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from application.models.pipeline_context import PipelineContext
from application.models.pipeline_result import PipelineResult
from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from application.services.pipeline_executor import PipelineExecutor

# =============================================================================
# Fixtures / Helpers
# =============================================================================


def make_context() -> PipelineContext:
    """Build a PipelineContext with mocked services."""
    session = MagicMock()
    session.id = "sess-001"
    session.definition_id = "def-001"
    session.worker_ip = "10.0.0.1"

    definition = MagicMock()
    definition.id = "def-001"
    definition.pipelines = {}

    return PipelineContext(
        session=session,
        definition=definition,
        worker_ip="10.0.0.1",
        worker_cml_username="admin",
        worker_cml_password="secret",
        api=AsyncMock(),
        cml=AsyncMock(),
        lds=AsyncMock(),
    )


SIMPLE_PIPELINE = {
    "description": "test pipeline",
    "steps": [
        {"name": "a", "handler": "a"},
    ],
    "outputs": {},
}


def make_handler(
    executor_result: PipelineResult | None = None,
    executor_error: Exception | None = None,
    on_complete: AsyncMock | None = None,
    on_error: AsyncMock | None = None,
    existing_progress: dict | None = None,
) -> LifecyclePhaseHandler:
    """Build a LifecyclePhaseHandler with a mocked executor."""
    executor = AsyncMock(spec=PipelineExecutor)
    if executor_error:
        executor.execute = AsyncMock(side_effect=executor_error)
    else:
        result = executor_result or PipelineResult(
            pipeline_name="test pipeline",
            status="completed",
            duration_seconds=0.5,
            steps_completed=1,
        )
        executor.execute = AsyncMock(return_value=result)

    return LifecyclePhaseHandler(
        session_id="sess-001",
        pipeline_name="instantiate",
        pipeline_def=SIMPLE_PIPELINE,
        context=make_context(),
        executor=executor,
        step_dispatcher=AsyncMock(),
        existing_progress=existing_progress,
        on_complete=on_complete,
        on_error=on_error,
    )


# =============================================================================
# Start / Stop Lifecycle
# =============================================================================


class TestStartStop:
    """Tests for handler start and stop lifecycle."""

    async def test_start_creates_running_task(self):
        """start() should create a background task that becomes running."""
        handler = make_handler()
        assert not handler.is_running

        await handler.start()

        # Give the event loop a chance to schedule the task
        await asyncio.sleep(0.05)

        # Task may have already completed since our executor is instant
        # The key test is that it ran without error
        assert handler.result is not None or handler.error is not None or handler.is_running

    async def test_start_is_idempotent(self):
        """Calling start() while already running should be a no-op."""
        handler = make_handler()

        # Create a slow executor to keep the task running
        slow_executor = AsyncMock(spec=PipelineExecutor)

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(1.0)
            return PipelineResult(pipeline_name="test", status="completed", duration_seconds=1.0)

        slow_executor.execute = slow_execute
        handler._executor = slow_executor

        await handler.start()
        assert handler.is_running
        assert handler.pipeline_attempt == 1

        await handler.start()  # Should be no-op
        assert handler.pipeline_attempt == 1  # Not incremented

        await handler.stop()

    async def test_stop_cancels_running_task(self):
        """stop() should cancel the running task."""
        handler = make_handler()

        # Use slow executor
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10.0)
            return PipelineResult(pipeline_name="test", status="completed", duration_seconds=10.0)

        handler._executor.execute = slow_execute

        await handler.start()
        assert handler.is_running

        await handler.stop()
        assert not handler.is_running

    async def test_stop_on_stopped_handler_is_noop(self):
        """stop() on a handler that isn't running should be a no-op."""
        handler = make_handler()
        await handler.stop()  # Should not raise

    async def test_pipeline_attempt_increments_on_start(self):
        """Each start() call should increment pipeline_attempt."""
        handler = make_handler()
        assert handler.pipeline_attempt == 0

        await handler.start()
        await asyncio.sleep(0.05)
        assert handler.pipeline_attempt == 1

        # Stop and restart
        await handler.stop()
        await handler.start()
        await asyncio.sleep(0.05)
        assert handler.pipeline_attempt == 2

        await handler.stop()


# =============================================================================
# is_running Property
# =============================================================================


class TestIsRunning:
    """Tests for the is_running property."""

    async def test_false_before_start(self):
        """is_running should be False before start() is called."""
        handler = make_handler()
        assert handler.is_running is False

    async def test_false_after_completion(self):
        """is_running should be False after pipeline completes."""
        handler = make_handler()

        await handler.start()
        # Wait for task to complete
        await asyncio.sleep(0.1)

        assert handler.is_running is False

    async def test_false_after_stop(self):
        """is_running should be False after stop() is called."""
        handler = make_handler()

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10.0)
            return PipelineResult(pipeline_name="test", status="completed", duration_seconds=10.0)

        handler._executor.execute = slow_execute

        await handler.start()
        await handler.stop()
        assert handler.is_running is False


# =============================================================================
# Result / Error Access
# =============================================================================


class TestResultAccess:
    """Tests for .result and .error properties."""

    async def test_result_none_before_start(self):
        """result should be None before start()."""
        handler = make_handler()
        assert handler.result is None

    async def test_result_populated_on_success(self):
        """result should contain PipelineResult after successful execution."""
        expected = PipelineResult(pipeline_name="test", status="completed", duration_seconds=0.5, steps_completed=1)
        handler = make_handler(executor_result=expected)

        await handler.start()
        await asyncio.sleep(0.1)

        assert handler.result is not None
        assert handler.result.status == "completed"
        assert handler.result.steps_completed == 1

    async def test_result_populated_on_failure(self):
        """result should contain PipelineResult even when pipeline status is failed."""
        failed_result = PipelineResult(pipeline_name="test", status="failed", duration_seconds=0.1, error="step boom")
        handler = make_handler(executor_result=failed_result)

        await handler.start()
        await asyncio.sleep(0.1)

        assert handler.result is not None
        assert handler.result.status == "failed"
        assert handler.result.error == "step boom"

    async def test_error_set_on_exception(self):
        """error should be set when executor raises an unhandled exception."""
        handler = make_handler(executor_error=RuntimeError("executor crash"))

        await handler.start()
        await asyncio.sleep(0.1)

        assert handler.error is not None
        assert "executor crash" in str(handler.error)
        assert handler.result is None  # No result on crash


# =============================================================================
# Callbacks
# =============================================================================


class TestCallbacks:
    """Tests for on_complete and on_error callbacks."""

    async def test_on_complete_called_on_success(self):
        """on_complete callback should be called with PipelineResult on success."""
        callback = AsyncMock()
        handler = make_handler(on_complete=callback)

        await handler.start()
        await asyncio.sleep(0.1)

        callback.assert_awaited_once()
        result_arg = callback.call_args[0][0]
        assert isinstance(result_arg, PipelineResult)
        assert result_arg.status == "completed"

    async def test_on_complete_called_on_pipeline_failure(self):
        """on_complete should be called even when pipeline status is 'failed'."""
        callback = AsyncMock()
        failed_result = PipelineResult(pipeline_name="test", status="failed", duration_seconds=0.1, error="boom")
        handler = make_handler(executor_result=failed_result, on_complete=callback)

        await handler.start()
        await asyncio.sleep(0.1)

        callback.assert_awaited_once()
        result_arg = callback.call_args[0][0]
        assert result_arg.status == "failed"

    async def test_on_error_called_on_crash(self):
        """on_error callback should be called when executor raises an exception."""
        callback = AsyncMock()
        handler = make_handler(executor_error=RuntimeError("crash"), on_error=callback)

        await handler.start()
        await asyncio.sleep(0.1)

        callback.assert_awaited_once()
        exc_arg = callback.call_args[0][0]
        assert isinstance(exc_arg, RuntimeError)
        assert "crash" in str(exc_arg)

    async def test_on_complete_error_does_not_crash_handler(self):
        """If on_complete callback raises, handler should survive."""
        bad_callback = AsyncMock(side_effect=RuntimeError("callback boom"))
        handler = make_handler(on_complete=bad_callback)

        await handler.start()
        await asyncio.sleep(0.1)

        # Handler should still have a result
        assert handler.result is not None

    async def test_on_error_error_does_not_crash_handler(self):
        """If on_error callback raises, handler should survive."""
        bad_callback = AsyncMock(side_effect=RuntimeError("callback boom"))
        handler = make_handler(executor_error=RuntimeError("exec crash"), on_error=bad_callback)

        await handler.start()
        await asyncio.sleep(0.1)

        # Handler should still have the error
        assert handler.error is not None


# =============================================================================
# No Auto-Terminate (AD-PIPELINE-007)
# =============================================================================


class TestNoAutoTerminate:
    """Verify handler does NOT auto-terminate on failure (AD-PIPELINE-007)."""

    async def test_failed_pipeline_does_not_call_terminate(self):
        """Failed pipeline should NOT call api.terminate_session."""
        failed_result = PipelineResult(pipeline_name="test", status="failed", duration_seconds=0.1, error="step failed")
        handler = make_handler(executor_result=failed_result)

        await handler.start()
        await asyncio.sleep(0.1)

        # Verify no terminate call was made
        handler._context.api.terminate_session.assert_not_awaited()

    async def test_crashed_pipeline_does_not_call_terminate(self):
        """Crashed pipeline should NOT call api.terminate_session."""
        handler = make_handler(executor_error=RuntimeError("crash"))

        await handler.start()
        await asyncio.sleep(0.1)

        handler._context.api.terminate_session.assert_not_awaited()


# =============================================================================
# Existing Progress Resumability
# =============================================================================


class TestExistingProgress:
    """Tests for passing existing_progress to the executor."""

    async def test_existing_progress_forwarded_to_executor(self):
        """existing_progress should be forwarded to executor.execute()."""
        progress = {"a": {"status": "completed", "result_data": {"val": 1}}}
        handler = make_handler(existing_progress=progress)

        await handler.start()
        await asyncio.sleep(0.1)

        # Verify executor.execute was called with existing_progress
        call_kwargs = handler._executor.execute.call_args.kwargs
        assert call_kwargs["existing_progress"] == progress

    async def test_none_progress_forwarded_as_none(self):
        """None existing_progress should be passed as None."""
        handler = make_handler(existing_progress=None)

        await handler.start()
        await asyncio.sleep(0.1)

        call_kwargs = handler._executor.execute.call_args.kwargs
        assert call_kwargs["existing_progress"] is None
