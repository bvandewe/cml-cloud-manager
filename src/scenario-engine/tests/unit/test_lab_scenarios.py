"""Unit tests for lab_resolve and lab_start scenarios."""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from application.services.scenario_context import AdapterRegistry, ScenarioContext
from application.services.scenario_registry import clear_registry
from scenarios.lab_resolve_scenario import LabResolveScenario
from scenarios.lab_start_scenario import LabStartScenario

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeLabInfo:
    title: str = "Test Lab"


def _build_context(adapters: AdapterRegistry | None = None, job_id: str = "test-job") -> ScenarioContext:
    """Build a ScenarioContext with test defaults."""

    async def noop_progress(pct: int, msg: str, details: dict | None = None) -> None:
        pass

    return ScenarioContext(
        job_id=job_id,
        scenario_name="test",
        scenario_version="v1",
        input_data={},
        adapters=adapters or AdapterRegistry(),
        report_progress=noop_progress,
        cancellation_event=asyncio.Event(),
    )


def _mock_cml_adapter(
    get_lab_state_return="STOPPED",
    import_lab_return="lab-123",
    check_converged_return=True,
    get_lab_return=None,
):
    """Create a mock CML adapter."""
    mock = AsyncMock()
    mock.get_lab_state = AsyncMock(return_value=get_lab_state_return)
    mock.import_lab = AsyncMock(return_value=import_lab_return)
    mock.start_lab = AsyncMock()
    mock.check_if_converged = AsyncMock(return_value=check_converged_return)
    mock.get_lab = AsyncMock(return_value=get_lab_return or FakeLabInfo(title="Imported Lab"))
    return mock


# ---------------------------------------------------------------------------
# LabResolveScenario Tests
# ---------------------------------------------------------------------------


