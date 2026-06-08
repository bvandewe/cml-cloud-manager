"""Suspended Step Watchdog Service (Phase 3 / Q-10).

Background leader-gated service that detects orphaned SE-suspended pipeline
steps (no CloudEvent callback arrived within the configured timeout window)
and fails them via CPA so the session can recover.

Problem Solved
--------------
With ``SCENARIO_ENGINE_INTEGRATION_ENABLED=true`` (Phase 3 Tier-B delegation),
a pipeline step that delegates to scenario-engine returns ``StepResult.suspended``
and the controller drops its in-process task. Resumption happens reactively
via :class:`EventsController` when a job lifecycle CloudEvent arrives.

If SE crashes, the callback URL is unreachable, or the event is dropped on
the wire, the session can sit in ``status="suspended"`` forever. This watchdog
fills the gap: on each scan it lists active sessions, walks
``pipeline_progress``, and for any step that has been suspended longer than
``Settings.pipeline_external_step_default_timeout_seconds`` it calls
:meth:`ControlPlaneApiClient.fail_pipeline_step` with a timeout error and
then signals the in-process :class:`LifecyclePhaseHandler` (if registered)
so the reconciler picks the failure up.

Architecture
------------
- Runs as an independent asyncio loop under leader election.
- Started/stopped by :class:`LabletReconciler` in ``_become_leader`` /
  ``_step_down`` (same pattern as ``TimeslotWatcherService``).
- Reads sessions through :class:`ControlPlaneApiClient.get_lablet_sessions`
  (ADR-001 — CPA is sole MongoDB writer; this is a read-only consumer).
- Writes failures through :class:`ControlPlaneApiClient.fail_pipeline_step`
  (the same command :class:`EventsController` calls on ``job.failed``).

Idempotency
-----------
A scan can race a late-arriving CloudEvent: CPA's
``FailPipelineStepCommand`` already handles "step is already failed" by
overwriting the error message (treated as success). To avoid log spam from
re-flagging the same step on every interval before the leader observes the
fail, an in-memory ``_failed_step_keys`` set tracks
``f"{session_id}:{pipeline_name}:{step_name}"`` and skips re-fails for the
remainder of the leader term.

References
----------
- AD-CSI-009 — Suspension/resumption uses StepResult.suspended + CloudEvent
- AD-CSI-016 — In-process LifecyclePhaseHandler registry
- AD-CSI-017 — SE round-trips metadata on every job lifecycle CloudEvent
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from lcm_core.integration.clients import ControlPlaneApiClient
from lcm_core.integration.clients.control_plane_client import ControlPlaneApiClientError

from application.services.lifecycle_phase_handler import LifecyclePhaseHandler
from application.settings import Settings

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

logger = logging.getLogger(__name__)

# Statuses considered "active" for the purposes of orphan detection.
# Terminal statuses (ARCHIVED / TERMINATED) cannot have running pipelines.
_ACTIVE_STATUS_VALUES: tuple[str, ...] = (
    "SCHEDULED",
    "INSTANTIATING",
    "READY",
    "RUNNING",
    "COLLECTING",
    "GRADING",
    "STOPPING",
)


class SuspendedStepWatchdogService:
    """Periodic scanner that fails pipeline steps stuck in ``suspended``."""

    def __init__(
        self,
        api_client: ControlPlaneApiClient,
        settings: Settings,
    ) -> None:
        self._api = api_client
        self._settings = settings
        self._running = False
        self._task: asyncio.Task | None = None

        # Idempotency guard — already-failed step keys for this leader term.
        self._failed_step_keys: set[str] = set()

        # Stats (for /info admin endpoint)
        self._scan_count = 0
        self._suspended_steps_seen = 0
        self._steps_failed = 0
        self._handler_signals = 0
        self._last_scan_at: datetime | None = None
        self._last_error: str | None = None

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def start_async(self) -> None:
        """Start the watchdog loop (idempotent)."""
        if not self._settings.suspended_step_watchdog_enabled:
            logger.info("⏭️ SuspendedStepWatchdogService is disabled (suspended_step_watchdog_enabled=false)")
            return
        if self._settings.suspended_step_watchdog_interval_seconds <= 0:
            logger.info("⏭️ SuspendedStepWatchdogService is disabled (interval_seconds <= 0)")
            return
        if self._running:
            return

        logger.info(
            "🚀 Starting SuspendedStepWatchdogService (interval=%ds, timeout=%ds)",
            self._settings.suspended_step_watchdog_interval_seconds,
            self._settings.pipeline_external_step_default_timeout_seconds,
        )
        self._running = True
        # Reset idempotency state on each leader term — a new leader has no
        # context from the prior one's local memory.
        self._failed_step_keys.clear()
        self._task = asyncio.create_task(self._watch_loop(), name="suspended_step_watchdog_loop")

    async def stop_async(self) -> None:
        """Stop the watchdog loop and await task cancellation."""
        if not self._running:
            return
        logger.info("🛑 Stopping SuspendedStepWatchdogService...")
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(
            "✅ SuspendedStepWatchdogService stopped (scans=%d, failed=%d, signals=%d)",
            self._scan_count,
            self._steps_failed,
            self._handler_signals,
        )

    # =========================================================================
    # Main scan loop
    # =========================================================================

    async def _watch_loop(self) -> None:
        """Repeatedly scan active sessions until cancelled."""
        # Brief warm-up so reconciliation can settle on a new leader.
        await asyncio.sleep(5)

        while self._running:
            loop_start = datetime.now(timezone.utc)
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                logger.info("SuspendedStepWatchdogService loop cancelled")
                raise
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.exception("SuspendedStepWatchdogService scan failed: %s", exc)

            elapsed = (datetime.now(timezone.utc) - loop_start).total_seconds()
            sleep_time = max(0.0, self._settings.suspended_step_watchdog_interval_seconds - elapsed)
            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                raise

    async def scan_once(self) -> None:
        """Execute a single scan pass — listing sessions and failing stale steps.

        Public so tests can exercise the logic without driving the loop.
        """
        self._scan_count += 1
        self._last_scan_at = datetime.now(timezone.utc)

        sessions = await self._list_active_sessions()
        if not sessions:
            return

        timeout_seconds = self._settings.pipeline_external_step_default_timeout_seconds
        now = datetime.now(timezone.utc)

        for session in sessions:
            session_id = session.get("id")
            if not session_id:
                continue
            pipeline_progress = session.get("pipeline_progress") or {}
            if not isinstance(pipeline_progress, dict):
                continue

            for pipeline_name, steps in pipeline_progress.items():
                if not isinstance(steps, dict):
                    continue
                for step_name, step in steps.items():
                    if not isinstance(step, dict):
                        continue
                    if step.get("status") != "suspended":
                        continue
                    self._suspended_steps_seen += 1

                    key = f"{session_id}:{pipeline_name}:{step_name}"
                    if key in self._failed_step_keys:
                        continue  # Already failed this term — skip until leader churn.

                    age_seconds = self._compute_age_seconds(step.get("suspended_at"), now)
                    if age_seconds is None:
                        # suspended_at missing or unparseable — log once and skip.
                        logger.warning(
                            "Suspended step %s has no usable suspended_at (step=%s); skipping watchdog.",
                            key,
                            step,
                        )
                        self._failed_step_keys.add(key)
                        continue
                    if age_seconds < timeout_seconds:
                        continue  # Still within budget — leave it alone.

                    await self._fail_step(
                        session_id=session_id,
                        pipeline_name=pipeline_name,
                        step_name=step_name,
                        step=step,
                        age_seconds=age_seconds,
                        timeout_seconds=timeout_seconds,
                    )
                    self._failed_step_keys.add(key)

    # =========================================================================
    # Internals
    # =========================================================================

    async def _list_active_sessions(self) -> list[dict[str, Any]]:
        """Aggregate ``get_lablet_sessions`` across all active statuses.

        ``ControlPlaneApiClient.get_lablet_sessions`` only accepts a single
        status filter, so we fan out one request per active status. Errors
        per-status are logged and skipped so a single CPA hiccup doesn't
        stall the whole scan.
        """
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for status in _ACTIVE_STATUS_VALUES:
            try:
                page = await self._api.get_lablet_sessions(status=status, include_terminated=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Watchdog: get_lablet_sessions(status=%s) failed: %s", status, exc)
                continue
            for sess in page:
                sid = sess.get("id")
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    results.append(sess)
        return results

    @staticmethod
    def _compute_age_seconds(suspended_at_raw: Any, now: datetime) -> float | None:
        """Parse ``suspended_at`` (ISO 8601 string) and return age in seconds."""
        if not isinstance(suspended_at_raw, str):
            return None
        # Normalise trailing 'Z' → '+00:00' for fromisoformat.
        value = suspended_at_raw.rstrip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            suspended_at = datetime.fromisoformat(value)
        except ValueError:
            return None
        if suspended_at.tzinfo is None:
            suspended_at = suspended_at.replace(tzinfo=timezone.utc)
        return (now - suspended_at).total_seconds()

    async def _fail_step(
        self,
        *,
        session_id: str,
        pipeline_name: str,
        step_name: str,
        step: dict[str, Any],
        age_seconds: float,
        timeout_seconds: int,
    ) -> None:
        """Issue ``fail_pipeline_step`` and signal the in-process handler."""
        correlation_id = step.get("step_correlation_id")
        if not correlation_id:
            logger.warning(
                "Suspended step %s:%s:%s missing step_correlation_id; cannot fail via CPA — skipping.",
                session_id,
                pipeline_name,
                step_name,
            )
            return

        error_message = f"timeout: no scenario-engine callback within {timeout_seconds}s " f"(actual age={int(age_seconds)}s)"
        details = {
            "timeout_seconds": timeout_seconds,
            "age_seconds": int(age_seconds),
            "external_job_id": step.get("external_job_id"),
            "pipeline_name": pipeline_name,
            "step_name": step_name,
            "watchdog": True,
        }

        try:
            cpa_result = await self._api.fail_pipeline_step(
                session_id=session_id,
                pipeline_name=pipeline_name,
                step_correlation_id=correlation_id,
                error=error_message,
                details=details,
            )
        except ControlPlaneApiClientError as exc:
            # 404 → session/step already gone (idempotency); other errors retry next scan.
            if getattr(exc, "status_code", None) == 404:
                logger.info(
                    "Watchdog: CPA reports session/step %s gone (404); marking as handled.",
                    f"{session_id}:{pipeline_name}:{step_name}",
                )
                return
            logger.warning(
                "Watchdog: fail_pipeline_step failed for %s:%s:%s: %s",
                session_id,
                pipeline_name,
                step_name,
                exc,
            )
            # Don't add to _failed_step_keys → retry on next interval.
            raise

        self._steps_failed += 1
        logger.warning(
            "⏱️  Watchdog failed orphaned suspended step %s:%s:%s after %ds (external_job=%s).",
            session_id,
            pipeline_name,
            step_name,
            int(age_seconds),
            step.get("external_job_id"),
        )

        # Signal the in-process handler (AD-CSI-016). When the leader controller
        # is the same instance that suspended the step, the handler is still
        # registered and a direct call resumes faster than waiting for the next
        # reconciliation cycle.
        await self._signal_handler_fail(session_id, cpa_result)

    async def _signal_handler_fail(self, session_id: str, cpa_result: dict[str, Any]) -> None:
        """Best-effort: notify the in-process LifecyclePhaseHandler of failure."""
        handler = LifecyclePhaseHandler.lookup(session_id)
        if handler is None:
            # No handler registered — controller restart or wrong leader.
            # The next reconcile pass will observe the failure in CPA state
            # and proceed (AD-CSI-016 fall-back).
            return
        progress = cpa_result.get("pipeline_progress") or {}
        try:
            await handler.fail_after_external_completion(progress)
            self._handler_signals += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Watchdog: handler signal failed for session %s: %s",
                session_id,
                exc,
            )

    # =========================================================================
    # Stats / DI
    # =========================================================================

    def get_stats(self) -> dict[str, Any]:
        return {
            "enabled": self._settings.suspended_step_watchdog_enabled,
            "running": self._running,
            "interval_seconds": self._settings.suspended_step_watchdog_interval_seconds,
            "timeout_seconds": self._settings.pipeline_external_step_default_timeout_seconds,
            "scan_count": self._scan_count,
            "suspended_steps_seen": self._suspended_steps_seen,
            "steps_failed": self._steps_failed,
            "handler_signals": self._handler_signals,
            "tracked_failed_keys": len(self._failed_step_keys),
            "last_scan_at": self._last_scan_at.isoformat() if self._last_scan_at else None,
            "last_error": self._last_error,
        }

    @classmethod
    def configure(cls, services: ServiceCollection) -> None:
        """Register as a singleton (lifecycle managed by LabletReconciler)."""

        def factory(sp):
            return cls(
                api_client=sp.get_required_service(ControlPlaneApiClient),
                settings=sp.get_required_service(Settings),
            )

        services.add_singleton(cls, implementation_factory=factory)
