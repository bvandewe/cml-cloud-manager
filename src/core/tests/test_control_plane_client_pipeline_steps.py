"""Tests for ControlPlaneApiClient pipeline-step resume/fail methods.

Phase 3 / AD-CSI-009: Bridge between Scenario Engine CloudEvents and the CPA
internal pipeline-progress endpoints. Uses ``httpx.MockTransport`` to assert
HTTP method / URL / body shape and headers (X-API-Key).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from lcm_core.integration.clients.control_plane_client import (
    ControlPlaneApiClient,
    ControlPlaneApiClientError,
)


def _build_client(handler) -> ControlPlaneApiClient:
    """Build a ControlPlaneApiClient backed by an httpx.MockTransport."""
    client = ControlPlaneApiClient(base_url="http://test", api_key="test-key")
    transport = httpx.MockTransport(handler)
    client._client = httpx.AsyncClient(
        base_url="http://test",
        transport=transport,
        headers={"X-API-Key": "test-key"},
    )
    return client


@pytest.mark.asyncio
async def test_resume_pipeline_step_posts_to_correct_url_with_body():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "session_id": "sess-1",
                "pipeline_name": "instantiate",
                "step_name": "lab_resolve",
                "pipeline_progress": {"lab_resolve": {"status": "completed"}},
                "idempotent": False,
            },
        )

    client = _build_client(handler)
    result = await client.resume_pipeline_step(
        session_id="sess-1",
        pipeline_name="instantiate",
        step_correlation_id="corr-1",
        output_data={"cml_lab_id": "lab-xyz"},
        completed_at="2026-01-01T00:00:00+00:00",
    )

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/internal/lablet-sessions/sess-1/pipeline-steps/resume")
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["body"] == {
        "pipeline_name": "instantiate",
        "step_correlation_id": "corr-1",
        "output_data": {"cml_lab_id": "lab-xyz"},
        "completed_at": "2026-01-01T00:00:00+00:00",
    }
    assert result["idempotent"] is False
    assert result["pipeline_progress"]["lab_resolve"]["status"] == "completed"
    await client.close()


@pytest.mark.asyncio
async def test_resume_omits_completed_at_when_none():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"pipeline_progress": {}})

    client = _build_client(handler)
    await client.resume_pipeline_step(
        session_id="sess-1",
        pipeline_name="instantiate",
        step_correlation_id="corr-1",
    )
    assert "completed_at" not in captured["body"]
    assert captured["body"]["output_data"] == {}
    await client.close()


@pytest.mark.asyncio
async def test_fail_pipeline_step_posts_to_correct_url_with_body():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "session_id": "sess-1",
                "pipeline_name": "instantiate",
                "step_name": "lab_start",
                "pipeline_progress": {"lab_start": {"status": "failed"}},
            },
        )

    client = _build_client(handler)
    result = await client.fail_pipeline_step(
        session_id="sess-1",
        pipeline_name="instantiate",
        step_correlation_id="corr-2",
        error="external job timed out",
        details={"timeout_seconds": 1800},
        failed_at="2026-01-01T00:30:00+00:00",
    )

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/internal/lablet-sessions/sess-1/pipeline-steps/fail")
    assert captured["body"] == {
        "pipeline_name": "instantiate",
        "step_correlation_id": "corr-2",
        "error": "external job timed out",
        "details": {"timeout_seconds": 1800},
        "failed_at": "2026-01-01T00:30:00+00:00",
    }
    assert result["pipeline_progress"]["lab_start"]["status"] == "failed"
    await client.close()


@pytest.mark.asyncio
async def test_resume_pipeline_step_404_raises_client_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"type": "NotFound", "title": "Session", "detail": "sess-missing not found"},
        )

    client = _build_client(handler)
    with pytest.raises(ControlPlaneApiClientError) as exc_info:
        await client.resume_pipeline_step(
            session_id="sess-missing",
            pipeline_name="instantiate",
            step_correlation_id="corr-x",
        )
    assert exc_info.value.status_code == 404
    await client.close()