class TestLabResolveScenario:
    """Tests for the lab_resolve@v1 scenario."""

    @pytest.fixture(autouse=True)
    def clean_registry(self):
        clear_registry()
        yield
        clear_registry()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fresh_import_success(self):
        """Lab is imported fresh when no existing lab provided."""
        cml = _mock_cml_adapter(import_lab_return="new-lab-456")
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabResolveScenario()
        result = await scenario.execute(
            {
                "topology_yaml": "<xml>topology</xml>",
                "worker_ip": "10.0.0.1",
                "worker_cml_username": "admin",
                "worker_cml_password": "secret",  # pragma: allowlist secret
            },
            context,
        )

        assert result.status == "completed"
        assert result.output_data["lab_id"] == "new-lab-456"
        assert result.output_data["freshly_imported"] is True
        cml.import_lab.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reuse_existing_lab(self):
        """Lab is reused when lab_reuse_enabled and existing_lab_id valid."""
        cml = _mock_cml_adapter(get_lab_state_return="STARTED")
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabResolveScenario()
        result = await scenario.execute(
            {
                "topology_yaml": "<xml>topology</xml>",
                "worker_ip": "10.0.0.1",
                "worker_cml_username": "admin",
                "worker_cml_password": "secret",  # pragma: allowlist secret
                "existing_lab_id": "existing-789",
                "lab_reuse_enabled": True,
            },
            context,
        )

        assert result.status == "completed"
        assert result.output_data["lab_id"] == "existing-789"
        assert result.output_data["freshly_imported"] is False
        cml.import_lab.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_reuse_falls_back_to_import_when_lab_not_found(self):
        """Falls back to import if existing lab not found."""
        cml = _mock_cml_adapter(get_lab_state_return=None, import_lab_return="fresh-001")
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabResolveScenario()
        result = await scenario.execute(
            {
                "topology_yaml": "<xml>topology</xml>",
                "worker_ip": "10.0.0.1",
                "worker_cml_username": "admin",
                "worker_cml_password": "secret",  # pragma: allowlist secret
                "existing_lab_id": "gone-lab",
                "lab_reuse_enabled": True,
            },
            context,
        )

        assert result.status == "completed"
        assert result.output_data["lab_id"] == "fresh-001"
        assert result.output_data["freshly_imported"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_topology_yaml(self):
        """Fails if topology_yaml missing."""
        cml = _mock_cml_adapter()
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabResolveScenario()
        result = await scenario.execute(
            {"worker_ip": "10.0.0.1", "worker_cml_username": "admin", "worker_cml_password": "secret"},  # pragma: allowlist secret
            context,
        )

        assert result.status == "failed"
        assert "topology_yaml" in result.error

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_import_failure(self):
        """Fails gracefully when CML import raises."""
        cml = _mock_cml_adapter()
        cml.import_lab = AsyncMock(side_effect=Exception("Connection refused"))
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabResolveScenario()
        result = await scenario.execute(
            {
                "topology_yaml": "<xml>topology</xml>",
                "worker_ip": "10.0.0.1",
                "worker_cml_username": "admin",
                "worker_cml_password": "secret",  # pragma: allowlist secret
            },
            context,
        )

        assert result.status == "failed"
        assert "Connection refused" in result.error


# ---------------------------------------------------------------------------
# LabStartScenario Tests
# ---------------------------------------------------------------------------


class TestLabStartScenario:
    """Tests for the lab_start@v1 scenario."""

    @pytest.fixture(autouse=True)
    def clean_registry(self):
        clear_registry()
        yield
        clear_registry()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_already_converged_fast_path(self):
        """Returns immediately if lab already STARTED + converged."""
        cml = _mock_cml_adapter(get_lab_state_return="STARTED", check_converged_return=True)
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabStartScenario()
        result = await scenario.execute(
            {"lab_id": "lab-1", "worker_ip": "10.0.0.1", "worker_cml_username": "admin", "worker_cml_password": "secret"},  # pragma: allowlist secret
            context,
        )

        assert result.status == "completed"
        assert result.output_data["lab_state"] == "CONVERGED"
        assert result.output_data["poll_count"] == 0
        cml.start_lab.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_and_converge(self):
        """Starts a STOPPED lab and polls until converged."""
        cml = _mock_cml_adapter(get_lab_state_return="STOPPED", check_converged_return=True)
        # After start, get_lab_state returns STARTED
        cml.get_lab_state = AsyncMock(side_effect=["STOPPED", "STARTED"])
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabStartScenario()
        result = await scenario.execute(
            {
                "lab_id": "lab-2",
                "worker_ip": "10.0.0.1",
                "worker_cml_username": "admin",
                "worker_cml_password": "secret",  # pragma: allowlist secret
                "poll_interval": 0,  # No delay in tests
            },
            context,
        )

        assert result.status == "completed"
        assert result.output_data["lab_state"] == "CONVERGED"
        assert result.output_data["poll_count"] == 1
        cml.start_lab.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ghost_lab_not_found(self):
        """Returns failed if lab doesn't exist on worker."""
        cml = _mock_cml_adapter(get_lab_state_return=None)
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabStartScenario()
        result = await scenario.execute(
            {"lab_id": "ghost-lab", "worker_ip": "10.0.0.1", "worker_cml_username": "admin", "worker_cml_password": "secret"},  # pragma: allowlist secret
            context,
        )

        assert result.status == "failed"
        assert "ghost lab" in result.error.lower()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unexpected_state_fails(self):
        """Returns failed if lab enters unexpected state during polling."""
        cml = _mock_cml_adapter(get_lab_state_return="STOPPED")
        # After start: returns unexpected "BOOTING" state
        cml.get_lab_state = AsyncMock(side_effect=["STOPPED", "BOOTING"])
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabStartScenario()
        result = await scenario.execute(
            {
                "lab_id": "lab-3",
                "worker_ip": "10.0.0.1",
                "worker_cml_username": "admin",
                "worker_cml_password": "secret",  # pragma: allowlist secret
                "poll_interval": 0,
            },
            context,
        )

        assert result.status == "failed"
        assert "unexpected state" in result.error.lower()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cancellation_during_poll(self):
        """Cancellation event stops polling."""
        cml = _mock_cml_adapter(get_lab_state_return="STOPPED", check_converged_return=False)
        cml.get_lab_state = AsyncMock(side_effect=["STOPPED", "STARTED"])
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)
        # Set cancellation before polling starts
        context.cancellation_event.set()

        scenario = LabStartScenario()
        result = await scenario.execute(
            {
                "lab_id": "lab-4",
                "worker_ip": "10.0.0.1",
                "worker_cml_username": "admin",
                "worker_cml_password": "secret",  # pragma: allowlist secret
                "poll_interval": 0,
            },
            context,
        )

        assert result.status == "cancelled"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_lab_id(self):
        """Fails if lab_id missing."""
        cml = _mock_cml_adapter()
        adapters = AdapterRegistry({"cml": cml})
        context = _build_context(adapters=adapters)

        scenario = LabStartScenario()
        result = await scenario.execute(
            {"worker_ip": "10.0.0.1", "worker_cml_username": "admin", "worker_cml_password": "secret"},  # pragma: allowlist secret
            context,
        )

        assert result.status == "failed"
        assert "lab_id" in result.error
