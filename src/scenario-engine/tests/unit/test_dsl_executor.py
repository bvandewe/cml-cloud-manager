"""Unit tests for the DSL executor and jq evaluator."""

import asyncio

import pytest
from application.services.dsl_executor import DslExecutor
from application.services.jq_evaluator import JqEvaluationError, evaluate, extract_expression, is_expression, resolve_object, resolve_value
from application.services.scenario_context import AdapterRegistry, ScenarioContext
from application.services.scenario_registry import ScenarioResult, clear_registry, scenario

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_context() -> ScenarioContext:
    """Build a ScenarioContext for DSL tests."""

    async def noop_progress(pct: int, msg: str, details: dict | None = None) -> None:
        pass

    return ScenarioContext(
        job_id="dsl-test-job",
        scenario_name="dsl_lifecycle",
        scenario_version="v1",
        input_data={},
        adapters=AdapterRegistry(),
        report_progress=noop_progress,
        cancellation_event=asyncio.Event(),
    )


@pytest.fixture(autouse=True)
def clean_registry():
    clear_registry()
    yield
    clear_registry()


# ===========================================================================
# jq Evaluator Tests
# ===========================================================================


class TestJqEvaluator:
    """Tests for jq_evaluator module."""

    @pytest.mark.unit
    def test_is_expression_true(self):
        assert is_expression("${ .lab_id }") is True
        assert is_expression("${ $context.worker_ip }") is True

    @pytest.mark.unit
    def test_is_expression_false(self):
        assert is_expression("hello") is False
        assert is_expression(42) is False
        assert is_expression(None) is False
        assert is_expression("${missing_space}") is True  # Spaces optional
        assert is_expression("not an expression ${ .x }") is False  # Must be entire string

    @pytest.mark.unit
    def test_extract_expression(self):
        assert extract_expression("${ .lab_id }") == ".lab_id"
        assert extract_expression("${ $context.x }") == "$context.x"
        assert extract_expression("literal") is None

    @pytest.mark.unit
    def test_evaluate_simple(self):
        result = evaluate(".name", {"name": "test-lab", "id": "123"})
        assert result == "test-lab"

    @pytest.mark.unit
    def test_evaluate_nested(self):
        result = evaluate(".config.port", {"config": {"port": 8080}})
        assert result == 8080

    @pytest.mark.unit
    def test_evaluate_with_variables(self):
        result = evaluate("$context.worker_ip", {}, variables={"context": {"worker_ip": "10.0.0.1"}})
        assert result == "10.0.0.1"

    @pytest.mark.unit
    def test_evaluate_object_construction(self):
        data = {"lab_id": "lab-1", "title": "My Lab", "extra": "ignore"}
        result = evaluate("{ lab_id: .lab_id, title: .title }", data)
        assert result == {"lab_id": "lab-1", "title": "My Lab"}

    @pytest.mark.unit
    def test_evaluate_invalid_expression(self):
        with pytest.raises(JqEvaluationError):
            evaluate("invalid syntax !!!", {})

    @pytest.mark.unit
    def test_resolve_value_literal(self):
        assert resolve_value("hello", {}) == "hello"
        assert resolve_value(42, {}) == 42
        assert resolve_value(True, {}) is True

    @pytest.mark.unit
    def test_resolve_value_expression(self):
        result = resolve_value("${ .port }", {"port": 9090})
        assert result == 9090

    @pytest.mark.unit
    def test_resolve_object(self):
        obj = {"host": "${ .worker_ip }", "port": 8080, "name": "literal"}
        result = resolve_object(obj, {"worker_ip": "10.0.0.1"})
        assert result == {"host": "10.0.0.1", "port": 8080, "name": "literal"}


# ===========================================================================
# DSL Executor Tests
# ===========================================================================


class TestDslExecutorSet:
    """Tests for 'set' task type."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_set_literal_values(self):
        """'set' merges literal values into context."""
        context = _build_context()
        executor = DslExecutor(context)

        tasks = [{"initContext": {"set": {"phase": "instantiate", "ready": True}}}]
        result = await executor.execute(tasks)

        assert result.success
        assert result.context["phase"] == "instantiate"
        assert result.context["ready"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_set_with_expressions(self):
        """'set' resolves jq expressions."""
        context = _build_context()
        executor = DslExecutor(context)

        tasks = [
            {"setInput": {"set": {"worker": "10.0.0.1"}}},
            {"derive": {"set": {"summary": "${ $context.worker }"}}},
        ]
        result = await executor.execute(tasks)

        assert result.success
        assert result.context["summary"] == "10.0.0.1"


class TestDslExecutorCall:
    """Tests for 'call' task type."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_call_scenario_success(self):
        """'call' invokes a registered scenario and returns output."""

        @scenario(name="test_add", version="v1")
        class AddScenario:
            async def execute(self, input_data: dict, ctx: ScenarioContext) -> ScenarioResult:
                return ScenarioResult.completed(output_data={"sum": input_data.get("a", 0) + input_data.get("b", 0)})

        context = _build_context()
        executor = DslExecutor(context)

        tasks = [{"addNumbers": {"call": "test_add@v1", "with": {"a": 3, "b": 4}}}]
        result = await executor.execute(tasks)

        assert result.success

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_call_scenario_not_found(self):
        """'call' fails if scenario not in registry."""
        context = _build_context()
        executor = DslExecutor(context)

        tasks = [{"missing": {"call": "nonexistent@v1"}}]
        result = await executor.execute(tasks)

        assert not result.success
        assert "not found" in result.error
        assert result.failed_task == "missing"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_call_with_jq_arguments(self):
        """'call' resolves jq expressions in 'with' arguments."""

        @scenario(name="echo_input", version="v1")
        class EchoInput:
            async def execute(self, input_data: dict, ctx: ScenarioContext) -> ScenarioResult:
                return ScenarioResult.completed(output_data=input_data)

        context = _build_context()
        executor = DslExecutor(context)

        tasks = [
            {"setCtx": {"set": {"target": "10.0.0.1"}}},
            {"echoIt": {"call": "echo_input@v1", "with": {"host": "${ $context.target }"}}},
        ]
        result = await executor.execute(tasks)

        assert result.success

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_call_with_timeout(self):
        """'call' respects timeout."""

        @scenario(name="slow_task", version="v1")
        class SlowTask:
            async def execute(self, input_data: dict, ctx: ScenarioContext) -> ScenarioResult:
                await asyncio.sleep(10)
                return ScenarioResult.completed()

        context = _build_context()
        executor = DslExecutor(context)

        tasks = [{"slowOne": {"call": "slow_task@v1", "timeout": {"seconds": 0.1}}}]
        result = await executor.execute(tasks)

        assert not result.success
        assert "timed out" in result.error.lower()


