"""Unit tests for InstantiationProgress value object (ADR-031).

Tests cover:
- StepResult: serialization round-trip, default values
- InstantiationProgress: DAG dependency resolution, next_executable_step(),
  step status transitions, completion detection, build_default() factory,
  serialization, progress counting

Pipeline steps (9 total — DAG order):
  content_sync → variables → lab_resolve → ports_alloc → tags_sync →
  lab_binding → lab_start → lds_provision → mark_ready

Pattern: Pure value object tests, no mocks needed.
"""

from datetime import datetime, timezone

import pytest
from domain.value_objects.instantiation_progress import InstantiationProgress, StepResult

# =============================================================================
# StepResult Tests
# =============================================================================


@pytest.mark.unit
class TestStepResult:
    """Tests for StepResult value object."""

    def test_default_status_is_pending(self) -> None:
        """New steps default to 'pending' status."""
        step = StepResult(step="lab_resolve")

        assert step.status == "pending"
        assert step.requires == []
        assert step.completed_at is None
        assert step.result_data is None
        assert step.error is None
        assert step.attempt_count == 0

    def test_serialization_round_trip(self) -> None:
        """to_dict() → from_dict() preserves all fields."""
        now = datetime.now(timezone.utc)
        step = StepResult(
            step="ports_alloc",
            status="completed",
            requires=["lab_resolve"],
            completed_at=now,
            result_data={"allocated": {"serial_1": 5041}},
            error=None,
            attempt_count=2,
        )
        data = step.to_dict()
        restored = StepResult.from_dict(data)

        assert restored.step == "ports_alloc"
        assert restored.status == "completed"
        assert restored.requires == ["lab_resolve"]
        assert restored.completed_at is not None
        assert restored.result_data == {"allocated": {"serial_1": 5041}}
        assert restored.attempt_count == 2

    def test_from_dict_defaults(self) -> None:
        """from_dict() fills in defaults for missing fields."""
        data = {"step": "lab_start"}
        step = StepResult.from_dict(data)

        assert step.step == "lab_start"
        assert step.status == "pending"
        assert step.requires == []
        assert step.completed_at is None
        assert step.attempt_count == 0

    def test_from_dict_parses_iso_datetime(self) -> None:
        """from_dict() parses ISO datetime strings for completed_at."""
        data = {
            "step": "mark_ready",
            "status": "completed",
            "completed_at": "2026-03-02T10:00:00+00:00",
        }
        step = StepResult.from_dict(data)

        assert isinstance(step.completed_at, datetime)
        assert step.completed_at.year == 2026

    def test_failed_step_carries_error(self) -> None:
        """A failed step stores the error message."""
        step = StepResult(step="lab_resolve", status="failed", error="CML API timeout")

        assert step.status == "failed"
        assert step.error == "CML API timeout"


# =============================================================================
# InstantiationProgress — Build Default Factory
# =============================================================================


