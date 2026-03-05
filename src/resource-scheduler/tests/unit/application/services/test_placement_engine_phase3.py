"""Phase 3 tests for PlacementEngine template selection.

Tests the capacity-based, cost-optimized template selection logic
added in Phase 3 - Auto-Scaling (AD-20).

Template selection flow:
1. Filter enabled templates by cpu/memory/storage requirements
2. Sort viable templates by cost_per_hour_usd ascending
3. Pick cheapest viable template
4. Fallback to largest enabled template if none satisfies requirements
5. Fallback to hardcoded defaults if no templates provided
"""

import pytest
from application.services.placement_engine import PlacementEngine

# =============================================================================
# Template Fixtures (match worker_templates.yaml)
# =============================================================================


@pytest.fixture
def templates():
    """Full set of worker templates matching registry."""
    return [
        {
            "name": "micro",
            "enabled": True,
            "capacity": {"cpu_cores": 2, "memory_gb": 1, "storage_gb": 20},
            "cost_per_hour_usd": 0.0104,
        },
        {
            "name": "small",
            "enabled": True,
            "capacity": {"cpu_cores": 2, "memory_gb": 2, "storage_gb": 50},
            "cost_per_hour_usd": 0.0208,
        },
        {
            "name": "medium",
            "enabled": True,
            "capacity": {"cpu_cores": 2, "memory_gb": 4, "storage_gb": 100},
            "cost_per_hour_usd": 0.0416,
        },
        {
            "name": "large",
            "enabled": True,
            "capacity": {"cpu_cores": 2, "memory_gb": 8, "storage_gb": 200},
            "cost_per_hour_usd": 0.0832,
        },
        {
            "name": "metal",
            "enabled": True,
            "capacity": {"cpu_cores": 48, "memory_gb": 192, "storage_gb": 900},
            "cost_per_hour_usd": 3.9641,
        },
    ]


@pytest.fixture
def engine():
    return PlacementEngine()


@pytest.fixture
def instance():
    return {"id": "inst-001", "definition_id": "def-001"}


@pytest.fixture
def definition_no_affinity():
    return {
        "id": "def-001",
        "name": "Lab",
        "resource_requirements": {"cpu_cores": 4, "memory_gb": 8, "storage_gb": 50},
        "license_affinity": [],
    }


# =============================================================================
# Capacity-Based Template Selection (with templates provided)
# =============================================================================


class TestTemplateSelectionWithTemplates:
    """Tests for _select_template when templates are provided."""

    def test_selects_multi_sessions_fallback(self, engine, instance, definition_no_affinity, templates):
        """Test multi-sessions template is selected as default when no affinity is specified."""
        decision = engine.schedule(
            instance=instance,
            definition=definition_no_affinity,
            workers=[],
            templates=templates,
        )

        assert decision.action == "scale_up"
        assert decision.worker_template == "multi-sessions"

    def test_selects_medium_for_medium_requirements(self, engine, instance, templates):
        """Test medium template selected for 4GB memory requirement."""
        definition_medium = {
            "id": "def-001",
            "name": "Medium Lab",
            "resource_requirements": {"cpu_cores": 2, "memory_gb": 4, "storage_gb": 50},
            "license_affinity": [],
        }

        decision = engine.schedule(
            instance=instance,
            definition=definition_medium,
            workers=[],
            templates=templates,
        )

        assert decision.action == "scale_up"
        assert decision.worker_template == "multi-sessions"

        assert decision.worker_template == "multi-sessions"

    def test_selects_single_session_for_personal_affinity(self, engine, instance, definition_no_affinity, templates):
        """Test single-session template is selected when definition explicitly requests personal affinity."""
        def_copy = dict(definition_no_affinity)
        def_copy["license_affinity"] = ["personal"]

        decision = engine.schedule(
            instance=instance,
            definition=def_copy,
            workers=[],
            templates=templates,
        )

        assert decision.action == "scale_up"
        assert decision.worker_template == "single-session"

        assert decision.worker_template == "single-session"


# =============================================================================
# Fallback Template Selection (no templates provided)
# =============================================================================


class TestTemplateSelectionFallback:
    """Tests for _select_template_fallback when no templates are available."""

    def test_selects_fallback_when_no_templates_provided(self, engine, instance, definition_no_affinity):
        """Test scale-up fallback still selects multi-sessions without templates list."""
        decision = engine.schedule(
            instance=instance,
            definition=definition_no_affinity,
            workers=[],
            templates=[],
        )

        assert decision.action == "scale_up"
        assert decision.worker_template == "multi-sessions"

    def test_fallback_empty_templates_list(self, engine, instance, definition_no_affinity):
        """Test that empty template list uses fallback."""
        decision = engine.schedule(instance, definition_no_affinity, [], templates=[])

        assert decision.action == "scale_up"
        assert decision.worker_template == "multi-sessions"

    def test_none_templates_uses_fallback(self, engine, instance, definition_no_affinity):
        """Test that None templates uses fallback."""
        decision = engine.schedule(instance, definition_no_affinity, [], templates=None)

        assert decision.action == "scale_up"
        assert decision.worker_template == "multi-sessions"


# =============================================================================
# Default Resource Requirements
# =============================================================================


class TestTemplateSelectionDefaults:
    """Tests for default values when resource_requirements are missing or partial."""

    def test_missing_resource_requirements_uses_defaults(self, engine, instance, templates):
        """Test that missing resource_requirements uses default values."""
        definition = {
            "id": "def-001",
            "name": "Lab",
            "license_affinity": [],
            # No resource_requirements
        }

        decision = engine.schedule(instance, definition, [], templates=templates)

        assert decision.action == "scale_up"
        # Defaults: cpu=4, mem=16, storage=100. This should now select multi-sessions by default.
        assert decision.worker_template == "multi-sessions"

        assert decision.worker_template == "multi-sessions"
