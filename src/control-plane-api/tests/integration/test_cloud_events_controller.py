"""Integration tests for CloudEvent ingestion in EventsController (G-12 / Phase 2).

Verifies:
- POST /events/ endpoint is registered
- ``_parse_cloud_event`` handles structured + binary CloudEvent modes
- ``_parse_event_time`` parses RFC 3339 timestamps (with Z and explicit offset)
- ``ingest_cloud_event`` dispatches to the correct projection command and
  returns 202 on success / 500 on handler failure / 202 on unknown event
  types (forward compatibility)
- Malformed envelopes return 400
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from api.controllers.events_controller import (
    CE_POD_DEFINITION_READY,
    CE_POD_DEFINITION_SYNC_FAILED,
    EventsController,
    _parse_cloud_event,
    _parse_event_time,
)
from application.commands.pod_definition_read.project_pod_definition_ready_command import (
    ProjectPodDefinitionReadyCommand,
)
from application.commands.pod_definition_read.project_pod_definition_sync_failed_command import (
    ProjectPodDefinitionSyncFailedCommand,
)
from fastapi import Request
from neuroglia.core import OperationResult
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator

# ============================================================================
# Helpers
# ============================================================================


def _make_request(headers: dict[str, str], body_bytes: bytes) -> Request:
    """Build a Starlette Request with the given headers + body."""
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/events/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
    }

    delivered = {"done": False}

    async def receive() -> dict[str, Any]:
        if delivered["done"]:
            return {"type": "http.disconnect"}
        delivered["done"] = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    return Request(scope, receive)


def _make_controller(mediator: Mediator) -> EventsController:
    """Build EventsController with mocked dependencies."""
    sp = MagicMock(spec=ServiceProviderBase)
    # EventsController.__init__ resolves SSEEventRelay, DualAuthService, JsonSerializer.
    sp.get_required_service.return_value = MagicMock()
    mapper = MagicMock(spec=Mapper)
    return EventsController(service_provider=sp, mapper=mapper, mediator=mediator)


# ============================================================================
# _parse_event_time
# ============================================================================


class TestParseEventTime:
    @pytest.mark.unit
    def test_parse_z_suffix(self) -> None:
        result = _parse_event_time("2024-01-15T10:30:00Z")
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    @pytest.mark.unit
    def test_parse_explicit_offset(self) -> None:
        result = _parse_event_time("2024-01-15T10:30:00+00:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    @pytest.mark.unit
    def test_parse_none_returns_none(self) -> None:
        assert _parse_event_time(None) is None

    @pytest.mark.unit
    def test_parse_empty_returns_none(self) -> None:
        assert _parse_event_time("") is None

    @pytest.mark.unit
    def test_parse_invalid_returns_none(self) -> None:
        assert _parse_event_time("not-a-date") is None


# ============================================================================
# _parse_cloud_event — structured mode
# ============================================================================


@pytest.mark.asyncio
async def test_parse_cloud_event_structured_mode() -> None:
    body = {
        "specversion": "1.0",
        "type": CE_POD_DEFINITION_READY,
        "source": "scenario-engine",
        "subject": "pd-1",
        "id": "evt-1",
        "time": "2024-01-15T10:30:00Z",
        "data": {"pod_definition_id": "pd-1", "name": "lab"},
    }
    request = _make_request(
        {"content-type": "application/cloudevents+json; charset=utf-8"},
        json.dumps(body).encode(),
    )

    event = await _parse_cloud_event(request)

    assert event is not None
    assert event["type"] == CE_POD_DEFINITION_READY
    assert event["source"] == "scenario-engine"
    assert event["subject"] == "pd-1"
    assert event["id"] == "evt-1"
    assert event["time"] == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert event["data"] == {"pod_definition_id": "pd-1", "name": "lab"}


@pytest.mark.asyncio
async def test_parse_cloud_event_binary_mode() -> None:
    data = {"pod_definition_id": "pd-2", "name": "lab2"}
    request = _make_request(
        {
            "content-type": "application/json",
            "ce-specversion": "1.0",
            "ce-type": CE_POD_DEFINITION_READY,
            "ce-source": "scenario-engine",
            "ce-subject": "pd-2",
            "ce-id": "evt-2",
            "ce-time": "2024-01-15T10:30:00Z",
        },
        json.dumps(data).encode(),
    )

    event = await _parse_cloud_event(request)

    assert event is not None
    assert event["type"] == CE_POD_DEFINITION_READY
    assert event["subject"] == "pd-2"
    assert event["time"] == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert event["data"] == data


# ============================================================================
# ingest_cloud_event — dispatch
# ============================================================================


@pytest.mark.asyncio
async def test_ingest_ready_event_dispatches_project_ready_command() -> None:
    mediator = MagicMock(spec=Mediator)
    mediator.execute_async = AsyncMock(return_value=_ok_result())

    controller = _make_controller(mediator)

    body = {
        "specversion": "1.0",
        "type": CE_POD_DEFINITION_READY,
        "source": "scenario-engine",
        "subject": "pd-1",
        "id": "evt-1",
        "time": "2024-01-15T10:30:00Z",
        "data": {
            "pod_definition_id": "pd-1",
            "name": "lab",
            "version": "v1",
            "pod_type": "cml_on_aws",
            "content_hash": "sha256:abc",
        },
    }
    request = _make_request({"content-type": "application/cloudevents+json"}, json.dumps(body).encode())

    response = await controller.ingest_cloud_event(request)

    assert response.status_code == 202
    mediator.execute_async.assert_awaited_once()
    cmd = mediator.execute_async.await_args.args[0]
    assert isinstance(cmd, ProjectPodDefinitionReadyCommand)
    assert cmd.pod_definition_id == "pd-1"
    assert cmd.name == "lab"
    assert cmd.pod_type == "cml_on_aws"
    assert cmd.content_hash == "sha256:abc"
    assert cmd.event_time == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_ingest_sync_failed_event_dispatches_project_failed_command() -> None:
    mediator = MagicMock(spec=Mediator)
    mediator.execute_async = AsyncMock(return_value=_ok_result())
    controller = _make_controller(mediator)

    body = {
        "specversion": "1.0",
        "type": CE_POD_DEFINITION_SYNC_FAILED,
        "source": "scenario-engine",
        "subject": "pd-9",
        "id": "evt-9",
        "data": {
            "pod_definition_id": "pd-9",
            "reason": "download timed out",
            "error_detail": "HTTP 504",
        },
    }
    request = _make_request({"content-type": "application/cloudevents+json"}, json.dumps(body).encode())

    response = await controller.ingest_cloud_event(request)

    assert response.status_code == 202
    cmd = mediator.execute_async.await_args.args[0]
    assert isinstance(cmd, ProjectPodDefinitionSyncFailedCommand)
    assert cmd.pod_definition_id == "pd-9"
    assert cmd.reason == "download timed out"
    assert cmd.error_detail == "HTTP 504"


@pytest.mark.asyncio
async def test_ingest_unknown_event_type_returns_202() -> None:
    """Forward compatibility — unknown types are accepted but logged."""
    mediator = MagicMock(spec=Mediator)
    mediator.execute_async = AsyncMock()
    controller = _make_controller(mediator)

    body = {
        "specversion": "1.0",
        "type": "scenario_engine.something.new.v1",
        "source": "scenario-engine",
        "id": "evt-x",
        "data": {},
    }
    request = _make_request({"content-type": "application/cloudevents+json"}, json.dumps(body).encode())

    response = await controller.ingest_cloud_event(request)

    assert response.status_code == 202
    mediator.execute_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_malformed_envelope_returns_400() -> None:
    mediator = MagicMock(spec=Mediator)
    controller = _make_controller(mediator)

    # Structured mode header but body is not JSON.
    request = _make_request({"content-type": "application/cloudevents+json"}, b"not-json-at-all")

    response = await controller.ingest_cloud_event(request)

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_ingest_projection_failure_returns_500() -> None:
    mediator = MagicMock(spec=Mediator)
    mediator.execute_async = AsyncMock(return_value=_failure_result("boom"))
    controller = _make_controller(mediator)

    body = {
        "specversion": "1.0",
        "type": CE_POD_DEFINITION_READY,
        "source": "scenario-engine",
        "subject": "pd-1",
        "id": "evt-1",
        "data": {
            "pod_definition_id": "pd-1",
            "name": "lab",
            "pod_type": "cml_on_aws",
            "content_hash": "sha256:abc",
        },
    }
    request = _make_request({"content-type": "application/cloudevents+json"}, json.dumps(body).encode())

    response = await controller.ingest_cloud_event(request)

    assert response.status_code == 500


# ============================================================================
# Controller structure
# ============================================================================


def test_events_controller_has_post_events_route() -> None:
    """POST /events/ route must be registered."""
    mediator = MagicMock(spec=Mediator)
    controller = _make_controller(mediator)
    routes = controller.router.routes
    paths = [(r.path, getattr(r, "methods", set())) for r in routes]  # type: ignore[attr-defined]
    assert any(path == "/events/" and "POST" in (methods or set()) for path, methods in paths)


# ============================================================================
# OperationResult builders (compatible with neuroglia.core)
# ============================================================================


def _ok_result() -> OperationResult[dict[str, Any]]:
    """Build a successful OperationResult (status 202)."""
    result: OperationResult[dict[str, Any]] = OperationResult(title="Accepted", status=202)
    result.data = {"ok": True}
    return result


def _failure_result(message: str) -> OperationResult[dict[str, Any]]:
    """Build a failed OperationResult (status 500)."""
    result: OperationResult[dict[str, Any]] = OperationResult(title="Internal Server Error", status=500, detail=message)
    result.data = None
    return result