@pytest.mark.unit
class TestBuildDefault:
    """Tests for InstantiationProgress.build_default() factory."""

    def test_minimal_pipeline_has_9_steps(self) -> None:
        """build_default() with no capabilities produces 9 steps."""
        progress = InstantiationProgress.build_default()

        assert progress.total_step_count == 9

    def test_step_names_match_pipeline(self) -> None:
        """Steps appear in the correct DAG order."""
        progress = InstantiationProgress.build_default(
            has_port_template=True,
            has_content_sync=True,
            has_lds=True,
        )
        step_names = [s.step for s in progress.steps]

        assert step_names == [
            "content_sync",
            "variables",
            "lab_resolve",
            "ports_alloc",
            "tags_sync",
            "lab_binding",
            "lab_start",
            "lds_provision",
            "mark_ready",
        ]

    def test_no_capabilities_skips_optional_steps(self) -> None:
        """Without capabilities, content_sync/variables/ports/tags/lds are skipped."""
        progress = InstantiationProgress.build_default(
            has_port_template=False,
            has_content_sync=False,
            has_lds=False,
        )
        skipped = {s.step for s in progress.steps if s.status == "skipped"}
        pending = {s.step for s in progress.steps if s.status == "pending"}

        assert "content_sync" in skipped
        assert "variables" in skipped  # always skipped (placeholder)
        assert "ports_alloc" in skipped
        assert "tags_sync" in skipped
        assert "lds_provision" in skipped

        # These are always pending
        assert "lab_resolve" in pending
        assert "lab_binding" in pending
        assert "lab_start" in pending
        assert "mark_ready" in pending

    def test_with_port_template_enables_port_steps(self) -> None:
        """has_port_template=True leaves ports_alloc and tags_sync as pending."""
        progress = InstantiationProgress.build_default(has_port_template=True)

        assert progress.get_step("ports_alloc").status == "pending"
        assert progress.get_step("tags_sync").status == "pending"

    def test_with_content_sync_enables_content_step(self) -> None:
        """has_content_sync=True leaves content_sync as pending."""
        progress = InstantiationProgress.build_default(has_content_sync=True)

        assert progress.get_step("content_sync").status == "pending"

    def test_with_lds_enables_lds_provision(self) -> None:
        """has_lds=True leaves lds_provision as pending."""
        progress = InstantiationProgress.build_default(has_lds=True)

        assert progress.get_step("lds_provision").status == "pending"

    def test_pipeline_version(self) -> None:
        """build_default() sets pipeline_version to '1.0'."""
        progress = InstantiationProgress.build_default()

        assert progress.pipeline_version == "1.0"

    def test_started_at_is_set(self) -> None:
        """build_default() sets started_at to current time."""
        progress = InstantiationProgress.build_default()

        assert progress.started_at is not None
        assert isinstance(progress.started_at, datetime)


# =============================================================================
# InstantiationProgress — DAG Dependency Resolution
# =============================================================================


@pytest.mark.unit
class TestDAGResolution:
    """Tests for next_executable_step() DAG traversal."""

    def test_first_step_no_capabilities(self) -> None:
        """With no capabilities, first executable step is lab_resolve (content_sync/variables skipped)."""
        progress = InstantiationProgress.build_default()
        next_step = progress.next_executable_step()

        assert next_step is not None
        assert next_step.step == "lab_resolve"

    def test_first_step_with_content_sync(self) -> None:
        """With content_sync enabled, it is the first executable step."""
        progress = InstantiationProgress.build_default(has_content_sync=True)
        next_step = progress.next_executable_step()

        assert next_step is not None
        assert next_step.step == "content_sync"

    def test_lab_resolve_requires_content_sync_and_variables(self) -> None:
        """lab_resolve is blocked until content_sync AND variables are satisfied."""
        progress = InstantiationProgress.build_default(has_content_sync=True)

        # content_sync is pending, so lab_resolve is blocked
        next_step = progress.next_executable_step()
        assert next_step.step == "content_sync"

        # Complete content_sync — lab_resolve should now be executable
        # (variables is already skipped)
        progress.complete_step("content_sync")
        next_step = progress.next_executable_step()
        assert next_step is not None
        assert next_step.step == "lab_resolve"

    def test_ports_alloc_requires_lab_resolve(self) -> None:
        """ports_alloc is blocked until lab_resolve is completed."""
        progress = InstantiationProgress.build_default(has_port_template=True)

        # lab_resolve is first executable
        next_step = progress.next_executable_step()
        assert next_step.step == "lab_resolve"

        # Complete lab_resolve — ports_alloc becomes executable
        progress.complete_step("lab_resolve")
        next_step = progress.next_executable_step()
        assert next_step.step == "ports_alloc"

    def test_lab_binding_requires_lab_resolve_and_tags_sync(self) -> None:
        """lab_binding requires both lab_resolve AND tags_sync to be satisfied."""
        progress = InstantiationProgress.build_default(has_port_template=True)

        # Walk through: lab_resolve → ports_alloc → tags_sync → lab_binding
        progress.complete_step("lab_resolve")
        progress.complete_step("ports_alloc")
        progress.complete_step("tags_sync")
        next_step = progress.next_executable_step()
        assert next_step is not None
        assert next_step.step == "lab_binding"

    def test_lab_binding_without_ports_skips_port_deps(self) -> None:
        """Without port template, tags_sync is skipped and lab_binding proceeds."""
        progress = InstantiationProgress.build_default(has_port_template=False)

        # tags_sync is skipped, lab_resolve → lab_binding
        progress.complete_step("lab_resolve")
        next_step = progress.next_executable_step()
        assert next_step.step == "lab_binding"

    def test_mark_ready_requires_lds_provision(self) -> None:
        """mark_ready is blocked until lds_provision is satisfied."""
        progress = InstantiationProgress.build_default(has_lds=True)

        # Walk through: lab_resolve → lab_binding → lab_start → lds_provision → mark_ready
        progress.complete_step("lab_resolve")
        progress.complete_step("lab_binding")
        progress.complete_step("lab_start")
        next_step = progress.next_executable_step()
        assert next_step.step == "lds_provision"

        progress.complete_step("lds_provision")
        next_step = progress.next_executable_step()
        assert next_step.step == "mark_ready"

    def test_mark_ready_without_lds(self) -> None:
        """Without LDS, lds_provision is skipped and mark_ready proceeds after lab_start."""
        progress = InstantiationProgress.build_default(has_lds=False)

        progress.complete_step("lab_resolve")
        progress.complete_step("lab_binding")
        progress.complete_step("lab_start")
        next_step = progress.next_executable_step()
        assert next_step.step == "mark_ready"

    def test_failed_step_blocks_dependents(self) -> None:
        """A failed step blocks all downstream steps that depend on it.

        Uses full capabilities so no steps are pre-skipped (except variables).
        Complete content_sync first so lab_resolve becomes eligible, then
        fail it — all downstream steps remain blocked.
        """
        progress = InstantiationProgress.build_default(
            has_port_template=True,
            has_content_sync=True,
            has_lds=True,
        )

        # Complete content_sync (prerequisite of lab_resolve)
        progress.complete_step("content_sync")

        # Now fail lab_resolve — everything downstream is blocked
        progress.fail_step("lab_resolve", "CML API timeout")
        next_step = progress.next_executable_step()
        assert next_step is None

    def test_none_when_all_complete(self) -> None:
        """next_executable_step() returns None when pipeline is complete."""
        progress = InstantiationProgress.build_default()

        # Complete all pending steps in order
        for step in progress.steps:
            if step.status == "pending":
                progress.complete_step(step.step)

        assert progress.next_executable_step() is None


