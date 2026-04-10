"""Unit tests for ADR-034 PipelineExecutor — DAG execution engine.

Covers:
- DAG resolution: linear chain, diamond, cycle detection, single step, duplicate names, unknown deps
- Skip-when evaluation: truthy → skip, falsy → execute, missing var → no skip, complex expressions
- Retry logic: success on retry, max attempts exceeded
- Timeout handling: step completes in time, step exceeds timeout
- Optional step failure: optional failure doesn't block, required failure blocks
- Output resolution: dot-path resolution, missing step data → None, nested paths
- Context injection: $SESSION, $DEFINITION, $WORKER, $STEPS available
- Progress persistence: persist called after each step
- End-to-end: full 9-step instantiate pipeline, partial failure scenarios

Pattern: Follows test_instantiation_pipeline.py style — plain fixtures, AsyncMock/MagicMock,
pytest-asyncio auto mode.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.models.pipeline_context import PipelineContext
from application.services.pipeline_executor import PipelineDefinitionError, PipelineExecutor, PipelineStepError

# =============================================================================
# Fixtures / Helpers
# =============================================================================


def make_context(
    session_id: str = "sess-001",
    definition_id: str = "def-001",
    form_qualified_name: str | None = "org/project/form",
    worker_ip: str = "10.0.0.1",
    pipelines: dict | None = None,
    steps_data: dict | None = None,
) -> PipelineContext:
    """Build a PipelineContext with mocked services for testing."""
    session = MagicMock()
    session.id = session_id
    session.definition_id = definition_id
    session.worker_ip = worker_ip
    session.user_session_id = "lds-001"
    session.cml_lab_id = "lab-abc"

    definition = MagicMock()
    definition.id = definition_id
    definition.form_qualified_name = form_qualified_name
    definition.port_template = {"ssh": 22, "telnet": 23}
    definition.pipelines = pipelines

    api = AsyncMock()

    cml = AsyncMock()
    lds = AsyncMock()

    return PipelineContext(
        session=session,
        definition=definition,
        worker_ip=worker_ip,
        worker_cml_username="admin",
        worker_cml_password="secret",
        api=api,
        cml=cml,
        lds=lds,
        steps_data=steps_data or {},
    )


def make_dispatcher(results: dict[str, dict] | None = None, side_effects: dict[str, Exception] | None = None) -> AsyncMock:
    """Build a step dispatcher mock.

    Args:
        results: Mapping of handler_name → result_data dict (success).
        side_effects: Mapping of handler_name → exception to raise.
    """
    results = results or {}
    side_effects = side_effects or {}

    async def _dispatch(handler_name: str, session: Any, progress: dict, context: Any = None, params: Any = None) -> dict:
        if handler_name in side_effects:
            raise side_effects[handler_name]
        return results.get(handler_name, {"step": handler_name, "status": "completed"})

    return AsyncMock(side_effect=_dispatch)


# =============================================================================
# DAG Resolution Tests
# =============================================================================


class TestDagResolution:
    """Tests for PipelineExecutor._resolve_dag() — graphlib.TopologicalSorter."""

    def test_linear_chain(self):
        """Three steps in a linear chain: A → B → C."""
        steps = [
            {"name": "a", "handler": "a"},
            {"name": "b", "handler": "b", "needs": ["a"]},
            {"name": "c", "handler": "c", "needs": ["b"]},
        ]
        executor = PipelineExecutor()
        ordered = executor._resolve_dag(steps)
        names = [s["name"] for s in ordered]
        assert names == ["a", "b", "c"]

    def test_diamond_dependency(self):
        """Diamond: A → B, A → C, B+C → D."""
        steps = [
            {"name": "a", "handler": "a"},
            {"name": "b", "handler": "b", "needs": ["a"]},
            {"name": "c", "handler": "c", "needs": ["a"]},
            {"name": "d", "handler": "d", "needs": ["b", "c"]},
        ]
        executor = PipelineExecutor()
        ordered = executor._resolve_dag(steps)
        names = [s["name"] for s in ordered]
        assert names[0] == "a"
        assert names[-1] == "d"
        assert set(names[1:3]) == {"b", "c"}

    def test_cycle_detection(self):
        """Steps with a cycle should raise PipelineDefinitionError."""
        steps = [
            {"name": "a", "handler": "a", "needs": ["c"]},
            {"name": "b", "handler": "b", "needs": ["a"]},
            {"name": "c", "handler": "c", "needs": ["b"]},
        ]
        executor = PipelineExecutor()
        with pytest.raises(PipelineDefinitionError, match="Cycle detected"):
            executor._resolve_dag(steps)

    def test_single_step(self):
        """A single step with no dependencies."""
        steps = [{"name": "solo", "handler": "solo"}]
        executor = PipelineExecutor()
        ordered = executor._resolve_dag(steps)
        assert len(ordered) == 1
        assert ordered[0]["name"] == "solo"

    def test_duplicate_step_names(self):
        """Duplicate step names should raise PipelineDefinitionError."""
        steps = [
            {"name": "a", "handler": "a"},
            {"name": "a", "handler": "a2"},
        ]
        executor = PipelineExecutor()
        with pytest.raises(PipelineDefinitionError, match="Duplicate step name"):
            executor._resolve_dag(steps)

    def test_unknown_dependency(self):
        """Referencing an unknown step in needs should raise PipelineDefinitionError."""
        steps = [
            {"name": "a", "handler": "a", "needs": ["nonexistent"]},
        ]
        executor = PipelineExecutor()
        with pytest.raises(PipelineDefinitionError, match="unknown step 'nonexistent'"):
            executor._resolve_dag(steps)

    def test_no_dependencies_preserves_order(self):
        """Steps with no dependencies should all appear (order is implementation-defined)."""
        steps = [
            {"name": "x", "handler": "x"},
            {"name": "y", "handler": "y"},
            {"name": "z", "handler": "z"},
        ]
        executor = PipelineExecutor()
        ordered = executor._resolve_dag(steps)
        names = [s["name"] for s in ordered]
        # All steps present; exact order is implementation-defined for same-level nodes
        assert set(names) == {"x", "y", "z"}

    def test_complex_dag_nine_steps(self):
        """The real 9-step instantiate pipeline from ADR-034 seed files."""
        steps = [
            {"name": "content_sync", "handler": "content_sync"},
            {"name": "variables", "handler": "variables"},
            {"name": "lab_resolve", "handler": "lab_resolve", "needs": ["content_sync", "variables"]},
            {"name": "ports_alloc", "handler": "ports_alloc", "needs": ["lab_resolve"]},
            {"name": "tags_sync", "handler": "tags_sync", "needs": ["ports_alloc"]},
            {"name": "lab_binding", "handler": "lab_binding", "needs": ["lab_resolve", "tags_sync"]},
            {"name": "lab_start", "handler": "lab_start", "needs": ["lab_binding"]},
            {"name": "lds_provision", "handler": "lds_provision", "needs": ["lab_start"]},
            {"name": "mark_ready", "handler": "mark_ready", "needs": ["lab_start", "lds_provision"]},
        ]
        executor = PipelineExecutor()
        ordered = executor._resolve_dag(steps)
        names = [s["name"] for s in ordered]

        # Verify ordering constraints
        assert names.index("content_sync") < names.index("lab_resolve")
        assert names.index("variables") < names.index("lab_resolve")
        assert names.index("lab_resolve") < names.index("ports_alloc")
        assert names.index("ports_alloc") < names.index("tags_sync")
        assert names.index("tags_sync") < names.index("lab_binding")
        assert names.index("lab_binding") < names.index("lab_start")
        assert names.index("lab_start") < names.index("lds_provision")
        assert names.index("lab_start") < names.index("mark_ready")
        assert names.index("lds_provision") < names.index("mark_ready")


# =============================================================================
# Skip-When Evaluation Tests
# =============================================================================


class TestSkipWhenEvaluation:
    """Tests for PipelineExecutor._evaluate_skip()."""

    def test_skip_when_truthy(self):
        """Expression evaluates to True → step should be skipped."""
        context = make_context(form_qualified_name=None)
        executor = PipelineExecutor()
        result = executor._evaluate_skip("not $DEFINITION.form_qualified_name", context)
        assert result is True

    def test_skip_when_falsy(self):
        """Expression evaluates to False → step should NOT be skipped."""
        context = make_context(form_qualified_name="org/project/form")
        executor = PipelineExecutor()
        result = executor._evaluate_skip("not $DEFINITION.form_qualified_name", context)
        assert result is False

    def test_skip_when_session_attribute(self):
        """Expression referencing $SESSION attribute."""
        context = make_context()
        context.session.user_session_id = None
        executor = PipelineExecutor()
        result = executor._evaluate_skip("not $SESSION.user_session_id", context)
        assert result is True

    def test_skip_when_session_attribute_present(self):
        """Expression referencing present $SESSION attribute → do not skip."""
        context = make_context()
        context.session.user_session_id = "lds-001"
        executor = PipelineExecutor()
        result = executor._evaluate_skip("not $SESSION.user_session_id", context)
        assert result is False

    def test_skip_when_invalid_expression_returns_false(self):
        """Invalid expression → log warning, return False (don't skip)."""
        context = make_context()
        executor = PipelineExecutor()
        result = executor._evaluate_skip("this is not valid python @@#!", context)
        assert result is False

    def test_skip_when_missing_variable_returns_false(self):
        """Reference to undefined variable → return False (don't skip)."""
        context = make_context()
        executor = PipelineExecutor()
        result = executor._evaluate_skip("$NONEXISTENT.value", context)
        assert result is False


# =============================================================================
# Retry Logic Tests
# =============================================================================


class TestRetryLogic:
    """Tests for retry behavior in PipelineExecutor._execute_step()."""

    async def test_success_on_first_attempt(self):
        """Step succeeds on first attempt — no retry needed."""
        executor = PipelineExecutor()
        context = make_context()
        step = {"name": "step1", "handler": "step1"}
        dispatcher = make_dispatcher(results={"step1": {"status": "completed", "data": "ok"}})

        result = await executor._execute_step(step, context, dispatcher, {})
        assert result["status"] == "completed"

    async def test_success_on_retry(self):
        """Step fails first, succeeds on second attempt."""
        executor = PipelineExecutor()
        context = make_context()
        step = {
            "name": "step1",
            "handler": "step1",
            "retry": {"max_attempts": 3, "delay_seconds": 0},
        }
        call_count = 0

        async def flaky_dispatcher(handler_name, session, progress, context=None, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Transient failure")
            return {"status": "completed"}

        result = await executor._execute_step(step, context, AsyncMock(side_effect=flaky_dispatcher), {})
        assert result["status"] == "completed"
        assert call_count == 2

    async def test_max_attempts_exceeded(self):
        """Step fails all retry attempts → PipelineStepError raised."""
        executor = PipelineExecutor()
        context = make_context()
        step = {
            "name": "step1",
            "handler": "step1",
            "retry": {"max_attempts": 2, "delay_seconds": 0},
        }
        dispatcher = make_dispatcher(side_effects={"step1": RuntimeError("Always fails")})

        with pytest.raises(PipelineStepError, match="step1"):
            await executor._execute_step(step, context, dispatcher, {})


# =============================================================================
# Timeout Handling Tests
# =============================================================================


class TestTimeoutHandling:
    """Tests for per-step timeout via asyncio.wait_for()."""

    async def test_step_completes_within_timeout(self):
        """Step finishes before timeout — success."""
        executor = PipelineExecutor()
        context = make_context()
        step = {"name": "fast", "handler": "fast", "timeout_seconds": 5}
        dispatcher = make_dispatcher(results={"fast": {"status": "completed"}})

        result = await executor._execute_step(step, context, dispatcher, {})
        assert result["status"] == "completed"

    async def test_step_exceeds_timeout(self):
        """Step takes longer than timeout — PipelineStepError raised."""
        executor = PipelineExecutor()
        context = make_context()
        step = {
            "name": "slow",
            "handler": "slow",
            "timeout_seconds": 0.05,  # 50ms timeout
        }

        async def slow_dispatcher(handler_name, session, progress, context=None, params=None):
            await asyncio.sleep(1.0)  # Way longer than timeout
            return {"status": "completed"}

        with pytest.raises(PipelineStepError, match="slow"):
            await executor._execute_step(step, context, AsyncMock(side_effect=slow_dispatcher), {})

    async def test_timeout_with_retry(self):
        """Step times out on first attempt, succeeds on second."""
        executor = PipelineExecutor()
        context = make_context()
        step = {
            "name": "retry_timeout",
            "handler": "retry_timeout",
            "timeout_seconds": 0.1,
            "retry": {"max_attempts": 2, "delay_seconds": 0},
        }
        call_count = 0

        async def timeout_then_ok(handler_name, session, progress, context=None, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(1.0)  # Timeout on first
            return {"status": "completed"}

        result = await executor._execute_step(step, context, AsyncMock(side_effect=timeout_then_ok), {})
        assert result["status"] == "completed"
        assert call_count == 2


# =============================================================================
# Optional Step Tests
# =============================================================================


class TestOptionalSteps:
    """Tests for optional vs required step failure behavior."""

    async def test_optional_failure_continues_pipeline(self):
        """Optional step fails → pipeline continues, status is 'partial'."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test-pipeline",
            "steps": [
                {"name": "step1", "handler": "step1"},
                {"name": "step2", "handler": "step2", "needs": ["step1"], "optional": True},
                {"name": "step3", "handler": "step3", "needs": ["step1"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={"step1": {"ok": True}, "step3": {"ok": True}},
            side_effects={"step2": RuntimeError("Optional failure")},
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "partial"
        assert result.steps_completed == 2
        assert result.steps_failed == 1

    async def test_required_failure_aborts_pipeline(self):
        """Required step fails → pipeline aborts, remaining steps skipped."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test-pipeline",
            "steps": [
                {"name": "step1", "handler": "step1"},
                {"name": "step2", "handler": "step2", "needs": ["step1"]},
                {"name": "step3", "handler": "step3", "needs": ["step2"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={"step1": {"ok": True}},
            side_effects={"step2": RuntimeError("Fatal failure")},
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "failed"
        assert result.steps_completed == 1
        assert result.steps_failed == 1
        assert result.steps_skipped == 1
        assert "step2" in result.error


# =============================================================================
# Output Resolution Tests
# =============================================================================


class TestOutputResolution:
    """Tests for PipelineExecutor._resolve_outputs() and _resolve_dot_path()."""

    def test_simple_dot_path(self):
        """Resolve $STEPS.lab_resolve.cml_lab_id → value."""
        executor = PipelineExecutor()
        steps_data = {"lab_resolve": {"cml_lab_id": "lab-xyz", "lab_record_id": "rec-001"}}
        output_defs = {"cml_lab_id": "$STEPS.lab_resolve.cml_lab_id"}

        outputs = executor._resolve_outputs(output_defs, steps_data)
        assert outputs["cml_lab_id"] == "lab-xyz"

    def test_multiple_outputs(self):
        """Resolve multiple output expressions."""
        executor = PipelineExecutor()
        steps_data = {
            "lab_resolve": {"cml_lab_id": "lab-xyz", "lab_record_id": "rec-001"},
            "lds_provision": {"user_session_id": "lds-123", "launch_url": "https://example.com"},
        }
        output_defs = {
            "cml_lab_id": "$STEPS.lab_resolve.cml_lab_id",
            "lab_record_id": "$STEPS.lab_resolve.lab_record_id",
            "user_session_id": "$STEPS.lds_provision.user_session_id",
            "launch_url": "$STEPS.lds_provision.launch_url",
        }

        outputs = executor._resolve_outputs(output_defs, steps_data)
        assert outputs == {
            "cml_lab_id": "lab-xyz",
            "lab_record_id": "rec-001",
            "user_session_id": "lds-123",
            "launch_url": "https://example.com",
        }

    def test_missing_step_data_returns_none(self):
        """Expression referencing a step that didn't run → None."""
        executor = PipelineExecutor()
        steps_data = {"lab_resolve": {"cml_lab_id": "lab-xyz"}}
        output_defs = {"missing": "$STEPS.nonexistent.field"}

        outputs = executor._resolve_outputs(output_defs, steps_data)
        assert outputs["missing"] is None

    def test_missing_field_returns_none(self):
        """Expression referencing a field that doesn't exist on step data → None."""
        executor = PipelineExecutor()
        steps_data = {"lab_resolve": {"cml_lab_id": "lab-xyz"}}
        output_defs = {"missing": "$STEPS.lab_resolve.nonexistent_field"}

        outputs = executor._resolve_outputs(output_defs, steps_data)
        assert outputs["missing"] is None

    def test_non_steps_expression_returns_none(self):
        """Expression not starting with $STEPS → None."""
        executor = PipelineExecutor()
        output_defs = {"bad": "$OTHER.something"}

        outputs = executor._resolve_outputs(output_defs, {})
        assert outputs["bad"] is None

    def test_nested_dot_path(self):
        """Resolve nested dict path like $STEPS.step1.nested.key."""
        executor = PipelineExecutor()
        steps_data = {"step1": {"nested": {"key": "deep_value"}}}
        output_defs = {"result": "$STEPS.step1.nested.key"}

        outputs = executor._resolve_outputs(output_defs, steps_data)
        assert outputs["result"] == "deep_value"


# =============================================================================
# Progress Persistence Tests
# =============================================================================


class TestProgressPersistence:
    """Tests for progress persistence via CPA API."""

    async def test_progress_persisted_after_each_step(self):
        """CPA update_pipeline_progress called after every step."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={"a": {"ok": True}, "b": {"ok": True}},
        )

        await executor.execute(pipeline_def, context, dispatcher, pipeline_name="instantiate")

        # Should have been called for each step completion
        assert context.api.update_pipeline_progress.call_count >= 2

    async def test_progress_persisted_on_failure(self):
        """Progress is persisted even when a step fails."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [
                {"name": "a", "handler": "a"},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(side_effects={"a": RuntimeError("boom")})

        result = await executor.execute(pipeline_def, context, dispatcher, pipeline_name="instantiate")
        assert result.status == "failed"
        assert context.api.update_pipeline_progress.call_count >= 1

    async def test_progress_persist_failure_does_not_abort(self):
        """If progress persistence fails, the pipeline continues."""
        executor = PipelineExecutor()
        context = make_context()
        context.api.update_pipeline_progress = AsyncMock(side_effect=RuntimeError("CPA down"))
        pipeline_def = {
            "description": "test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}, "b": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 2

    async def test_progress_persisted_with_per_step_params(self):
        """Verify _persist_progress calls api.update_pipeline_progress with per-step params."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"val": 42}})

        await executor.execute(pipeline_def, context, dispatcher, pipeline_name="instantiate")

        call_kwargs = context.api.update_pipeline_progress.call_args.kwargs
        assert call_kwargs["session_id"] == "sess-001"
        assert call_kwargs["pipeline_name"] == "instantiate"
        assert call_kwargs["step_name"] == "a"
        assert call_kwargs["step_status"] == "completed"
        assert call_kwargs["result_data"] == {"val": 42}


# =============================================================================
# Resumability Tests (Sprint C)
# =============================================================================


class TestResumability:
    """Tests for existing_progress support in PipelineExecutor.execute()."""

    async def test_completed_steps_skipped_on_resume(self):
        """Steps marked 'completed' in existing_progress are skipped."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "resume test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        existing_progress = {
            "a": {"status": "completed", "result_data": {"key": "value"}},
        }
        dispatcher = make_dispatcher(results={"b": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher, existing_progress=existing_progress)

        assert result.status == "completed"
        assert result.steps_completed == 2  # a (resumed) + b (executed)
        # Dispatcher should only have been called for step b
        assert dispatcher.call_count == 1
        dispatcher.assert_awaited_once()
        call_args = dispatcher.call_args
        assert call_args[0][0] == "b"  # handler_name

    async def test_resumed_result_data_available_downstream(self):
        """Result data from resumed completed steps is available in context.steps_data."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "resume data test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        existing_progress = {
            "a": {"status": "completed", "result_data": {"cml_lab_id": "lab-123"}},
        }
        dispatcher = make_dispatcher(results={"b": {"ok": True}})

        await executor.execute(pipeline_def, context, dispatcher, existing_progress=existing_progress)

        # The resumed step's result_data should be in context.steps_data
        assert context.steps_data["a"] == {"cml_lab_id": "lab-123"}

    async def test_skipped_steps_skipped_on_resume(self):
        """Steps marked 'skipped' in existing_progress are skipped."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "skip resume test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        existing_progress = {
            "a": {"status": "skipped"},
        }
        dispatcher = make_dispatcher(results={"b": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher, existing_progress=existing_progress)

        assert result.status == "completed"
        # Dispatcher only called for b
        assert dispatcher.call_count == 1

    async def test_failed_steps_re_executed_on_resume(self):
        """Steps marked 'failed' in existing_progress are re-executed."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "retry resume test",
            "steps": [
                {"name": "a", "handler": "a"},
            ],
            "outputs": {},
        }
        existing_progress = {
            "a": {"status": "failed", "error": "timeout"},
        }
        dispatcher = make_dispatcher(results={"a": {"recovered": True}})

        result = await executor.execute(pipeline_def, context, dispatcher, existing_progress=existing_progress)

        assert result.status == "completed"
        assert dispatcher.call_count == 1

    async def test_pending_steps_re_executed_on_resume(self):
        """Steps marked 'pending' in existing_progress are re-executed."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "pending resume test",
            "steps": [
                {"name": "a", "handler": "a"},
            ],
            "outputs": {},
        }
        existing_progress = {
            "a": {"status": "pending"},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher, existing_progress=existing_progress)

        assert result.status == "completed"
        assert dispatcher.call_count == 1

    async def test_legacy_steps_list_format(self):
        """existing_progress with legacy 'steps' list format is supported."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "legacy format test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        existing_progress = {
            "steps": [
                {"step": "a", "status": "completed", "result_data": {"val": 1}},
            ],
        }
        dispatcher = make_dispatcher(results={"b": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher, existing_progress=existing_progress)

        assert result.status == "completed"
        assert dispatcher.call_count == 1
        assert context.steps_data["a"] == {"val": 1}

    async def test_no_existing_progress_runs_all(self):
        """Without existing_progress, all steps are executed normally."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "no resume test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}, "b": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher)

        assert result.status == "completed"
        assert dispatcher.call_count == 2


# =============================================================================
# PipelineResult.max_retries Tests (Sprint C)
# =============================================================================


class TestPipelineResultMaxRetries:
    """Tests for PipelineResult.max_retries field from pipeline_def."""

    async def test_max_retries_from_pipeline_def(self):
        """max_retries should be populated from pipeline_def."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "retry test",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {},
            "max_retries": 5,
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher)

        assert result.max_retries == 5

    async def test_max_retries_default_zero(self):
        """max_retries defaults to 0 when not in pipeline_def."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "default retry",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher)

        assert result.max_retries == 0


# =============================================================================
# Empty Pipeline Tests
# =============================================================================


class TestEmptyPipeline:
    """Tests for edge cases — empty or trivial pipelines."""

    async def test_empty_steps_returns_completed(self):
        """Pipeline with no steps → immediate 'completed'."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {"description": "empty", "steps": [], "outputs": {}}
        dispatcher = make_dispatcher()

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 0
        assert result.duration_seconds == 0.0

    async def test_single_step_pipeline(self):
        """Pipeline with exactly one step."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "single",
            "steps": [{"name": "only", "handler": "only"}],
            "outputs": {"result": "$STEPS.only.value"},
        }
        dispatcher = make_dispatcher(results={"only": {"value": 42}})

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 1
        assert result.outputs["result"] == 42


# =============================================================================
# Context Injection Tests
# =============================================================================


class TestContextInjection:
    """Tests for context variable availability in skip_when expressions."""

    def test_definition_attribute_available(self):
        """$DEFINITION.form_qualified_name is resolvable."""
        context = make_context(form_qualified_name="org/test/form")
        executor = PipelineExecutor()
        # Expression that checks FQN is truthy → should NOT skip
        assert executor._evaluate_skip("not $DEFINITION.form_qualified_name", context) is False

    def test_session_attribute_available(self):
        """$SESSION.id is resolvable."""
        context = make_context(session_id="sess-999")
        executor = PipelineExecutor()
        assert executor._evaluate_skip("not $SESSION.id", context) is False

    def test_steps_data_available(self):
        """$STEPS dict is available (initially empty)."""
        context = make_context(steps_data={})
        executor = PipelineExecutor()
        # $STEPS is empty dict → truthy as a dict but checking a missing key
        # This should not raise — just return False (don't skip)
        assert executor._evaluate_skip("not $STEPS", context) is True

    def test_steps_data_with_values(self):
        """$STEPS with accumulated data is available."""
        context = make_context(steps_data={"lab_resolve": {"cml_lab_id": "lab-001"}})
        executor = PipelineExecutor()
        assert executor._evaluate_skip("not $STEPS", context) is False


# =============================================================================
# Upstream Dependency Failure Tests
# =============================================================================


class TestUpstreamDependencyFailure:
    """Tests for step skipping when upstream dependencies fail."""

    async def test_downstream_skipped_when_required_upstream_fails(self):
        """If a required upstream step fails, downstream steps are skipped."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
                {"name": "c", "handler": "c", "needs": ["b"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={},
            side_effects={"a": RuntimeError("a failed")},
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "failed"
        assert result.steps_failed == 1
        assert result.steps_skipped == 2

    async def test_skip_when_combined_with_upstream_skip(self):
        """Step with skip_when + upstream completed → skip_when takes priority."""
        executor = PipelineExecutor()
        context = make_context(form_qualified_name=None)
        pipeline_def = {
            "description": "test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"], "skip_when": "not $DEFINITION.form_qualified_name"},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.steps_completed == 1
        assert result.steps_skipped == 1


# =============================================================================
# End-to-End Pipeline Tests
# =============================================================================


class TestEndToEndPipeline:
    """Integration-style tests with realistic pipeline definitions."""

    async def test_full_instantiate_pipeline_all_steps_succeed(self):
        """Full 9-step instantiate pipeline — all steps complete successfully."""
        executor = PipelineExecutor()
        context = make_context()

        pipeline_def = {
            "description": "Prepare lablet session environment",
            "trigger": "on_status:instantiating",
            "steps": [
                {
                    "name": "content_sync",
                    "handler": "content_sync",
                    "skip_when": "not $DEFINITION.form_qualified_name",
                    "timeout_seconds": 120,
                    "retry": {"max_attempts": 3, "delay_seconds": 0},
                },
                {"name": "variables", "handler": "variables", "optional": True},
                {
                    "name": "lab_resolve",
                    "handler": "lab_resolve",
                    "needs": ["content_sync", "variables"],
                    "timeout_seconds": 120,
                    "retry": {"max_attempts": 2, "delay_seconds": 0},
                },
                {
                    "name": "ports_alloc",
                    "handler": "ports_alloc",
                    "needs": ["lab_resolve"],
                    "skip_when": "not $DEFINITION.port_template",
                    "timeout_seconds": 30,
                },
                {
                    "name": "tags_sync",
                    "handler": "tags_sync",
                    "needs": ["ports_alloc"],
                    "skip_when": "not $DEFINITION.port_template",
                    "timeout_seconds": 30,
                },
                {
                    "name": "lab_binding",
                    "handler": "lab_binding",
                    "needs": ["lab_resolve", "tags_sync"],
                    "timeout_seconds": 30,
                },
                {
                    "name": "lab_start",
                    "handler": "lab_start",
                    "needs": ["lab_binding"],
                    "timeout_seconds": 300,
                    "retry": {"max_attempts": 5, "delay_seconds": 0},
                },
                {
                    "name": "lds_provision",
                    "handler": "lds_provision",
                    "needs": ["lab_start"],
                    "skip_when": "not $DEFINITION.form_qualified_name",
                    "timeout_seconds": 60,
                },
                {
                    "name": "mark_ready",
                    "handler": "mark_ready",
                    "needs": ["lab_start", "lds_provision"],
                    "timeout_seconds": 10,
                },
            ],
            "outputs": {
                "cml_lab_id": "$STEPS.lab_resolve.cml_lab_id",
                "lab_record_id": "$STEPS.lab_resolve.lab_record_id",
                "user_session_id": "$STEPS.lds_provision.user_session_id",
                "launch_url": "$STEPS.lds_provision.launch_url",
            },
        }

        step_results = {
            "content_sync": {"status": "completed", "synced": True},
            "variables": {"status": "completed", "vars": {}},
            "lab_resolve": {"cml_lab_id": "lab-xyz", "lab_record_id": "rec-001", "status": "completed"},
            "ports_alloc": {"status": "completed", "ports": {"ssh": 2001, "telnet": 2002}},
            "tags_sync": {"status": "completed", "tags_written": 5},
            "lab_binding": {"status": "completed", "bound": True},
            "lab_start": {"status": "completed", "boot_time_seconds": 45},
            "lds_provision": {"user_session_id": "lds-456", "launch_url": "https://lds.example.com/login", "status": "completed"},
            "mark_ready": {"status": "completed", "ready_at": "2026-03-02T12:00:00Z"},
        }
        dispatcher = make_dispatcher(results=step_results)

        result = await executor.execute(pipeline_def, context, dispatcher)

        assert result.status == "completed"
        assert result.steps_completed == 9
        assert result.steps_failed == 0
        assert result.steps_skipped == 0
        assert result.error is None
        assert result.outputs["cml_lab_id"] == "lab-xyz"
        assert result.outputs["lab_record_id"] == "rec-001"
        assert result.outputs["user_session_id"] == "lds-456"
        assert result.outputs["launch_url"] == "https://lds.example.com/login"

    async def test_instantiate_pipeline_no_fqn_skips_content_and_lds(self):
        """Pipeline without form_qualified_name → content_sync and lds_provision skipped."""
        executor = PipelineExecutor()
        context = make_context(form_qualified_name=None)
        # Also remove port_template so ports_alloc and tags_sync are skipped
        context.definition.port_template = None

        pipeline_def = {
            "description": "No-FQN pipeline",
            "steps": [
                {
                    "name": "content_sync",
                    "handler": "content_sync",
                    "skip_when": "not $DEFINITION.form_qualified_name",
                },
                {"name": "variables", "handler": "variables", "optional": True},
                {"name": "lab_resolve", "handler": "lab_resolve", "needs": ["content_sync", "variables"]},
                {
                    "name": "ports_alloc",
                    "handler": "ports_alloc",
                    "needs": ["lab_resolve"],
                    "skip_when": "not $DEFINITION.port_template",
                },
                {
                    "name": "tags_sync",
                    "handler": "tags_sync",
                    "needs": ["ports_alloc"],
                    "skip_when": "not $DEFINITION.port_template",
                },
                {"name": "lab_binding", "handler": "lab_binding", "needs": ["lab_resolve", "tags_sync"]},
                {"name": "lab_start", "handler": "lab_start", "needs": ["lab_binding"]},
                {
                    "name": "lds_provision",
                    "handler": "lds_provision",
                    "needs": ["lab_start"],
                    "skip_when": "not $DEFINITION.form_qualified_name",
                },
                {"name": "mark_ready", "handler": "mark_ready", "needs": ["lab_start", "lds_provision"]},
            ],
            "outputs": {
                "cml_lab_id": "$STEPS.lab_resolve.cml_lab_id",
            },
        }

        step_results = {
            "variables": {"status": "completed"},
            "lab_resolve": {"cml_lab_id": "lab-abc", "status": "completed"},
            "lab_binding": {"status": "completed"},
            "lab_start": {"status": "completed"},
            "mark_ready": {"status": "completed"},
        }
        dispatcher = make_dispatcher(results=step_results)

        result = await executor.execute(pipeline_def, context, dispatcher)

        assert result.status == "completed"
        # content_sync, ports_alloc, tags_sync, lds_provision → 4 skipped
        assert result.steps_skipped == 4
        assert result.steps_completed == 5
        assert result.outputs["cml_lab_id"] == "lab-abc"

    async def test_instantiate_pipeline_lab_start_fails(self):
        """lab_start fails → mark_ready and lds_provision skipped."""
        executor = PipelineExecutor()
        context = make_context()

        pipeline_def = {
            "description": "lab_start failure",
            "steps": [
                {"name": "content_sync", "handler": "content_sync"},
                {"name": "variables", "handler": "variables", "optional": True},
                {"name": "lab_resolve", "handler": "lab_resolve", "needs": ["content_sync", "variables"]},
                {"name": "ports_alloc", "handler": "ports_alloc", "needs": ["lab_resolve"]},
                {"name": "tags_sync", "handler": "tags_sync", "needs": ["ports_alloc"]},
                {"name": "lab_binding", "handler": "lab_binding", "needs": ["lab_resolve", "tags_sync"]},
                {"name": "lab_start", "handler": "lab_start", "needs": ["lab_binding"]},
                {"name": "lds_provision", "handler": "lds_provision", "needs": ["lab_start"]},
                {"name": "mark_ready", "handler": "mark_ready", "needs": ["lab_start", "lds_provision"]},
            ],
            "outputs": {},
        }

        step_results = {
            "content_sync": {"status": "completed"},
            "variables": {"status": "completed"},
            "lab_resolve": {"status": "completed"},
            "ports_alloc": {"status": "completed"},
            "tags_sync": {"status": "completed"},
            "lab_binding": {"status": "completed"},
        }
        dispatcher = make_dispatcher(
            results=step_results,
            side_effects={"lab_start": RuntimeError("CML lab failed to boot")},
        )

        result = await executor.execute(pipeline_def, context, dispatcher)

        assert result.status == "failed"
        assert result.steps_completed == 6
        assert result.steps_failed == 1
        assert result.steps_skipped == 2  # lds_provision, mark_ready
        assert "lab_start" in result.error

    async def test_teardown_pipeline(self):
        """Simpler 3-step teardown pipeline."""
        executor = PipelineExecutor()
        context = make_context()

        pipeline_def = {
            "description": "Teardown",
            "trigger": "on_status:stopping",
            "steps": [
                {"name": "stop_lab", "handler": "stop_lab", "timeout_seconds": 120},
                {"name": "wipe_lab", "handler": "wipe_lab", "needs": ["stop_lab"], "timeout_seconds": 120},
                {"name": "archive", "handler": "archive", "needs": ["wipe_lab"], "timeout_seconds": 10},
            ],
            "outputs": {"archived_at": "$STEPS.archive.archived_at"},
        }

        step_results = {
            "stop_lab": {"status": "completed"},
            "wipe_lab": {"status": "completed"},
            "archive": {"archived_at": "2026-03-02T18:00:00Z", "status": "completed"},
        }
        dispatcher = make_dispatcher(results=step_results)

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 3
        assert result.outputs["archived_at"] == "2026-03-02T18:00:00Z"

    async def test_optional_variables_failure_does_not_block_lab_resolve(self):
        """Optional 'variables' step fails → lab_resolve still runs (needs content_sync + variables)."""
        executor = PipelineExecutor()
        context = make_context()

        pipeline_def = {
            "description": "Optional failure test",
            "steps": [
                {"name": "content_sync", "handler": "content_sync"},
                {"name": "variables", "handler": "variables", "optional": True},
                {"name": "lab_resolve", "handler": "lab_resolve", "needs": ["content_sync", "variables"]},
            ],
            "outputs": {"cml_lab_id": "$STEPS.lab_resolve.cml_lab_id"},
        }

        step_results = {
            "content_sync": {"status": "completed"},
            "lab_resolve": {"cml_lab_id": "lab-001", "status": "completed"},
        }
        dispatcher = make_dispatcher(
            results=step_results,
            side_effects={"variables": RuntimeError("Variable resolution failed")},
        )

        result = await executor.execute(pipeline_def, context, dispatcher)

        assert result.status == "partial"  # One optional step failed
        assert result.steps_completed == 2
        assert result.steps_failed == 1
        assert result.outputs["cml_lab_id"] == "lab-001"


# =============================================================================
# Pipeline Definition Edge Cases
# =============================================================================


class TestPipelineDefinitionEdgeCases:
    """Tests for unusual but valid pipeline definitions."""

    async def test_step_without_handler_uses_name(self):
        """Step without explicit 'handler' falls back to 'name'."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "no handler field",
            "steps": [{"name": "my_step"}],  # No 'handler' key
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"my_step": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"

    async def test_dispatcher_returning_non_dict(self):
        """Dispatcher returns a non-dict value → wrapped in {'result': value}."""
        executor = PipelineExecutor()
        context = make_context()
        step = {"name": "weird", "handler": "weird"}

        async def non_dict_dispatcher(handler_name, session, progress, context=None, params=None):
            return "string_result"  # type: ignore[return-value]

        result = await executor._execute_step(step, context, AsyncMock(side_effect=non_dict_dispatcher), {})
        assert result == {"result": "string_result"}

    async def test_pipeline_with_only_skipped_steps(self):
        """All steps skipped → status is 'completed', zero completed/failed."""
        executor = PipelineExecutor()
        context = make_context(form_qualified_name=None)
        pipeline_def = {
            "description": "all skipped",
            "steps": [
                {"name": "a", "handler": "a", "skip_when": "not $DEFINITION.form_qualified_name"},
                {"name": "b", "handler": "b", "skip_when": "not $DEFINITION.form_qualified_name"},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher()

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 0
        assert result.steps_skipped == 2


# =============================================================================
# Initial Progress Build Tests
# =============================================================================


class TestBuildInitialProgress:
    """Tests for PipelineExecutor._build_initial_progress()."""

    def test_builds_pending_entries(self):
        """All steps start with 'pending' status."""
        executor = PipelineExecutor()
        steps = [
            {"name": "a", "handler": "a"},
            {"name": "b", "handler": "b"},
            {"name": "c", "handler": "c"},
        ]
        progress = executor._build_initial_progress(steps)
        assert len(progress) == 3
        assert progress["a"]["status"] == "pending"
        assert progress["b"]["status"] == "pending"
        assert progress["c"]["status"] == "pending"
        assert progress["a"]["order"] == 0
        assert progress["b"]["order"] == 1
        assert progress["c"]["order"] == 2


# =============================================================================
# Handler Status Propagation Tests (AD-PIPELINE-STATUS-01)
# =============================================================================


class TestHandlerStatusPropagation:
    """Tests for executor honoring step handler return statuses.

    Step handlers may return {"status": "skipped"} or {"status": "failed", "error": "..."}
    instead of raising exceptions. The executor must propagate these statuses correctly
    rather than blindly marking every non-exception return as "completed".

    This is critical for pipeline steps like ports_alloc and tags_sync that gracefully
    skip or fail when preconditions aren't met (e.g. no port_template defined).
    """

    async def test_handler_returns_skipped_marks_step_skipped(self):
        """Handler returning {"status": "skipped"} → step is tracked as skipped."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "handler-skip test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={
                "a": {"status": "skipped", "reason": "no port_template"},
                "b": {"status": "completed", "ok": True},
            },
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.steps_skipped == 1
        assert result.steps_completed == 1
        assert result.status == "completed"

    async def test_handler_returns_skipped_result_data_available_downstream(self):
        """Skipped step's result_data is stored in context.steps_data for downstream access."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "skip data test",
            "steps": [
                {"name": "ports_alloc", "handler": "ports_alloc"},
                {"name": "tags_sync", "handler": "tags_sync", "needs": ["ports_alloc"]},
            ],
            "outputs": {},
        }
        skip_data = {"status": "skipped", "reason": "no port_template defined"}
        dispatcher = make_dispatcher(
            results={
                "ports_alloc": skip_data,
                "tags_sync": {"status": "completed"},
            },
        )

        await executor.execute(pipeline_def, context, dispatcher)
        assert context.steps_data["ports_alloc"] == skip_data

    async def test_handler_returns_failed_required_aborts_pipeline(self):
        """Required handler returning {"status": "failed"} → pipeline aborts, remaining skipped."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "handler-fail test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
                {"name": "c", "handler": "c", "needs": ["b"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={
                "a": {"status": "completed", "ok": True},
                "b": {"status": "failed", "error": "No lab_record_id available"},
            },
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "failed"
        assert result.steps_completed == 1  # only 'a'
        assert result.steps_failed == 1  # 'b'
        assert result.steps_skipped == 1  # 'c' skipped due to abort
        assert "b" in result.error

    async def test_handler_returns_failed_optional_continues(self):
        """Optional handler returning {"status": "failed"} → pipeline continues, status is 'partial'."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "optional handler-fail test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"], "optional": True},
                {"name": "c", "handler": "c", "needs": ["a"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={
                "a": {"status": "completed"},
                "b": {"status": "failed", "error": "Optional step failed gracefully"},
                "c": {"status": "completed"},
            },
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "partial"
        assert result.steps_completed == 2
        assert result.steps_failed == 1

    async def test_handler_returns_completed_normal_flow(self):
        """Handler returning {"status": "completed"} → normal completion (backward compat)."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "explicit-completed test",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"status": "completed", "data": "ok"}})

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 1
        assert context.steps_data["a"] == {"status": "completed", "data": "ok"}

    async def test_handler_returns_dict_without_status_treated_as_completed(self):
        """Handler returning dict without "status" key → treated as completed (backward compat)."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "no-status test",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {"val": "$STEPS.a.value"},
        }
        dispatcher = make_dispatcher(results={"a": {"value": 42}})

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 1
        assert result.outputs["val"] == 42

    async def test_handler_skipped_progress_persisted(self):
        """Handler-skipped step has progress persisted via CPA API."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "skip-persist test",
            "steps": [{"name": "ports_alloc", "handler": "ports_alloc"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={"ports_alloc": {"status": "skipped", "reason": "no port_template"}},
        )

        await executor.execute(pipeline_def, context, dispatcher)

        # Verify progress was persisted with "skipped" status
        call_kwargs = context.api.update_pipeline_progress.call_args.kwargs
        assert call_kwargs["step_name"] == "ports_alloc"
        assert call_kwargs["step_status"] == "skipped"

    async def test_handler_failed_progress_persisted(self):
        """Handler-failed step has progress persisted with error detail."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "fail-persist test",
            "steps": [{"name": "ports_alloc", "handler": "ports_alloc"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={"ports_alloc": {"status": "failed", "error": "API returned 404"}},
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "failed"

        # Find the call for ports_alloc (first call should be for it)
        calls = context.api.update_pipeline_progress.call_args_list
        ports_call = next(c for c in calls if c.kwargs.get("step_name") == "ports_alloc")
        assert ports_call.kwargs["step_status"] == "failed"
        assert "API returned 404" in ports_call.kwargs["error"]

    async def test_skip_when_plus_handler_skip_deduplication(self):
        """Step skipped by skip_when is not executed — handler skip is a separate path."""
        executor = PipelineExecutor()
        context = make_context()
        context.definition.port_template = None  # Makes skip_when 'not $DEFINITION.port_template' → True
        pipeline_def = {
            "description": "skip_when vs handler skip",
            "steps": [
                {
                    "name": "ports_alloc",
                    "handler": "ports_alloc",
                    "skip_when": "not $DEFINITION.port_template",
                },
            ],
            "outputs": {},
        }
        # Dispatcher should NOT be called — step is skipped by skip_when
        dispatcher = make_dispatcher(results={"ports_alloc": {"status": "completed"}})

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.steps_skipped == 1
        assert result.steps_completed == 0
        # Dispatcher should not have been called
        assert dispatcher.call_count == 0

    async def test_ports_alloc_tags_sync_skip_when_no_port_template(self):
        """Realistic test: ports_alloc and tags_sync both skipped via skip_when when no port_template."""
        executor = PipelineExecutor()
        context = make_context()
        context.definition.port_template = None

        pipeline_def = {
            "description": "No port template pipeline",
            "steps": [
                {"name": "lab_resolve", "handler": "lab_resolve"},
                {
                    "name": "ports_alloc",
                    "handler": "ports_alloc",
                    "needs": ["lab_resolve"],
                    "skip_when": "not $DEFINITION.port_template",
                    "timeout_seconds": 30,
                },
                {
                    "name": "tags_sync",
                    "handler": "tags_sync",
                    "needs": ["ports_alloc"],
                    "skip_when": "not $DEFINITION.port_template",
                    "timeout_seconds": 30,
                },
                {"name": "lab_binding", "handler": "lab_binding", "needs": ["lab_resolve", "tags_sync"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={
                "lab_resolve": {"cml_lab_id": "lab-001", "status": "completed"},
                "lab_binding": {"status": "completed"},
            },
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 2  # lab_resolve + lab_binding
        assert result.steps_skipped == 2  # ports_alloc + tags_sync
        # Dispatcher called only for lab_resolve and lab_binding
        assert dispatcher.call_count == 2

    async def test_ports_alloc_tags_sync_execute_when_port_template_present(self):
        """Realistic test: ports_alloc and tags_sync execute when port_template is present."""
        executor = PipelineExecutor()
        context = make_context()
        # make_context() already sets port_template = {"ssh": 22, "telnet": 23}

        pipeline_def = {
            "description": "With port template pipeline",
            "steps": [
                {"name": "lab_resolve", "handler": "lab_resolve"},
                {
                    "name": "ports_alloc",
                    "handler": "ports_alloc",
                    "needs": ["lab_resolve"],
                    "skip_when": "not $DEFINITION.port_template",
                    "timeout_seconds": 30,
                },
                {
                    "name": "tags_sync",
                    "handler": "tags_sync",
                    "needs": ["ports_alloc"],
                    "skip_when": "not $DEFINITION.port_template",
                    "timeout_seconds": 30,
                },
                {"name": "lab_binding", "handler": "lab_binding", "needs": ["lab_resolve", "tags_sync"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(
            results={
                "lab_resolve": {"cml_lab_id": "lab-001", "status": "completed"},
                "ports_alloc": {"status": "completed", "allocated_ports": {"ssh": 2001}},
                "tags_sync": {"status": "completed", "tags_written": 2},
                "lab_binding": {"status": "completed"},
            },
        )

        result = await executor.execute(pipeline_def, context, dispatcher)
        assert result.status == "completed"
        assert result.steps_completed == 4
        assert result.steps_skipped == 0


# =============================================================================
# Pipeline Name Routing Tests (ADR-034 Sprint E)
# =============================================================================


class TestPipelineNameRouting:
    """Tests for pipeline_name parameter controlling progress routing.

    All progress is persisted via update_pipeline_progress.
    When pipeline_name is None, it defaults to "unnamed".
    """

    async def test_without_pipeline_name_uses_unnamed_default(self):
        """Default (pipeline_name=None) → update_pipeline_progress called with 'unnamed'."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}})

        # No pipeline_name → defaults to "unnamed"
        await executor.execute(pipeline_def, context, dispatcher)

        assert context.api.update_pipeline_progress.call_count >= 1
        call_kwargs = context.api.update_pipeline_progress.call_args.kwargs
        assert call_kwargs["pipeline_name"] == "unnamed"

    async def test_with_pipeline_name_uses_generic_endpoint(self):
        """Explicit pipeline_name → update_pipeline_progress called."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}})

        await executor.execute(pipeline_def, context, dispatcher, pipeline_name="teardown")

        assert context.api.update_pipeline_progress.call_count >= 1

    async def test_pipeline_name_passed_in_generic_call(self):
        """update_pipeline_progress receives the correct pipeline_name."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [{"name": "stop_lab", "handler": "stop_lab"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"stop_lab": {"stopped": True}})

        await executor.execute(pipeline_def, context, dispatcher, pipeline_name="teardown")

        call_kwargs = context.api.update_pipeline_progress.call_args.kwargs
        assert call_kwargs["pipeline_name"] == "teardown"
        assert call_kwargs["step_name"] == "stop_lab"
        assert call_kwargs["step_status"] == "completed"
        assert call_kwargs["result_data"] == {"stopped": True}

    async def test_pipeline_name_on_failure_uses_generic_endpoint(self):
        """Failed step with pipeline_name → update_pipeline_progress with status=failed."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(side_effects={"a": RuntimeError("boom")})

        result = await executor.execute(pipeline_def, context, dispatcher, pipeline_name="collect_evidence")

        assert result.status == "failed"
        assert context.api.update_pipeline_progress.call_count >= 1
        # Verify the failure details
        call_kwargs = context.api.update_pipeline_progress.call_args.kwargs
        assert call_kwargs["pipeline_name"] == "collect_evidence"
        assert call_kwargs["step_status"] == "failed"
        assert "boom" in call_kwargs["error"]

    async def test_pipeline_name_on_skipped_step(self):
        """Skipped step with pipeline_name → update_pipeline_progress with status=skipped."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "test",
            "steps": [
                {"name": "a", "handler": "a", "skip_when": "True"},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {}})

        await executor.execute(pipeline_def, context, dispatcher, pipeline_name="compute_grading")

        assert context.api.update_pipeline_progress.call_count >= 1
        call_kwargs = context.api.update_pipeline_progress.call_args.kwargs
        assert call_kwargs["step_name"] == "a"
        assert call_kwargs["step_status"] == "skipped"
        assert call_kwargs["pipeline_name"] == "compute_grading"

    async def test_generic_persist_failure_does_not_abort(self):
        """If update_pipeline_progress fails, the pipeline continues."""
        executor = PipelineExecutor()
        context = make_context()
        context.api.update_pipeline_progress = AsyncMock(side_effect=RuntimeError("CPA down"))
        pipeline_def = {
            "description": "test",
            "steps": [
                {"name": "a", "handler": "a"},
                {"name": "b", "handler": "b", "needs": ["a"]},
            ],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}, "b": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher, pipeline_name="teardown")
        assert result.status == "completed"
        assert result.steps_completed == 2

    async def test_pipeline_label_independent_of_pipeline_name(self):
        """PipelineResult.pipeline_name uses the description, not the pipeline_name param."""
        executor = PipelineExecutor()
        context = make_context()
        pipeline_def = {
            "description": "My Teardown Pipeline",
            "steps": [{"name": "a", "handler": "a"}],
            "outputs": {},
        }
        dispatcher = make_dispatcher(results={"a": {"ok": True}})

        result = await executor.execute(pipeline_def, context, dispatcher, pipeline_name="teardown")

        # PipelineResult.pipeline_name comes from the description, not the routing param
        assert result.pipeline_name == "My Teardown Pipeline"
