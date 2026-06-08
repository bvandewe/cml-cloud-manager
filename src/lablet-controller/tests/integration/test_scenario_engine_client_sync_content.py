"""Tests for ScenarioEngineClient.sync_content (Phase 2 / G-02 / AD-CSI-003).

Uses httpx.MockTransport (no respx) to verify:
- success path returns ContentSyncResult populated from SE response
- HTTP 4xx/5xx surfaces as ScenarioEngineError with status_code
- connection error wraps httpx.RequestError as ScenarioEngineError
- advisory fields (content_hash, pod_type) are sent in the payload for
  forward compatibility (AD-CSI-002)
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from integration.services.scenario_engine_client import (
    ContentSyncResult,
    ScenarioEngineClient,
    ScenarioEngineError,
)

MockHandler = Callable[[httpx.Request], httpx.Response]


def _make_client(handler: MockHandler) -> ScenarioEngineClient:
    """Build a client whose internal httpx.AsyncClient uses MockTransport."""
    transport = httpx.MockTransport(handler)
    client = ScenarioEngineClient(base_url="http://scenario-engine:8083")
    # Replace the real AsyncClient with one wired to the mock transport.
    client._http = httpx.AsyncClient(transport=transport, timeout=5.0)
    return client


@pytest.mark.asyncio
async def test_sync_content_success_returns_result() -> None:
    """SE returns 202 with definition_id, status, content_hash, pod_type."""
    seen_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/content/sync"
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(
            202,
            json={
                "definition_id": "pd-abc",
                "status": "ready",
                "content_hash": "sha256:deadbeef",
                "pod_type": "cml_on_aws",
                "message": "synced",
                "superseded_ids": ["pd-old-1", "pd-old-2"],
            },
        )

    client = _make_client(handler)
    try:
        result = await client.sync_content(
            source_uri="s3://lablets/bucket/pkg.zip",
            name="my-lab",
            version="v1",
            content_hash="sha256:deadbeef",
            pod_type="cml_on_aws",
        )
    finally:
        await client.close()

    assert isinstance(result, ContentSyncResult)
    assert result.pod_definition_id == "pd-abc"
    assert result.status == "ready"
    assert result.content_hash == "sha256:deadbeef"
    assert result.pod_type == "cml_on_aws"
    assert result.message == "synced"
    assert result.superseded_ids == ["pd-old-1", "pd-old-2"]

    # Advisory fields must be sent (forward-compat per AD-CSI-002).
    assert len(seen_payloads) == 1
    payload = seen_payloads[0]
    assert payload["source_uri"] == "s3://lablets/bucket/pkg.zip"
    assert payload["name"] == "my-lab"
    assert payload["version"] == "v1"
    assert payload["force"] is False
    assert payload["content_hash"] == "sha256:deadbeef"
    assert payload["pod_type"] == "cml_on_aws"


@pytest.mark.asyncio
async def test_sync_content_404_raises_scenario_engine_error() -> None:
    """4xx response surfaces as ScenarioEngineError with status_code."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    client = _make_client(handler)
    try:
        with pytest.raises(ScenarioEngineError) as exc_info:
            await client.sync_content(source_uri="s3://x/y.zip", name="lab")
    finally:
        await client.close()

    assert exc_info.value.status_code == 404
    assert exc_info.value.response == {"detail": "not found"}


@pytest.mark.asyncio
async def test_sync_content_500_raises_scenario_engine_error() -> None:
    """5xx response surfaces as ScenarioEngineError."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal"})

    client = _make_client(handler)
    try:
        with pytest.raises(ScenarioEngineError) as exc_info:
            await client.sync_content(source_uri="s3://x/y.zip", name="lab")
    finally:
        await client.close()

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_sync_content_connection_error_raises_scenario_engine_error() -> None:
    """Connection failure wraps httpx.RequestError as ScenarioEngineError."""

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _make_client(handler)
    try:
        with pytest.raises(ScenarioEngineError) as exc_info:
            await client.sync_content(source_uri="s3://x/y.zip", name="lab")
    finally:
        await client.close()

    assert "Connection to Scenario Engine failed" in str(exc_info.value)
    assert exc_info.value.status_code is None


@pytest.mark.asyncio
async def test_sync_content_missing_superseded_ids_defaults_to_empty_list() -> None:
    """SE today does not emit superseded_ids in HTTP response (Q-09 gap)."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202,
            json={
                "definition_id": "pd-1",
                "status": "ready",
                "content_hash": "sha256:cafe",
                "pod_type": "cml_on_aws",
            },
        )

    client = _make_client(handler)
    try:
        result = await client.sync_content(source_uri="s3://x/y.zip", name="lab")
    finally:
        await client.close()

    assert result.superseded_ids == []
