"""Pipeline executor — DAG-based step orchestration engine.

ADR-034: Replaces the monolithic _handle_instantiating() one-step-per-reconcile
pattern with a self-driving DAG executor that:
- Topologically sorts steps via ``graphlib.TopologicalSorter``
- Evaluates ``skip_when`` expressions via simpleeval
- Supports per-step retry with backoff
- Enforces per-step timeout via asyncio.wait_for()
- Persists progress after each step via CPA API
- Resolves pipeline outputs via dot-path expressions

The executor does NOT import LabletReconciler. It receives a ``StepDispatcher``
callable that maps handler names to async functions, keeping the executor
fully testable in isolation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from graphlib import CycleError, TopologicalSorter
from typing import Any

from simpleeval import InvalidExpression, SimpleEval

from application.models.pipeline_context import PipelineContext
from application.models.pipeline_result import PipelineResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# Step dispatcher: receives (handler_name, session, progress_dict, context, params) → result_data dict
# ADR-038: context and params added to support registry-based handlers and
# parameterized steps (e.g. execute_command_on_cml_node).
StepDispatcher = Callable[..., Awaitable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PipelineDefinitionError(Exception):
    """Raised when a pipeline definition is structurally invalid (e.g. cycle)."""


class PipelineStepError(Exception):
    """Raised when a required step fails and the pipeline cannot continue."""

    def __init__(self, step_name: str, message: str) -> None:
        self.step_name = step_name
        super().__init__(f"Step '{step_name}' failed: {message}")


# ---------------------------------------------------------------------------
# PipelineExecutor
# ---------------------------------------------------------------------------


class PipelineExecutor:
    """DAG-based pipeline execution engine.

    Usage::

        executor = PipelineExecutor()
        result = await executor.execute(
            pipeline_def=definition.pipelines["instantiate"],
            context=pipeline_context,
            step_dispatcher=reconciler_dispatch_fn,
        )

    Args:
        max_parallel: Reserved for future parallel execution within a DAG level.
                      Currently unused — steps execute sequentially per topological order.
    """

    def __init__(self, max_parallel: int = 1) -> None:
        self._max_parallel = max_parallel

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self,
        pipeline_def: dict[str, Any],
        context: PipelineContext,
        step_dispatcher: StepDispatcher,
        existing_progress: dict[str, Any] | None = None,
        pipeline_name: str | None = None,
    ) -> PipelineResult:
        """Execute a full pipeline DAG.

        Args:
            pipeline_def: The pipeline definition dict (from YAML ``pipelines.<name>``).
            context: Execution context with session, definition, services, accumulated data.
            step_dispatcher: Async callable ``(handler_name, session, progress) -> result_data``.
            existing_progress: Optional progress from a previous run for resumability.
                Steps with status "completed" or "skipped" are skipped; their result_data
                is restored into context.steps_data. Steps with "failed", "pending", or
                "in_progress" are re-executed.
            pipeline_name: Pipeline key name (e.g. "instantiate", "teardown"). Used
                for generic pipeline progress persistence (ADR-034 Sprint E). If None,
                falls back to instantiation-specific progress endpoint.

        Returns:
            PipelineResult with completion stats, resolved outputs, and any error.
        """
        pipeline_label = pipeline_def.get("description", "unnamed")
        steps: list[dict[str, Any]] = pipeline_def.get("steps", [])
        output_defs: dict[str, str] = pipeline_def.get("outputs", {})
        max_retries: int = pipeline_def.get("max_retries", 0)

        if not steps:
            return PipelineResult(
                pipeline_name=pipeline_label,
                status="completed",
                duration_seconds=0.0,
                max_retries=max_retries,
            )

        # Validate and topologically sort
        ordered_steps = self._resolve_dag(steps)

        # Build resumability index from existing progress
        resume_statuses: dict[str, dict[str, Any]] = {}
        if existing_progress:
            # existing_progress may be a flat dict {step_name: {status, result_data, ...}}
            # or a legacy dict with a "steps" list
            if "steps" in existing_progress and isinstance(existing_progress["steps"], list):
                for s in existing_progress["steps"]:
                    step_name = s.get("step", s.get("name", ""))
                    if step_name:
                        resume_statuses[step_name] = s
            else:
                for step_name, step_info in existing_progress.items():
                    if isinstance(step_info, dict) and "status" in step_info:
                        resume_statuses[step_name] = step_info

        t0 = time.monotonic()
        completed = 0
        failed = 0
        skipped = 0
        step_statuses: dict[str, str] = {}  # step_name → "completed"|"failed"|"skipped"
        error_message: str | None = None

        # Build the progress dict for CPA persistence
        progress = self._build_initial_progress(ordered_steps)

        for step in ordered_steps:
            step_name: str = step["name"]
            is_optional: bool = step.get("optional", False)
            needs: list[str] = step.get("needs", [])

            # ----------------------------------------------------------
            # Resumability: skip already-completed/skipped steps
            # ----------------------------------------------------------
            prev = resume_statuses.get(step_name)
            if prev:
                prev_status = prev.get("status", prev.get("step_status", ""))
                if prev_status == "completed":
                    # Restore result_data into context for downstream steps
                    prev_result = prev.get("result_data", {})
                    if prev_result:
                        context.steps_data[step_name] = prev_result
                    step_statuses[step_name] = "completed"
                    completed += 1
                    progress[step_name] = {"status": "completed", "result_data": prev_result}
                    logger.info("Pipeline step '%s' already completed (resumed) — skipping", step_name)
                    continue
                elif prev_status == "skipped":
                    step_statuses[step_name] = "skipped"
                    skipped += 1
                    progress[step_name] = {"status": "skipped", "reason": "previously skipped"}
                    logger.info("Pipeline step '%s' already skipped (resumed) — skipping", step_name)
                    continue
                # "failed", "pending", "in_progress" → re-execute below

            # ----------------------------------------------------------
            # Check if upstream dependencies are satisfied
            # ----------------------------------------------------------
            upstream_blocked = False
            for dep in needs:
                dep_status = step_statuses.get(dep)
                if dep_status == "failed":
                    # Check if the failed dependency was optional AND no other
                    # non-optional downstream step also depends on it
                    dep_step = self._find_step(steps, dep)
                    if dep_step and dep_step.get("optional", False):
                        # Optional upstream failed — skip this step too unless
                        # this step has other satisfied dependencies
                        continue
                    upstream_blocked = True
                    break
                elif dep_status == "skipped":
                    # Skipped dependency — step can still proceed
                    continue

            if upstream_blocked:
                step_statuses[step_name] = "skipped"
                skipped += 1
                progress[step_name] = {"status": "skipped", "reason": f"upstream '{dep}' failed"}
                await self._persist_progress(context, step_name, "skipped", pipeline_name=pipeline_name)
                logger.info("Pipeline step '%s' skipped — upstream dependency '%s' failed", step_name, dep)
                continue

            # ----------------------------------------------------------
            # Evaluate skip_when
            # ----------------------------------------------------------
            skip_expr = step.get("skip_when")
            if skip_expr and self._evaluate_skip(skip_expr, context):
                step_statuses[step_name] = "skipped"
                skipped += 1
                progress[step_name] = {"status": "skipped", "reason": f"skip_when: {skip_expr}"}
                await self._persist_progress(context, step_name, "skipped", pipeline_name=pipeline_name)
                logger.info("Pipeline step '%s' skipped — skip_when evaluated to True", step_name)
                continue

            # ----------------------------------------------------------
            # Execute with retry and timeout
            # ----------------------------------------------------------
            try:
                result_data = await self._execute_step(step, context, step_dispatcher, progress)

                # ----------------------------------------------------------
                # Honor step handler's reported status
                # ----------------------------------------------------------
                # Step handlers may return {"status": "skipped"} or
                # {"status": "failed", "error": "..."} to signal non-completion
                # without raising exceptions. The executor must propagate these
                # statuses instead of blindly marking everything "completed".
                handler_status = result_data.get("status") if isinstance(result_data, dict) else None

                if handler_status == "skipped":
                    # Step handler decided to skip (e.g. no port_template)
                    step_statuses[step_name] = "skipped"
                    skipped += 1
                    context.steps_data[step_name] = result_data
                    reason = result_data.get("reason", "step handler returned skipped")
                    progress[step_name] = {"status": "skipped", "reason": reason, "result_data": result_data}
                    await self._persist_progress(context, step_name, "skipped", pipeline_name=pipeline_name)
                    logger.info("Pipeline step '%s' skipped by handler: %s", step_name, reason)

                elif handler_status == "failed":
                    # Step handler reports failure via return value (not exception)
                    handler_error = result_data.get("error", "step handler returned failed")
                    step_statuses[step_name] = "failed"
                    failed += 1
                    progress[step_name] = {"status": "failed", "error": handler_error, "result_data": result_data}
                    await self._persist_progress(context, step_name, "failed", error=handler_error, pipeline_name=pipeline_name)

                    if is_optional:
                        logger.warning("Optional pipeline step '%s' failed (handler): %s — continuing", step_name, handler_error)
                    else:
                        error_message = f"Required step '{step_name}' failed: {handler_error}"
                        logger.error("Pipeline aborted: %s", error_message)
                        for remaining in ordered_steps:
                            rname = remaining["name"]
                            if rname not in step_statuses:
                                step_statuses[rname] = "skipped"
                                skipped += 1
                                progress[rname] = {"status": "skipped", "reason": "pipeline aborted"}
                                await self._persist_progress(context, rname, "skipped", pipeline_name=pipeline_name)
                        break

                else:
                    # Normal completion (status is "completed" or unset)
                    step_statuses[step_name] = "completed"
                    completed += 1
                    context.steps_data[step_name] = result_data
                    progress[step_name] = {"status": "completed", "result_data": result_data}
                    await self._persist_progress(context, step_name, "completed", result_data=result_data, pipeline_name=pipeline_name)
                    logger.info("Pipeline step '%s' completed successfully", step_name)

            except Exception as exc:
                step_statuses[step_name] = "failed"
                failed += 1
                exc_msg = str(exc)
                progress[step_name] = {"status": "failed", "error": exc_msg}
                await self._persist_progress(context, step_name, "failed", error=exc_msg, pipeline_name=pipeline_name)

                if is_optional:
                    logger.warning("Optional pipeline step '%s' failed: %s — continuing", step_name, exc_msg)
                else:
                    error_message = f"Required step '{step_name}' failed: {exc_msg}"
                    logger.error("Pipeline aborted: %s", error_message)
                    # Mark remaining steps as skipped
                    for remaining in ordered_steps:
                        rname = remaining["name"]
                        if rname not in step_statuses:
                            step_statuses[rname] = "skipped"
                            skipped += 1
                            progress[rname] = {"status": "skipped", "reason": "pipeline aborted"}
                            await self._persist_progress(context, rname, "skipped", pipeline_name=pipeline_name)
                    break

        elapsed = time.monotonic() - t0

        # Determine terminal status
        if error_message:
            status = "failed"
        elif failed > 0:
            status = "partial"  # Some optional steps failed
        else:
            status = "completed"

        # Resolve outputs
        outputs = self._resolve_outputs(output_defs, context.steps_data)

        return PipelineResult(
            pipeline_name=pipeline_label,
            status=status,
            steps_completed=completed,
            steps_failed=failed,
            steps_skipped=skipped,
            duration_seconds=round(elapsed, 3),
            outputs=outputs,
            error=error_message,
            max_retries=max_retries,
        )

    # ------------------------------------------------------------------
    # DAG Resolution (Kahn's Algorithm)
    # ------------------------------------------------------------------

    def _resolve_dag(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Topologically sort pipeline steps using graphlib.TopologicalSorter.

        Args:
            steps: List of step definitions, each with ``name`` and optional ``needs``.

        Returns:
            Steps in topologically sorted order (dependencies first).

        Raises:
            PipelineDefinitionError: If the DAG contains a cycle or references unknown steps.
        """
        step_map: dict[str, dict[str, Any]] = {}
        graph: dict[str, set[str]] = {}

        # 1. Map steps and build the dependency graph
        for step in steps:
            name = step["name"]
            if name in step_map:
                raise PipelineDefinitionError(f"Duplicate step name: '{name}'")
            step_map[name] = step
            # graphlib expects {node: {predecessors}}
            graph[name] = set(step.get("needs", []))

        # 2. Validate that all declared dependencies exist in the pipeline
        known_steps = set(step_map.keys())
        for name, deps in graph.items():
            unknown = deps - known_steps
            if unknown:
                # Preserve original error message format for single unknown dep
                if len(unknown) == 1:
                    raise PipelineDefinitionError(f"Step '{name}' depends on unknown step '{next(iter(unknown))}'")
                raise PipelineDefinitionError(f"Step '{name}' depends on unknown step(s): {', '.join(sorted(unknown))}")

        # 3. Execute topological sort
        sorter = TopologicalSorter(graph)
        try:
            ordered_names = list(sorter.static_order())
        except CycleError as exc:
            cycle_nodes = ", ".join(str(n) for n in exc.args[1])
            raise PipelineDefinitionError(f"Cycle detected among steps: [{cycle_nodes}]") from exc

        # 4. Reconstruct the ordered list of step definitions
        return [step_map[name] for name in ordered_names]

    # ------------------------------------------------------------------
    # Skip-When Evaluation
    # ------------------------------------------------------------------

    def _evaluate_skip(self, expression: str, context: PipelineContext) -> bool:
        """Evaluate a ``skip_when`` expression using simpleeval.

        Variable references prefixed with ``$`` are mapped to context attributes.
        The ``$`` prefix is stripped before evaluation since Python's AST parser
        does not support ``$`` in identifiers:

        - ``$SESSION.<attr>`` → ``SESSION.<attr>`` → context.session.<attr>
        - ``$DEFINITION.<attr>`` → ``DEFINITION.<attr>`` → context.definition.<attr>
        - ``$WORKER.ip`` → ``WORKER.ip`` → context.worker_ip
        - ``$STEPS.<step>.<field>`` → ``STEPS.<step>.<field>`` → context.steps_data[step][field]

        Args:
            expression: The simpleeval expression string (with ``$`` prefixes).
            context: Pipeline execution context.

        Returns:
            True if the step should be skipped, False otherwise.
        """
        # Strip $ prefix from variable references — Python AST cannot parse $
        cleaned_expr = expression.replace("$DEFINITION", "DEFINITION").replace("$SESSION", "SESSION").replace("$WORKER", "WORKER").replace("$STEPS", "STEPS")

        evaluator = SimpleEval()

        # Build names dict from context (without $ prefix)
        names: dict[str, Any] = {}

        if hasattr(context, "definition") and context.definition is not None:
            names["DEFINITION"] = context.definition
        if hasattr(context, "session") and context.session is not None:
            names["SESSION"] = context.session
        names["WORKER"] = type("Worker", (), {"ip": context.worker_ip})()
        names["STEPS"] = context.steps_data

        evaluator.names = names

        try:
            result = evaluator.eval(cleaned_expr)
            return bool(result)
        except (InvalidExpression, SyntaxError, TypeError, AttributeError, KeyError) as exc:
            logger.warning("skip_when expression '%s' evaluation failed: %s — treating as False (do not skip)", expression, exc)
            return False

    # ------------------------------------------------------------------
    # Step Execution (Retry + Timeout)
    # ------------------------------------------------------------------

    async def _execute_step(
        self,
        step: dict[str, Any],
        context: PipelineContext,
        step_dispatcher: StepDispatcher,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a single step with retry and timeout support.

        Args:
            step: Step definition dict.
            context: Pipeline context.
            step_dispatcher: Async callable to dispatch the step handler.
            progress: Current progress dict for the pipeline.

        Returns:
            Result data dict from the step handler.

        Raises:
            asyncio.TimeoutError: If the step exceeds its timeout.
            PipelineStepError: If the step exhausts all retry attempts.
        """
        step_name: str = step["name"]
        handler_name: str = step.get("handler", step_name)
        timeout_seconds: int | None = step.get("timeout_seconds")
        retry_config: dict[str, Any] | None = step.get("retry")
        step_params: dict[str, Any] | None = step.get("params")  # ADR-038: per-step YAML params

        max_attempts = 1
        delay_seconds = 0
        if retry_config:
            max_attempts = retry_config.get("max_attempts", 1)
            delay_seconds = retry_config.get("delay_seconds", 0)

        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                progress[step_name] = {"status": "in_progress", "attempt": attempt}

                # ADR-038: Pass context and params to dispatcher for registry-based handlers
                coro = step_dispatcher(handler_name, context.session, progress, context, step_params)

                if timeout_seconds:
                    result = await asyncio.wait_for(coro, timeout=timeout_seconds)
                else:
                    result = await coro

                # Validate result shape
                if not isinstance(result, dict):
                    result = {"result": result}

                return result

            except asyncio.TimeoutError:
                last_error = asyncio.TimeoutError(f"Step '{step_name}' timed out after {timeout_seconds}s (attempt {attempt}/{max_attempts})")
                logger.warning("Step '%s' timed out (attempt %d/%d)", step_name, attempt, max_attempts)
            except Exception as exc:
                last_error = exc
                logger.warning("Step '%s' failed (attempt %d/%d): %s", step_name, attempt, max_attempts, exc)

            # Wait before retry (except on last attempt)
            if attempt < max_attempts and delay_seconds > 0:
                logger.info("Retrying step '%s' in %ds...", step_name, delay_seconds)
                await asyncio.sleep(delay_seconds)

        # All attempts exhausted
        raise PipelineStepError(step_name, str(last_error))

    # ------------------------------------------------------------------
    # Output Resolution
    # ------------------------------------------------------------------

    def _resolve_outputs(self, output_defs: dict[str, str], steps_data: dict[str, dict]) -> dict[str, Any]:
        """Resolve pipeline output expressions to concrete values.

        Expressions use dot-path syntax: ``$STEPS.<step_name>.<field_name>``

        Args:
            output_defs: Mapping of output name → expression string.
            steps_data: Accumulated step result data.

        Returns:
            Dict of resolved output values.
        """
        outputs: dict[str, Any] = {}

        for key, expr in output_defs.items():
            try:
                value = self._resolve_dot_path(expr, steps_data)
                outputs[key] = value
            except (KeyError, IndexError, TypeError) as exc:
                logger.warning("Output '%s' resolution failed for expression '%s': %s", key, expr, exc)
                outputs[key] = None

        return outputs

    def _resolve_dot_path(self, expression: str, steps_data: dict[str, dict]) -> Any:
        """Resolve a single dot-path expression.

        Format: ``$STEPS.<step_name>.<field_name>[.<nested_field>]*``

        Args:
            expression: Dot-path expression string.
            steps_data: Accumulated step result data.

        Returns:
            The resolved value, or None if the path cannot be resolved.
        """
        # Strip leading/trailing whitespace and quotes
        expr = expression.strip().strip("'\"")

        if not expr.startswith("$STEPS."):
            logger.warning("Output expression '%s' does not start with '$STEPS.' — returning None", expr)
            return None

        # Remove $STEPS. prefix and split
        parts = expr[len("$STEPS.") :].split(".")
        if len(parts) < 2:
            return None

        step_name = parts[0]
        field_path = parts[1:]

        # Navigate into steps_data
        data: Any = steps_data.get(step_name)
        if data is None:
            return None

        for part in field_path:
            if isinstance(data, dict):
                data = data.get(part)
            elif hasattr(data, part):
                data = getattr(data, part)
            else:
                return None

            if data is None:
                return None

        return data

    # ------------------------------------------------------------------
    # Progress Helpers
    # ------------------------------------------------------------------

    def _build_initial_progress(self, ordered_steps: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the initial progress dict with all steps set to 'pending'.

        Args:
            ordered_steps: Topologically sorted step definitions.

        Returns:
            Dict mapping step name → status dict.
        """
        progress: dict[str, Any] = {}
        for i, step in enumerate(ordered_steps):
            progress[step["name"]] = {
                "status": "pending",
                "order": i,
            }
        return progress

    async def _persist_progress(
        self,
        context: PipelineContext,
        step_name: str,
        step_status: str,
        result_data: dict[str, Any] | None = None,
        error: str | None = None,
        pipeline_name: str | None = None,
    ) -> None:
        """Persist a single step's progress to CPA via the API client.

        Uses the generic pipeline progress endpoint (ADR-034 Sprint E).
        pipeline_name is required; defaults to "unnamed" if not provided.

        Args:
            context: Pipeline context with API client.
            step_name: Name of the pipeline step.
            step_status: Status of the step ("completed", "failed", "skipped").
            result_data: Optional result payload for completed steps.
            error: Optional error message for failed steps.
            pipeline_name: Pipeline key name (e.g. "instantiate", "teardown").
        """
        try:
            await context.api.update_pipeline_progress(
                session_id=context.session.id,
                pipeline_name=pipeline_name or "unnamed",
                step_name=step_name,
                step_status=step_status,
                result_data=result_data,
                error=error,
            )
        except Exception as exc:
            logger.warning("Failed to persist pipeline progress for session '%s' step '%s': %s", context.session.id, step_name, exc)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_step(steps: list[dict[str, Any]], step_name: str) -> dict[str, Any] | None:
        """Find a step definition by name in the original step list."""
        for step in steps:
            if step["name"] == step_name:
                return step
        return None