# =============================================================================
# InstantiationProgress — Step Status Transitions
# =============================================================================


@pytest.mark.unit
class TestStepTransitions:
    """Tests for step status mutation helpers."""

    def test_complete_step(self) -> None:
        """complete_step() sets status, timestamp, and increments attempt_count."""
        progress = InstantiationProgress.build_default()

        progress.complete_step("lab_resolve", result_data={"cml_lab_id": "lab-99"})
        step = progress.get_step("lab_resolve")

        assert step.status == "completed"
        assert step.completed_at is not None
        assert step.result_data == {"cml_lab_id": "lab-99"}
        assert step.attempt_count == 1

    def test_fail_step(self) -> None:
        """fail_step() sets status, error, and increments attempt_count."""
        progress = InstantiationProgress.build_default()

        progress.fail_step("lab_resolve", "API timeout")
        step = progress.get_step("lab_resolve")

        assert step.status == "failed"
        assert step.error == "API timeout"
        assert step.attempt_count == 1

    def test_skip_step(self) -> None:
        """skip_step() sets status to 'skipped' with optional reason."""
        progress = InstantiationProgress.build_default(has_content_sync=True)

        progress.skip_step("content_sync", reason="no upstream")
        step = progress.get_step("content_sync")

        assert step.status == "skipped"
        assert step.completed_at is not None
        assert step.error == "no upstream"

    def test_reset_step(self) -> None:
        """reset_step() returns a failed step to pending."""
        progress = InstantiationProgress.build_default()

        progress.fail_step("lab_resolve", "timeout")
        progress.reset_step("lab_resolve")
        step = progress.get_step("lab_resolve")

        assert step.status == "pending"
        assert step.error is None

    def test_reset_only_works_on_failed(self) -> None:
        """reset_step() is a no-op for non-failed steps."""
        progress = InstantiationProgress.build_default()
        step_before = progress.get_step("lab_resolve")

        assert step_before.status == "pending"
        progress.reset_step("lab_resolve")

        assert progress.get_step("lab_resolve").status == "pending"

    def test_mark_in_progress(self) -> None:
        """mark_in_progress() sets current_step but doesn't change step status."""
        progress = InstantiationProgress.build_default()

        progress.mark_in_progress("lab_resolve")

        assert progress.current_step == "lab_resolve"
        assert progress.get_step("lab_resolve").status == "pending"

    def test_complete_clears_current_step(self) -> None:
        """Completing a step clears current_step."""
        progress = InstantiationProgress.build_default()

        progress.mark_in_progress("lab_resolve")
        progress.complete_step("lab_resolve")

        assert progress.current_step is None

    def test_fail_clears_current_step(self) -> None:
        """Failing a step clears current_step."""
        progress = InstantiationProgress.build_default()

        progress.mark_in_progress("lab_resolve")
        progress.fail_step("lab_resolve", "error")

        assert progress.current_step is None


