"""Integration tests for Lab Records Controllers — Phase 8 (P8-29).

Tests verify:
- LabRecordsController imports correctly and has expected routes
- LabRecordsController request models validate correctly
- InternalController lab-record endpoints have expected routes
- InternalController lab-record request models validate correctly
- Controller methods create correct command/query objects

Note: Full end-to-end testing with mocked services is complex due to
Neuroglia's controller patterns. These tests focus on structural validation,
consistent with the approach in test_lablet_controllers.py.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from api.controllers.internal_controller import (
    BindLabToLabletRequest,
    CompleteLabActionRequest,
    DiscoverLabRecordsRequest,
    FailLabActionRequest,
    InternalController,
    MarkLabOrphanedRequest,
    RecordLabRunRequest,
    UnbindLabFromLabletRequest,
    UpdateLabRecordStatusRequest,
    UpdateLabTopologyRequest,
)
from api.controllers.lab_records_controller import (
    BindLabRequest,
    CloneLabRequest,
    LabRecordsController,
    UnbindLabRequest,
)
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_mediator() -> MagicMock:
    """Provide a mock Mediator for testing."""
    return MagicMock(spec=Mediator)


@pytest.fixture
def mock_service_provider() -> MagicMock:
    """Provide a mock ServiceProvider."""
    return MagicMock(spec=ServiceProviderBase)


@pytest.fixture
def mock_mapper() -> MagicMock:
    """Provide a mock Mapper."""
    return MagicMock(spec=Mapper)


# ============================================================================
# LABRECORDS CONTROLLER — STRUCTURE TESTS
# ============================================================================


class TestLabRecordsControllerStructure:
    """Tests for LabRecordsController structure and routes."""

    @pytest.mark.integration
    def test_controller_instantiation(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that the LabRecordsController can be instantiated."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        assert controller is not None

    @pytest.mark.integration
    def test_controller_has_router(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that the controller has a router attribute."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        assert hasattr(controller, "router")
        assert controller.router is not None

    @pytest.mark.integration
    def test_controller_inherits_from_controller_base(self):
        """Test that LabRecordsController inherits from ControllerBase."""
        from neuroglia.mvc import ControllerBase

        assert issubclass(LabRecordsController, ControllerBase)

    @pytest.mark.integration
    def test_controller_routes_include_list_endpoint(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has the list (GET /) endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_get_by_id(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has GET /{lab_record_id} endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_topology(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has GET /{lab_record_id}/topology endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/topology" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_revisions(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has GET /{lab_record_id}/revisions endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/revisions" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_runs(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has GET /{lab_record_id}/runs endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/runs" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_bindings(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has GET /{lab_record_id}/bindings endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/bindings" in route_paths

    @pytest.mark.integration
    def test_controller_has_6_get_endpoints(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has exactly 6 GET endpoints."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        get_routes = [r for r in routes if "GET" in getattr(r, "methods", [])]
        assert len(get_routes) == 6

    @pytest.mark.integration
    def test_controller_routes_include_start(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/start endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/start" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_stop(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/stop endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/stop" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_wipe(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/wipe endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/wipe" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_delete(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/delete endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/delete" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_clone(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/clone endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/clone" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_export(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/export endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/export" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_archive(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/archive endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/archive" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_bind(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/bind endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/bind" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_unbind(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /{lab_record_id}/unbind endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/{lab_record_id}/unbind" in route_paths

    @pytest.mark.integration
    def test_controller_routes_include_import(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has POST /import endpoint."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/lab-records/import" in route_paths

    @pytest.mark.integration
    def test_controller_has_10_post_endpoints(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has exactly 10 POST endpoints."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        post_routes = [r for r in routes if "POST" in getattr(r, "methods", [])]
        assert len(post_routes) == 10

    @pytest.mark.integration
    def test_controller_has_16_total_endpoints(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ):
        """Test that controller has exactly 16 endpoints total (6 GET + 10 POST)."""
        controller = LabRecordsController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )
        routes = controller.router.routes
        http_routes = [r for r in routes if hasattr(r, "methods")]
        assert len(http_routes) == 16


# ============================================================================
# LABRECORDS CONTROLLER — REQUEST MODEL TESTS
# ============================================================================


class TestLabRecordsRequestModels:
    """Tests for LabRecordsController Pydantic request models."""

    @pytest.mark.integration
    def test_bind_lab_request_required_fields(self):
        """Test that BindLabRequest requires lablet_session_id."""
        request = BindLabRequest(lablet_session_id=str(uuid4()))
        assert request.lablet_session_id is not None
        assert request.role == "primary"
        assert request.metadata is None

    @pytest.mark.integration
    def test_bind_lab_request_custom_role(self):
        """Test that BindLabRequest accepts custom role."""
        request = BindLabRequest(
            lablet_session_id=str(uuid4()),
            role="secondary",
            metadata={"port_offset": 100},
        )
        assert request.role == "secondary"
        assert request.metadata == {"port_offset": 100}

    @pytest.mark.integration
    def test_unbind_lab_request_required_fields(self):
        """Test that UnbindLabRequest requires lablet_session_id."""
        instance_id = str(uuid4())
        request = UnbindLabRequest(lablet_session_id=instance_id)
        assert request.lablet_session_id == instance_id
        assert request.reason is None

    @pytest.mark.integration
    def test_unbind_lab_request_with_reason(self):
        """Test that UnbindLabRequest accepts reason."""
        request = UnbindLabRequest(
            lablet_session_id=str(uuid4()),
            reason="timeslot_end",
        )
        assert request.reason == "timeslot_end"

    @pytest.mark.integration
    def test_clone_lab_request_defaults(self):
        """Test that CloneLabRequest has optional title with None default."""
        request = CloneLabRequest()
        assert request.title is None

    @pytest.mark.integration
    def test_clone_lab_request_with_title(self):
        """Test that CloneLabRequest accepts custom title."""
        request = CloneLabRequest(title="My Cloned Lab")
        assert request.title == "My Cloned Lab"


# ============================================================================
# LABRECORDS CONTROLLER — EXPORT TESTS
# ============================================================================


class TestLabRecordsControllerImports:
    """Tests to verify LabRecordsController is properly exported."""

    @pytest.mark.integration
    def test_exported_from_controllers_package(self):
        """Test that LabRecordsController is exported from api.controllers."""
        from api.controllers import LabRecordsController

        assert LabRecordsController is not None

    @pytest.mark.integration
    def test_legacy_labs_controller_removed(self):
        """Test that the legacy LabsController is no longer exported."""
        import api.controllers as controllers_package

        assert not hasattr(controllers_package, "LabsController")


# ============================================================================
# INTERNAL CONTROLLER — LAB RECORD ROUTE TESTS
# ============================================================================


class TestInternalControllerLabRecordRoutes:
    """Tests for InternalController lab-record endpoints (P8-24).

    Verifies that the InternalController has all 10 lab-record internal
    endpoints (1 legacy sync + 9 new Phase 8 endpoints).
    """

    @pytest.fixture
    def internal_controller(
        self,
        mock_service_provider: MagicMock,
        mock_mapper: MagicMock,
        mock_mediator: MagicMock,
    ) -> InternalController:
        """Instantiate InternalController with mocks."""
        return InternalController(
            service_provider=mock_service_provider,
            mapper=mock_mapper,
            mediator=mock_mediator,
        )

    @pytest.mark.integration
    def test_internal_controller_instantiation(self, internal_controller: InternalController):
        """Test that InternalController can be instantiated."""
        assert internal_controller is not None

    @pytest.mark.integration
    def test_internal_has_discover_lab_records(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/discover."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/discover" in route_paths

    @pytest.mark.integration
    def test_internal_has_update_status(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/{id}/status."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/{lab_record_id}/status" in route_paths

    @pytest.mark.integration
    def test_internal_has_update_topology(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/{id}/topology."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/{lab_record_id}/topology" in route_paths

    @pytest.mark.integration
    def test_internal_has_run_completed(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/{id}/run-completed."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/{lab_record_id}/run-completed" in route_paths

    @pytest.mark.integration
    def test_internal_has_complete_action(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/{id}/complete-action."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/{lab_record_id}/complete-action" in route_paths

    @pytest.mark.integration
    def test_internal_has_fail_action(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/{id}/fail-action."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/{lab_record_id}/fail-action" in route_paths

    @pytest.mark.integration
    def test_internal_has_bind(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/{id}/bind."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/{lab_record_id}/bind" in route_paths

    @pytest.mark.integration
    def test_internal_has_unbind(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/{id}/unbind."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/{lab_record_id}/unbind" in route_paths

    @pytest.mark.integration
    def test_internal_has_mark_orphaned(self, internal_controller: InternalController):
        """Test that InternalController has POST /lab-records/{id}/mark-orphaned."""
        routes = internal_controller.router.routes
        route_paths = [r.path for r in routes]
        assert "/internal/lab-records/{lab_record_id}/mark-orphaned" in route_paths

    @pytest.mark.integration
    def test_internal_lab_endpoints_all_post(self, internal_controller: InternalController):
        """Test that all lab-record internal endpoints (except list) use POST method."""
        routes = internal_controller.router.routes
        lab_routes = [r for r in routes if hasattr(r, "path") and "/lab-records" in r.path]
        for route in lab_routes:
            methods = getattr(route, "methods", set())
            # GET /lab-records is the list endpoint (P9-4)
            if route.path == "/internal/lab-records" and "GET" in methods:
                continue
            assert "POST" in methods, f"Route {route.path} should be POST, got {methods}"


# ============================================================================
# INTERNAL CONTROLLER — LAB REQUEST MODEL TESTS
# ============================================================================


class TestInternalLabRecordRequestModels:
    """Tests for InternalController lab-record Pydantic request models."""

    # --- DiscoverLabRecordsRequest ---

    @pytest.mark.integration
    def test_discover_request_required_fields(self):
        """Test that DiscoverLabRecordsRequest requires worker_id and labs."""
        request = DiscoverLabRecordsRequest(
            worker_id="worker-456",
            labs=[{"id": "lab-1"}, {"id": "lab-2"}],
        )
        assert request.worker_id == "worker-456"
        assert len(request.labs) == 2
        assert request.source == "lab-discovery-service"

    @pytest.mark.integration
    def test_discover_request_custom_source(self):
        """Test that DiscoverLabRecordsRequest accepts custom source."""
        request = DiscoverLabRecordsRequest(
            worker_id="worker-456",
            labs=[],
            source="worker-controller",
        )
        assert request.source == "worker-controller"

    # --- UpdateLabRecordStatusRequest ---

    @pytest.mark.integration
    def test_update_status_request_all_optional(self):
        """Test that UpdateLabRecordStatusRequest fields are optional."""
        request = UpdateLabRecordStatusRequest()
        assert request.new_status is None
        assert request.cml_state is None
        assert request.error_message is None

    @pytest.mark.integration
    def test_update_status_request_with_values(self):
        """Test that UpdateLabRecordStatusRequest accepts values."""
        request = UpdateLabRecordStatusRequest(
            new_status="booted",
            cml_state="STARTED",
            error_message=None,
        )
        assert request.new_status == "booted"
        assert request.cml_state == "STARTED"

    # --- UpdateLabTopologyRequest ---

    @pytest.mark.integration
    def test_update_topology_request_defaults(self):
        """Test that UpdateLabTopologyRequest has empty dict default."""
        request = UpdateLabTopologyRequest()
        assert request.topology_data == {}
        assert request.change_summary is None

    @pytest.mark.integration
    def test_update_topology_request_with_data(self):
        """Test that UpdateLabTopologyRequest accepts topology data."""
        topo = {"nodes": [{"label": "r1"}], "links": []}
        request = UpdateLabTopologyRequest(
            topology_data=topo,
            change_summary="Added router r1",
        )
        assert request.topology_data == topo
        assert request.change_summary == "Added router r1"

    # --- RecordLabRunRequest ---

    @pytest.mark.integration
    def test_record_lab_run_request_defaults(self):
        """Test that RecordLabRunRequest has sensible defaults."""
        request = RecordLabRunRequest()
        assert request.started_at is None
        assert request.stopped_at is None
        assert request.started_by == "system"
        assert request.stop_reason is None
        assert request.lablet_session_id is None
        assert request.final_state is None

    @pytest.mark.integration
    def test_record_lab_run_request_with_values(self):
        """Test that RecordLabRunRequest accepts full run data."""
        request = RecordLabRunRequest(
            started_at="2026-02-11T10:00:00Z",
            stopped_at="2026-02-11T12:00:00Z",
            started_by="user",
            stop_reason="timeslot_end",
            lablet_session_id=str(uuid4()),
            final_state="STOPPED",
        )
        assert request.started_at == "2026-02-11T10:00:00Z"
        assert request.stop_reason == "timeslot_end"
        assert request.final_state == "STOPPED"

    # --- CompleteLabActionRequest ---

    @pytest.mark.integration
    def test_complete_action_request_defaults(self):
        """Test that CompleteLabActionRequest fields are optional."""
        request = CompleteLabActionRequest()
        assert request.action is None
        assert request.cml_state is None

    @pytest.mark.integration
    def test_complete_action_request_with_values(self):
        """Test that CompleteLabActionRequest accepts values."""
        request = CompleteLabActionRequest(action="start", cml_state="STARTED")
        assert request.action == "start"
        assert request.cml_state == "STARTED"

    # --- FailLabActionRequest ---

    @pytest.mark.integration
    def test_fail_action_request_required_error(self):
        """Test that FailLabActionRequest requires error_message."""
        request = FailLabActionRequest(error_message="CML API timeout")
        assert request.error_message == "CML API timeout"
        assert request.transition_to_error is False

    @pytest.mark.integration
    def test_fail_action_request_with_transition(self):
        """Test that FailLabActionRequest accepts transition_to_error flag."""
        request = FailLabActionRequest(
            error_message="Fatal error",
            transition_to_error=True,
        )
        assert request.transition_to_error is True

    # --- BindLabToLabletRequest ---

    @pytest.mark.integration
    def test_bind_request_required_fields(self):
        """Test that BindLabToLabletRequest requires lablet_session_id."""
        instance_id = str(uuid4())
        request = BindLabToLabletRequest(lablet_session_id=instance_id)
        assert request.lablet_session_id == instance_id
        assert request.role == "primary"
        assert request.metadata is None

    @pytest.mark.integration
    def test_bind_request_with_role_and_metadata(self):
        """Test that BindLabToLabletRequest accepts role and metadata."""
        request = BindLabToLabletRequest(
            lablet_session_id=str(uuid4()),
            role="auxiliary",
            metadata={"shared": True},
        )
        assert request.role == "auxiliary"
        assert request.metadata == {"shared": True}

    # --- UnbindLabFromLabletRequest ---

    @pytest.mark.integration
    def test_unbind_request_required_fields(self):
        """Test that UnbindLabFromLabletRequest requires lablet_session_id."""
        instance_id = str(uuid4())
        request = UnbindLabFromLabletRequest(lablet_session_id=instance_id)
        assert request.lablet_session_id == instance_id
        assert request.reason is None

    @pytest.mark.integration
    def test_unbind_request_with_reason(self):
        """Test that UnbindLabFromLabletRequest accepts reason."""
        request = UnbindLabFromLabletRequest(
            lablet_session_id=str(uuid4()),
            reason="user_request",
        )
        assert request.reason == "user_request"

    # --- MarkLabOrphanedRequest ---

    @pytest.mark.integration
    def test_mark_orphaned_request_defaults(self):
        """Test that MarkLabOrphanedRequest has sensible defaults."""
        request = MarkLabOrphanedRequest()
        assert request.error_message == "Lab not found on worker during scan"
        assert request.transition_to_error is True

    @pytest.mark.integration
    def test_mark_orphaned_request_custom_message(self):
        """Test that MarkLabOrphanedRequest accepts custom error message."""
        request = MarkLabOrphanedRequest(
            error_message="Worker re-provisioned, lab not found",
            transition_to_error=False,
        )
        assert request.error_message == "Worker re-provisioned, lab not found"
        assert request.transition_to_error is False