class TestDslExecutorDo:
    """Tests for 'do' task type."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_do_sequential_tasks(self):
        """'do' executes sub-tasks sequentially."""

        @scenario(name="step_a", version="v1")
        class StepA:
            async def execute(self, input_data: dict, ctx: ScenarioContext) -> ScenarioResult:
                return ScenarioResult.completed(output_data={"a": True})

        context = _build_context()
        executor = DslExecutor(context)

        tasks = [
            {
                "pipeline": {
                    "do": [
                        {"init": {"set": {"started": True}}},
                        {"run_a": {"call": "step_a@v1"}},
                        {"finish": {"set": {"done": True}}},
                    ]
                }
            }
        ]
        result = await executor.execute(tasks)

        assert result.success
        assert result.context["started"] is True
        assert result.context["done"] is True


class TestDslExecutorTry:
    """Tests for 'try' task type."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_try_success_no_retry(self):
        """'try' passes through on success."""

        @scenario(name="reliable", version="v1")
        class Reliable:
            async def execute(self, input_data: dict, ctx: ScenarioContext) -> ScenarioResult:
                return ScenarioResult.completed(output_data={"ok": True})

        context = _build_context()
        executor = DslExecutor(context)

        tasks = [{"safe": {"try": {"call": "reliable@v1"}, "catch": {}}}]
        result = await executor.execute(tasks)

        assert result.success

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_try_with_retry_succeeds_on_second(self):
        """'try' retries and succeeds on second attempt."""
        call_count = {"n": 0}

        @scenario(name="flaky", version="v1")
        class Flaky:
            async def execute(self, input_data: dict, ctx: ScenarioContext) -> ScenarioResult:
                call_count["n"] += 1
                if call_count["n"] < 2:
                    return ScenarioResult.failed("Transient error")
                return ScenarioResult.completed(output_data={"recovered": True})

        context = _build_context()
        executor = DslExecutor(context)

        tasks = [
            {
                "retryable": {
                    "try": {"call": "flaky@v1"},
                    "catch": {
                        "retry": {
                            "limit": {"attempt": {"count": 3}},
                            "delay": {"seconds": 0},
                        }
                    },
                }
            }
        ]
        result = await executor.execute(tasks)

        assert result.success
        assert call_count["n"] == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_try_exhausted_with_fallback(self):
        """'try' with exhausted retries falls back to catch.do."""

        @scenario(name="always_fail", version="v1")
        class AlwaysFail:
            async def execute(self, input_data: dict, ctx: ScenarioContext) -> ScenarioResult:
                return ScenarioResult.failed("Permanent error")

        context = _build_context()
        executor = DslExecutor(context)

        tasks = [
            {
                "risky": {
                    "try": {"call": "always_fail@v1"},
                    "catch": {
                        "retry": {"limit": {"attempt": {"count": 2}}, "delay": {"seconds": 0}},
                        "do": [{"fallback": {"set": {"fallback_executed": True}}}],
                    },
                }
            }
        ]
        result = await executor.execute(tasks)

        assert result.success
        assert result.context["fallback_executed"] is True


class TestDslExecutorConditional:
    """Tests for 'if' conditional on tasks."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_if_true_executes(self):
        """Task with 'if' evaluating to true executes."""
        context = _build_context()
        executor = DslExecutor(context)

        tasks = [
            {"init": {"set": {"has_ports": True}}},
            {"conditional": {"set": {"ports_processed": True}, "if": "${ $context.has_ports }"}},
        ]
        result = await executor.execute(tasks)

        assert result.success
        assert result.context["ports_processed"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_if_false_skips(self):
        """Task with 'if' evaluating to false is skipped."""
        context = _build_context()
        executor = DslExecutor(context)

        tasks = [
            {"init": {"set": {"has_ports": False}}},
            {"conditional": {"set": {"ports_processed": True}, "if": "${ $context.has_ports }"}},
        ]
        result = await executor.execute(tasks)

        assert result.success
        assert "ports_processed" not in result.context