# =============================================================================
# InstantiationProgress — Pipeline Completion & Progress Counting
# =============================================================================


@pytest.mark.unit
class TestPipelineCompletion:
    """Tests for is_complete, has_failures, and progress counting."""

    def test_is_complete_all_completed(self) -> None:
        """is_complete is True when all steps are completed."""
        progress = InstantiationProgress.build_default()

        for step in progress.steps:
            if step.status == "pending":
                progress.complete_step(step.step)

        assert progress.is_complete is True

    def test_is_complete_mix_of_completed_and_skipped(self) -> None:
        """is_complete is True with mix of completed and skipped steps."""
        progress = InstantiationProgress.build_default()  # some skipped, some pending

        for step in progress.steps:
            if step.status == "pending":
                progress.complete_step(step.step)

        assert progress.is_complete is True

    def test_is_not_complete_with_pending(self) -> None:
        """is_complete is False when pending steps remain."""
        progress = InstantiationProgress.build_default()

        assert progress.is_complete is False

    def test_is_not_complete_with_failed(self) -> None:
        """is_complete is False when a step is failed."""
        progress = InstantiationProgress.build_default()

        progress.fail_step("lab_resolve", "error")

        assert progress.is_complete is False

    def test_has_failures(self) -> None:
        """has_failures is True when at least one step failed."""
        progress = InstantiationProgress.build_default()

        progress.fail_step("lab_resolve", "timeout")

        assert progress.has_failures is True

    def test_no_failures(self) -> None:
        """has_failures is False when no steps have failed."""
        progress = InstantiationProgress.build_default()

        assert progress.has_failures is False

    def test_completed_step_count(self) -> None:
        """completed_step_count counts completed + skipped steps."""
        progress = InstantiationProgress.build_default()  # 5 skipped by default
        initial_count = progress.completed_step_count

        progress.complete_step("lab_resolve")

        assert progress.completed_step_count == initial_count + 1

    def test_total_step_count(self) -> None:
        """total_step_count always returns 9 for default pipeline."""
        progress = InstantiationProgress.build_default()

        assert progress.total_step_count == 9

    def test_completed_at_set_when_done(self) -> None:
        """completed_at is set when the last step is completed."""
        progress = InstantiationProgress.build_default()

        for step in progress.steps:
            if step.status == "pending":
                progress.complete_step(step.step)

        assert progress.completed_at is not None

    def test_completed_at_not_set_when_incomplete(self) -> None:
        """completed_at is None when pipeline is still in progress."""
        progress = InstantiationProgress.build_default()

        progress.complete_step("lab_resolve")

        assert progress.completed_at is None

    def test_empty_pipeline_not_complete(self) -> None:
        """An empty pipeline (no steps) is not considered complete."""
        progress = InstantiationProgress(steps=[])

        assert progress.is_complete is False

    def test_progress_percentage_calculation(self) -> None:
        """completed_step_count / total_step_count gives a progress fraction."""
        progress = InstantiationProgress.build_default()  # 5 skipped, 4 pending

        # 5/9 complete (skipped count as done)
        assert progress.completed_step_count == 5
        assert progress.total_step_count == 9

        progress.complete_step("lab_resolve")

        assert progress.completed_step_count == 6


