"""Unit tests for the Scenario Registry."""

import pytest
from application.services.scenario_registry import (
    ScenarioResult,
    clear_registry,
    get_all_scenarios,
    get_scenario,
    scenario,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear registry before each test."""
    clear_registry()
    yield
    clear_registry()


class TestScenarioDecorator:
    """Tests for the @scenario decorator."""

    @pytest.mark.unit
    def test_register_scenario_class(self):
        """Registering a scenario class adds it to the registry."""

        @scenario(name="test_scenario", version="v1", description="A test scenario")
        class TestScenario:
            input_schema = {"type": "object"}
            output_schema = {"type": "object"}

        result = get_scenario("test_scenario", "v1")
        assert result is not None
        assert result.name == "test_scenario"
        assert result.version == "v1"
        assert result.description == "A test scenario"
        assert result.implementation is TestScenario

    @pytest.mark.unit
    def test_register_multiple_versions(self):
        """Different versions of the same scenario can coexist."""

        @scenario(name="multi", version="v1")
        class MultiV1:
            pass

        @scenario(name="multi", version="v2")
        class MultiV2:
            pass

        v1 = get_scenario("multi", "v1")
        v2 = get_scenario("multi", "v2")
        assert v1 is not None
        assert v2 is not None
        assert v1.implementation is MultiV1
        assert v2.implementation is MultiV2

    @pytest.mark.unit
    def test_get_nonexistent_scenario(self):
        """Looking up a non-registered scenario returns None."""
        result = get_scenario("nonexistent", "v1")
        assert result is None

    @pytest.mark.unit
    def test_get_all_scenarios(self):
        """get_all_scenarios returns metadata for all registered scenarios."""

        @scenario(name="alpha", version="v1", description="Alpha")
        class Alpha:
            pass

        @scenario(name="beta", version="v2", description="Beta")
        class Beta:
            pass

        all_scenarios = get_all_scenarios()
        assert len(all_scenarios) == 2
        assert "alpha@v1" in all_scenarios
        assert "beta@v2" in all_scenarios
        assert all_scenarios["alpha@v1"]["description"] == "Alpha"


class TestScenarioResult:
    """Tests for ScenarioResult dataclass."""

    @pytest.mark.unit
    def test_completed_result(self):
        """ScenarioResult.completed creates a success result."""
        result = ScenarioResult.completed({"key": "value"})
        assert result.status == "completed"
        assert result.output_data == {"key": "value"}
        assert result.error is None

    @pytest.mark.unit
    def test_failed_result(self):
        """ScenarioResult.failed creates a failure result."""
        result = ScenarioResult.failed("something went wrong")
        assert result.status == "failed"
        assert result.error == "something went wrong"
        assert result.output_data == {}

    @pytest.mark.unit
    def test_cancelled_result(self):
        """ScenarioResult.cancelled creates a cancellation result."""
        result = ScenarioResult.cancelled()
        assert result.status == "cancelled"
