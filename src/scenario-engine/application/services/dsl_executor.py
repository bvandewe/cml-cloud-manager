"""DSL Task DAG Executor — executes lifecycle.yaml task definitions.

Supports task types: call, do, set, try (Phase 2 core).
Additional types (for, fork, switch, wait, emit, run, raise, listen) are Phase 3+.

The executor processes a list of tasks sequentially, maintaining a context dict
that accumulates state across tasks via export.as expressions.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from application.services.jq_evaluator import JqEvaluationError, is_expression, resolve_object, resolve_value
from application.services.scenario_context import ScenarioContext
from application.services.scenario_registry import ScenarioResult, get_scenario

logger = logging.getLogger(__name__)


class DslExecutionError(Exception):
    """Raised when a DSL task execution fails fatally."""

    def __init__(self, task_name: str, detail: str, instance: str = "") -> None:
        self.task_name = task_name
        self.detail = detail
        self.instance = instance
        super().__init__(f"DSL execution error at '{task_name}': {detail}")


@dataclass
class DslExecutionResult:
    """Result of a DSL document execution."""

    success: bool
    context: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    failed_task: str | None = None

    @staticmethod
    def completed(context: dict[str, Any]) -> DslExecutionResult:
        return DslExecutionResult(success=True, context=context)

    @staticmethod
    def failed(error: str, failed_task: str | None = None) -> DslExecutionResult:
        return DslExecutionResult(success=False, error=error, failed_task=failed_task)


class DslExecutor:
    """Executes a DSL task list within a ScenarioContext.

    Task types supported (Phase 2):
    - call: Invoke a registered scenario by name@version
    - do: Execute sequential sub-tasks
    - set: Update context variables
    - try: Error handling with retry

    Data flow:
    - Each task receives the previous task's output as its raw input
    - input.from transforms raw input before execution
    - output.as transforms the task's raw output
    - export.as updates $context with selected output values
    """

    def __init__(self, scenario_context: ScenarioContext) -> None:
        self._context = scenario_context
        self._workflow_context: dict[str, Any] = {}
        self._logger = scenario_context.logger.getChild("dsl")

    async def execute(self, tasks: list[dict[str, Any]], initial_context: dict[str, Any] | None = None) -> DslExecutionResult:
        """Execute a list of DSL tasks.

        Args:
            tasks: Ordered list of task definitions (from lifecycle.yaml phases).
            initial_context: Initial workflow context (merged into $context).

        Returns:
            DslExecutionResult with final context or error details.
        """
        self._workflow_context = dict(initial_context or {})
        last_output: Any = self._workflow_context

        for task_def in tasks:
            if self._context.cancellation_event.is_set():
                return DslExecutionResult.failed("Cancelled", failed_task="(cancellation)")

            # Each task_def is {task_name: {task_spec}}
            if not isinstance(task_def, dict) or len(task_def) != 1:
                return DslExecutionResult.failed(f"Invalid task definition: expected single-key dict, got {type(task_def)}")

            task_name = next(iter(task_def))
            task_spec = task_def[task_name]

            if not isinstance(task_spec, dict):
                return DslExecutionResult.failed(f"Invalid task spec for '{task_name}': expected dict", failed_task=task_name)

            # Check 'if' condition
            if_expr = task_spec.get("if")
            if if_expr is not None:
                try:
                    condition = resolve_value(if_expr, last_output, self._jq_variables(last_output))
                except JqEvaluationError as e:
                    return DslExecutionResult.failed(f"Condition evaluation failed: {e.detail}", failed_task=task_name)
                if not condition:
                    self._logger.debug("Skipping task '%s' (condition false)", task_name)
                    continue

            # Dispatch by task type
            try:
                task_output = await self._execute_task(task_name, task_spec, last_output)
            except DslExecutionError as e:
                return DslExecutionResult.failed(e.detail, failed_task=e.task_name)

            # Apply output.as transformation
            output_spec = task_spec.get("output")
            if output_spec and isinstance(output_spec, dict) and "as" in output_spec:
                try:
                    task_output = resolve_value(output_spec["as"], task_output, self._jq_variables(task_output))
                except JqEvaluationError as e:
                    return DslExecutionResult.failed(f"Output transform failed: {e.detail}", failed_task=task_name)

            # Apply export.as to update $context
            export_spec = task_spec.get("export")
            if export_spec and isinstance(export_spec, dict) and "as" in export_spec:
                try:
                    new_context = resolve_value(export_spec["as"], task_output, self._jq_variables(task_output))
                    if isinstance(new_context, dict):
                        self._workflow_context.update(new_context)
                except JqEvaluationError as e:
                    return DslExecutionResult.failed(f"Export transform failed: {e.detail}", failed_task=task_name)

            last_output = task_output

            # Check flow directive
            then = task_spec.get("then")
            if then == "end":
                break

        return DslExecutionResult.completed(self._workflow_context)

    async def _execute_task(self, task_name: str, task_spec: dict[str, Any], raw_input: Any) -> Any:
        """Dispatch a single task by type."""
        # Determine task type
        if "call" in task_spec:
            return await self._execute_call(task_name, task_spec, raw_input)
        elif "do" in task_spec:
            return await self._execute_do(task_name, task_spec, raw_input)
        elif "set" in task_spec:
            return self._execute_set(task_name, task_spec, raw_input)
        elif "try" in task_spec:
            return await self._execute_try(task_name, task_spec, raw_input)
        else:
            known_types = {"call", "do", "set", "try", "for", "fork", "switch", "wait", "emit", "run", "raise", "listen"}
            found = set(task_spec.keys()) & known_types
            if found:
                raise DslExecutionError(task_name, f"Task type '{next(iter(found))}' not yet implemented (Phase 3+)")
            raise DslExecutionError(task_name, f"Unknown task type. Keys: {list(task_spec.keys())}")

    # =========================================================================
    # call — Invoke a registered scenario
    # =========================================================================

    async def _execute_call(self, task_name: str, task_spec: dict[str, Any], raw_input: Any) -> Any:
        """Execute a 'call' task — invokes a scenario from the registry."""
        call_ref = task_spec["call"]
        if not isinstance(call_ref, str):
            raise DslExecutionError(task_name, f"'call' must be a string scenario reference, got {type(call_ref)}")

        # Parse name@version
        if "@" in call_ref:
            scenario_name, scenario_version = call_ref.split("@", 1)
        else:
            scenario_name, scenario_version = call_ref, "v1"

        # Resolve scenario
        scenario_meta = get_scenario(scenario_name, scenario_version)
        if scenario_meta is None:
            raise DslExecutionError(task_name, f"Scenario '{call_ref}' not found in registry")

        # Build input: resolve 'with' arguments + 'input.from' transform
        task_input = self._resolve_task_input(task_name, task_spec, raw_input)

        # Timeout
        timeout_spec = task_spec.get("timeout")
        timeout_seconds: float | None = None
        if timeout_spec and isinstance(timeout_spec, dict):
            timeout_seconds = timeout_spec.get("seconds")

        # Execute scenario
        self._logger.info("Calling scenario '%s' (task: %s)", call_ref, task_name)
        scenario_instance = scenario_meta.implementation()

        try:
            if timeout_seconds:
                result: ScenarioResult = await asyncio.wait_for(
                    scenario_instance.execute(task_input, self._context),
                    timeout=timeout_seconds,
                )
            else:
                result = await scenario_instance.execute(task_input, self._context)
        except asyncio.TimeoutError:
            raise DslExecutionError(task_name, f"Scenario '{call_ref}' timed out after {timeout_seconds}s")
        except asyncio.CancelledError:
            raise DslExecutionError(task_name, "Cancelled")

        if result.status == "failed":
            raise DslExecutionError(task_name, f"Scenario '{call_ref}' failed: {result.error}")
        if result.status == "cancelled":
            raise DslExecutionError(task_name, "Scenario cancelled")

        return result.output_data

    # =========================================================================
    # do — Sequential sub-tasks
    # =========================================================================

    async def _execute_do(self, task_name: str, task_spec: dict[str, Any], raw_input: Any) -> Any:
        """Execute a 'do' task — sequential sub-task list."""
        sub_tasks = task_spec["do"]
        if not isinstance(sub_tasks, list):
            raise DslExecutionError(task_name, "'do' must be a list of sub-tasks")

        # Execute sub-tasks via recursive call
        sub_executor = DslExecutor(self._context)
        sub_result = await sub_executor.execute(sub_tasks, initial_context=self._workflow_context)

        if not sub_result.success:
            raise DslExecutionError(task_name, f"Sub-task failed: {sub_result.error} (at: {sub_result.failed_task})")

        # Update our context with sub-executor's accumulated context
        self._workflow_context.update(sub_result.context)
        return sub_result.context

    # =========================================================================
    # set — Update context variables
    # =========================================================================

    def _execute_set(self, task_name: str, task_spec: dict[str, Any], raw_input: Any) -> dict[str, Any]:
        """Execute a 'set' task — merge key-value pairs into context."""
        set_values = task_spec["set"]
        if not isinstance(set_values, dict):
            raise DslExecutionError(task_name, "'set' must be a dict of key-value pairs")

        resolved: dict[str, Any] = {}
        variables = self._jq_variables(raw_input)

        for key, value in set_values.items():
            if is_expression(value):
                try:
                    resolved[key] = resolve_value(value, raw_input, variables)
                except JqEvaluationError as e:
                    raise DslExecutionError(task_name, f"Failed to evaluate set.{key}: {e.detail}")
            else:
                resolved[key] = value

        # Merge into workflow context
        self._workflow_context.update(resolved)
        return self._workflow_context

    # =========================================================================
    # try — Error handling with retry
    # =========================================================================

    async def _execute_try(self, task_name: str, task_spec: dict[str, Any], raw_input: Any) -> Any:
        """Execute a 'try' task — attempt with error handling and retry."""
        try_task = task_spec["try"]
        catch_spec = task_spec.get("catch", {})

        # Retry configuration
        retry_spec = catch_spec.get("retry", {})
        max_attempts = 1
        retry_limit = retry_spec.get("limit", {})
        if isinstance(retry_limit, dict):
            attempt_config = retry_limit.get("attempt", {})
            if isinstance(attempt_config, dict):
                max_attempts = attempt_config.get("count", 1)

        delay_spec = retry_spec.get("delay", {})
        base_delay = delay_spec.get("seconds", 1) if isinstance(delay_spec, dict) else 1

        backoff_spec = retry_spec.get("backoff", {})
        use_exponential = "exponential" in backoff_spec if isinstance(backoff_spec, dict) else False

        # Attempt execution with retries
        last_error: str | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                # try_task is a task spec (inline task definition)
                if isinstance(try_task, dict):
                    return await self._execute_task(task_name, try_task, raw_input)
                else:
                    raise DslExecutionError(task_name, "'try' value must be a task spec dict")
            except DslExecutionError as e:
                last_error = e.detail
                self._logger.warning("try task '%s' attempt %d/%d failed: %s", task_name, attempt, max_attempts, e.detail)

                if attempt < max_attempts:
                    # Calculate delay
                    delay = base_delay * (2 ** (attempt - 1)) if use_exponential else base_delay
                    await asyncio.sleep(delay)
                    continue

        # All retries exhausted — execute catch.do fallback if provided
        catch_tasks = catch_spec.get("do")
        if catch_tasks and isinstance(catch_tasks, list):
            self._logger.info("Executing catch.do fallback for task '%s'", task_name)
            # Make $error available in context
            self._workflow_context["_error"] = {"task": task_name, "detail": last_error}
            sub_executor = DslExecutor(self._context)
            sub_result = await sub_executor.execute(catch_tasks, initial_context=self._workflow_context)
            self._workflow_context.pop("_error", None)
            if sub_result.success:
                self._workflow_context.update(sub_result.context)
                return sub_result.context

        # No fallback or fallback failed
        raise DslExecutionError(task_name, f"try exhausted {max_attempts} attempts: {last_error}")

    # =========================================================================
    # Helpers
    # =========================================================================

    def _resolve_task_input(self, task_name: str, task_spec: dict[str, Any], raw_input: Any) -> Any:
        """Resolve task input from 'with' arguments and 'input.from' transform."""
        variables = self._jq_variables(raw_input)

        # 'with' — resolve each argument
        with_args = task_spec.get("with")
        if with_args and isinstance(with_args, dict):
            try:
                return resolve_object(with_args, raw_input, variables)
            except JqEvaluationError as e:
                raise DslExecutionError(task_name, f"'with' argument evaluation failed: {e.detail}")

        # 'input.from' — apply jq transform
        input_spec = task_spec.get("input")
        if input_spec and isinstance(input_spec, dict) and "from" in input_spec:
            try:
                return resolve_value(input_spec["from"], raw_input, variables)
            except JqEvaluationError as e:
                raise DslExecutionError(task_name, f"'input.from' evaluation failed: {e.detail}")

        # Default: pass raw_input as-is
        return raw_input if isinstance(raw_input, dict) else {}

    def _jq_variables(self, current_output: Any = None) -> dict[str, Any]:
        """Build the jq variable dict for expression evaluation."""
        return {
            "context": self._workflow_context,
            "input": current_output if isinstance(current_output, (dict, list)) else {},
            "output": current_output if isinstance(current_output, (dict, list)) else {},
        }
