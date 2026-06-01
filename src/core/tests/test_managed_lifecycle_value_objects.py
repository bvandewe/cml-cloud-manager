"""Tests for ADR-036 LifecyclePhase and ManagedLifecycle value objects.

Validates round-trip serialization (to_dict / from_dict), lookup methods,
immutability, and edge cases for the managed lifecycle VOs in lcm_core.
"""

import pytest

from lcm_core.domain.value_objects.managed_lifecycle import LifecyclePhase, ManagedLifecycle

# =============================================================================
# LifecyclePhase
# =============================================================================


class TestLifecyclePhase:
    """Round-trip serialization and behavior for LifecyclePhase."""

    def test_round_trip_full(self):
        """LifecyclePhase with all fields populated — from_dict(to_dict(x)) == x."""
        phase = LifecyclePhase(
            name="instantiate",
            engine="pipeline",
            trigger_on_status="instantiating",
            pipeline_def={
                "steps": [
                    {"name": "import_lab", "handler": "import_lab"},
                    {"name": "start_lab", "handler": "start_lab"},
                ],
            },
            workflow_ref=None,
            is_required=True,
        )
        restored = LifecyclePhase.from_dict(phase.to_dict())
        assert restored == phase

    def test_round_trip_minimal(self):
        """LifecyclePhase with defaults only — name is the only required field."""
        phase = LifecyclePhase(name="teardown")
        restored = LifecyclePhase.from_dict(phase.to_dict())
        assert restored == phase
        assert restored.engine == "pipeline"
        assert restored.trigger_on_status is None
        assert restored.pipeline_def is None
        assert restored.workflow_ref is None
        assert restored.is_required is True

    def test_pipeline_engine_default(self):
        """Engine defaults to 'pipeline'."""
        phase = LifecyclePhase(name="instantiate")
        assert phase.engine == "pipeline"

    def test_workflow_engine(self):
        """Engine can be set to 'workflow' with workflow_ref."""
        workflow_ref = {"namespace": "lcm", "name": "collect-evidence", "version": "0.1.0"}
        phase = LifecyclePhase(
            name="collect_evidence",
            engine="workflow",
            trigger_on_status="collecting",
            workflow_ref=workflow_ref,
            is_required=False,
        )
        assert phase.engine == "workflow"
        assert phase.workflow_ref == workflow_ref
        assert phase.is_required is False

    def test_from_dict_missing_optional_fields(self):
        """Missing optional fields default to their dataclass defaults."""
        data = {"name": "boot"}
        phase = LifecyclePhase.from_dict(data)
        assert phase.name == "boot"
        assert phase.engine == "pipeline"
        assert phase.trigger_on_status is None
        assert phase.is_required is True

    def test_frozen_immutability(self):
        """Cannot mutate fields after creation."""
        phase = LifecyclePhase(name="teardown")
        with pytest.raises(AttributeError):
            phase.name = "other"  # type: ignore[misc]

    def test_to_dict_preserves_pipeline_def(self):
        """pipeline_def dict preserved in serialization."""
        steps = {"steps": [{"name": "step1", "handler": "do_step1"}]}
        phase = LifecyclePhase(name="provision", pipeline_def=steps)
        d = phase.to_dict()
        assert d["pipeline_def"] == steps

    def test_to_dict_preserves_workflow_ref(self):
        """workflow_ref dict preserved in serialization."""
        ref = {"namespace": "lcm", "name": "grade", "version": "1.0.0"}
        phase = LifecyclePhase(name="compute_grading", engine="workflow", workflow_ref=ref)
        d = phase.to_dict()
        assert d["workflow_ref"] == ref


# =============================================================================
# ManagedLifecycle
# =============================================================================