# =============================================================================
# InstantiationProgress — Get Step
# =============================================================================


@pytest.mark.unit
class TestGetStep:
    """Tests for get_step() lookup."""

    def test_get_existing_step(self) -> None:
        """get_step() returns the step by name."""
        progress = InstantiationProgress.build_default()

        step = progress.get_step("lab_start")

        assert step is not None
        assert step.step == "lab_start"

    def test_get_unknown_step_returns_none(self) -> None:
        """get_step() returns None for unknown step names."""
        progress = InstantiationProgress.build_default()

        assert progress.get_step("nonexistent_step") is None


# =============================================================================
# InstantiationProgress — Serialization
# =============================================================================


@pytest.mark.unit
class TestProgressSerialization:
    """Tests for to_dict() / from_dict() round-trip."""

    def test_round_trip_preserves_state(self) -> None:
        """to_dict() → from_dict() preserves all pipeline state."""
        progress = InstantiationProgress.build_default(
            has_port_template=True,
            has_content_sync=True,
            has_lds=True,
        )
        progress.complete_step("content_sync", result_data={"synced": True})
        progress.mark_in_progress("lab_resolve")

        data = progress.to_dict()
        restored = InstantiationProgress.from_dict(data)

        assert restored.pipeline_version == "1.0"
        assert restored.current_step == "lab_resolve"
        assert restored.get_step("content_sync").status == "completed"
        assert restored.get_step("content_sync").result_data == {"synced": True}
        assert restored.get_step("lab_resolve").status == "pending"
        assert restored.total_step_count == 9

    def test_to_dict_structure(self) -> None:
        """to_dict() produces the expected top-level keys."""
        progress = InstantiationProgress.build_default()
        data = progress.to_dict()

        assert "steps" in data
        assert "started_at" in data
        assert "current_step" in data
        assert "completed_at" in data
        assert "pipeline_version" in data
        assert len(data["steps"]) == 9

    def test_from_dict_with_missing_fields(self) -> None:
        """from_dict() handles missing optional fields gracefully."""
        data = {"steps": [{"step": "lab_resolve"}]}
        restored = InstantiationProgress.from_dict(data)

        assert restored.pipeline_version == "1.0"
        assert restored.current_step is None
        assert restored.completed_at is None
        assert restored.total_step_count == 1


# =============================================================================
# Full Pipeline Walk-Through
# =============================================================================


@pytest.mark.unit
class TestFullPipelineWalkthrough:
    """End-to-end test: walk the entire pipeline to completion."""

    def test_minimal_pipeline_all_steps_complete(self) -> None:
        """Walk the default (no-capabilities) pipeline to completion."""
        progress = InstantiationProgress.build_default()

        # Expected execution order: lab_resolve → lab_binding → lab_start → mark_ready
        step = progress.next_executable_step()
        assert step.step == "lab_resolve"
        progress.complete_step("lab_resolve", {"cml_lab_id": "lab-99"})

        step = progress.next_executable_step()
        assert step.step == "lab_binding"
        progress.complete_step("lab_binding")

        step = progress.next_executable_step()
        assert step.step == "lab_start"
        progress.complete_step("lab_start")

        step = progress.next_executable_step()
        assert step.step == "mark_ready"
        progress.complete_step("mark_ready")

        assert progress.is_complete is True
        assert progress.completed_at is not None
        assert progress.next_executable_step() is None

    def test_full_pipeline_all_capabilities(self) -> None:
        """Walk the full 9-step pipeline with all capabilities enabled."""
        progress = InstantiationProgress.build_default(
            has_port_template=True,
            has_content_sync=True,
            has_lds=True,
        )

        expected_order = [
            "content_sync",
            "lab_resolve",
            "ports_alloc",
            "tags_sync",
            "lab_binding",
            "lab_start",
            "lds_provision",
            "mark_ready",
        ]

        for expected_name in expected_order:
            step = progress.next_executable_step()
            assert step is not None, f"Expected {expected_name} but got None"
            assert step.step == expected_name, f"Expected {expected_name} but got {step.step}"
            progress.complete_step(step.step)

        assert progress.is_complete is True
        assert progress.completed_step_count == 9  # 8 completed + 1 skipped (variables)