class TestManagedLifecycle:
    """Round-trip serialization and behavior for ManagedLifecycle."""

    def _make_lifecycle(self) -> ManagedLifecycle:
        """Standard test lifecycle with 4 phases (LabletSession pattern)."""
        return ManagedLifecycle(
            phases=(
                LifecyclePhase(
                    name="instantiate",
                    engine="pipeline",
                    trigger_on_status="instantiating",
                    pipeline_def={"steps": [{"name": "import_lab"}]},
                ),
                LifecyclePhase(
                    name="collect_evidence",
                    engine="workflow",
                    trigger_on_status="collecting",
                    workflow_ref={"namespace": "lcm", "name": "collect-evidence", "version": "0.1.0"},
                    is_required=False,
                ),
                LifecyclePhase(
                    name="compute_grading",
                    engine="workflow",
                    trigger_on_status="grading",
                    workflow_ref={"namespace": "lcm", "name": "compute-grading", "version": "0.1.0"},
                    is_required=False,
                ),
                LifecyclePhase(
                    name="teardown",
                    engine="pipeline",
                    trigger_on_status="stopping",
                    pipeline_def={"steps": [{"name": "stop_lab"}, {"name": "wipe_lab"}]},
                ),
            ),
            current_phase="instantiate",
        )

    def test_round_trip(self):
        """Full ManagedLifecycle round-trip — from_dict(to_dict(x)) == x."""
        lifecycle = self._make_lifecycle()
        restored = ManagedLifecycle.from_dict(lifecycle.to_dict())
        assert restored == lifecycle

    def test_round_trip_empty_phases(self):
        """Empty phases tuple round-trips correctly."""
        lifecycle = ManagedLifecycle(phases=())
        restored = ManagedLifecycle.from_dict(lifecycle.to_dict())
        assert restored == lifecycle
        assert restored.phases == ()
        assert restored.current_phase is None

    def test_round_trip_no_current_phase(self):
        """ManagedLifecycle with current_phase=None."""
        lifecycle = ManagedLifecycle(
            phases=(LifecyclePhase(name="provision"),),
        )
        restored = ManagedLifecycle.from_dict(lifecycle.to_dict())
        assert restored.current_phase is None

    def test_get_phase_found(self):
        """Returns correct phase by name."""
        lifecycle = self._make_lifecycle()
        phase = lifecycle.get_phase("collect_evidence")
        assert phase is not None
        assert phase.name == "collect_evidence"
        assert phase.engine == "workflow"

    def test_get_phase_not_found(self):
        """Returns None for unknown phase name."""
        lifecycle = self._make_lifecycle()
        assert lifecycle.get_phase("nonexistent") is None

    def test_get_active_phases(self):
        """Filters by is_required=True."""
        lifecycle = self._make_lifecycle()
        active = lifecycle.get_active_phases()
        assert len(active) == 2
        assert all(p.is_required for p in active)
        assert [p.name for p in active] == ["instantiate", "teardown"]

    def test_get_active_phases_all_required(self):
        """When all phases are required, returns all."""
        lifecycle = ManagedLifecycle(
            phases=(
                LifecyclePhase(name="provision"),
                LifecyclePhase(name="teardown"),
            ),
        )
        active = lifecycle.get_active_phases()
        assert len(active) == 2

    def test_phase_names(self):
        """Returns ordered list of phase names."""
        lifecycle = self._make_lifecycle()
        assert lifecycle.phase_names() == [
            "instantiate",
            "collect_evidence",
            "compute_grading",
            "teardown",
        ]

    def test_phase_names_empty(self):
        """Empty lifecycle returns empty list."""
        lifecycle = ManagedLifecycle(phases=())
        assert lifecycle.phase_names() == []

    def test_to_dict_phases_as_dict(self):
        """Phases serialized as dict keyed by phase name."""
        lifecycle = self._make_lifecycle()
        d = lifecycle.to_dict()
        assert isinstance(d["phases"], dict)
        assert "instantiate" in d["phases"]
        assert "teardown" in d["phases"]
        assert len(d["phases"]) == 4

    def test_from_dict_phases_from_dict(self):
        """Phases deserialized from dict keyed by phase name."""
        data = {
            "phases": {
                "provision": {
                    "engine": "pipeline",
                    "trigger_on_status": "pending",
                },
                "teardown": {
                    "engine": "pipeline",
                    "trigger_on_status": "stopping",
                    "is_required": True,
                },
            },
            "current_phase": "provision",
        }
        lifecycle = ManagedLifecycle.from_dict(data)
        assert len(lifecycle.phases) == 2
        assert lifecycle.phases[0].name == "provision"
        assert lifecycle.phases[1].name == "teardown"
        assert lifecycle.current_phase == "provision"

    def test_from_dict_infers_name_from_key(self):
        """Phase name inferred from dict key if not in phase data."""
        data = {
            "phases": {
                "my_phase": {"engine": "workflow"},
            },
        }
        lifecycle = ManagedLifecycle.from_dict(data)
        assert lifecycle.phases[0].name == "my_phase"

    def test_from_dict_name_in_data_takes_precedence(self):
        """Explicit name in phase data takes precedence over dict key."""
        data = {
            "phases": {
                "key_name": {"name": "explicit_name", "engine": "pipeline"},
            },
        }
        lifecycle = ManagedLifecycle.from_dict(data)
        assert lifecycle.phases[0].name == "explicit_name"

    def test_frozen_immutability(self):
        """Cannot mutate fields after creation."""
        lifecycle = self._make_lifecycle()
        with pytest.raises(AttributeError):
            lifecycle.current_phase = "teardown"  # type: ignore[misc]

    def test_str_representation(self):
        """__str__ produces human-readable output."""
        lifecycle = self._make_lifecycle()
        s = str(lifecycle)
        assert "ManagedLifecycle" in s
        assert "instantiate" in s
        assert "teardown" in s
        assert "current: instantiate" in s

    def test_str_representation_no_current(self):
        """__str__ without current_phase."""
        lifecycle = ManagedLifecycle(phases=(LifecyclePhase(name="provision"),))
        s = str(lifecycle)
        assert "current:" not in s
