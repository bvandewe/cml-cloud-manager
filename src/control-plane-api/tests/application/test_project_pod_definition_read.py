"""Unit tests for ProjectPodDefinitionReady/SyncFailed commands (G-12 / AD-CSI-015).

Covers:
- success path upserts a READY read model
- staleness guard drops out-of-order events
- supersession invokes ``mark_superseded_async``
- sync_failed carries forward identity fields from prior projection when
  the failure payload omits them
- validation rejects missing required fields
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from application.commands.pod_definition_read.project_pod_definition_ready_command import (
    ProjectPodDefinitionReadyCommand,
    ProjectPodDefinitionReadyCommandHandler,
)
from application.commands.pod_definition_read.project_pod_definition_sync_failed_command import (
    ProjectPodDefinitionSyncFailedCommand,
    ProjectPodDefinitionSyncFailedCommandHandler,
)
from domain.read_models.pod_definition_read_model import PodDefinitionReadModel
from domain.repositories.pod_definition_read_repository import PodDefinitionReadRepository


def _make_repo() -> AsyncMock:
    repo = AsyncMock(spec=PodDefinitionReadRepository)
    repo.get_async = AsyncMock(return_value=None)
    repo.upsert_async = AsyncMock(return_value=None)
    repo.mark_superseded_async = AsyncMock(return_value=0)
    return repo


# ============================================================================
# ProjectPodDefinitionReadyCommand
# ============================================================================


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_ready_success_upserts_read_model():
    repo = _make_repo()
    handler = ProjectPodDefinitionReadyCommandHandler(repo)
    now = datetime.now(timezone.utc)

    cmd = ProjectPodDefinitionReadyCommand(
        pod_definition_id="pd-1",
        name="lab",
        version="v1",
        pod_type="cml_on_aws",
        content_hash="sha256:abc",
        source_uri="s3://x/y.zip",
        event_time=now,
        raw_event={"foo": "bar"},
    )

    result = await handler.handle_async(cmd)

    assert result.is_success
    assert result.data["status"] == "READY"
    repo.upsert_async.assert_awaited_once()
    model: PodDefinitionReadModel = repo.upsert_async.await_args.args[0]
    assert model.id == "pd-1"
    assert model.status == "READY"
    assert model.content_hash == "sha256:abc"
    assert model.last_event_at == now
    repo.mark_superseded_async.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_ready_supersession_calls_mark_superseded():
    repo = _make_repo()
    repo.mark_superseded_async.return_value = 2
    handler = ProjectPodDefinitionReadyCommandHandler(repo)

    cmd = ProjectPodDefinitionReadyCommand(
        pod_definition_id="pd-2",
        name="lab",
        pod_type="cml_on_aws",
        content_hash="sha256:def",
        superseded_ids=["pd-old-1", "pd-old-2"],
    )

    result = await handler.handle_async(cmd)

    assert result.is_success
    assert result.data["superseded_count"] == 2
    repo.mark_superseded_async.assert_awaited_once()
    args, _ = repo.mark_superseded_async.await_args
    assert args[0] == ["pd-old-1", "pd-old-2"]


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_ready_drops_stale_event():
    """AD-CSI-015: out-of-order events older than last_event_at are dropped."""
    later = datetime.now(timezone.utc)
    earlier = later - timedelta(minutes=5)

    existing = PodDefinitionReadModel(
        id="pd-3",
        name="lab",
        version="v1",
        pod_type="cml_on_aws",
        status="READY",
        content_hash="sha256:current",
        source_uri=None,
        error_message=None,
        error_detail=None,
        last_event_at=later,
    )
    repo = _make_repo()
    repo.get_async.return_value = existing
    handler = ProjectPodDefinitionReadyCommandHandler(repo)

    cmd = ProjectPodDefinitionReadyCommand(
        pod_definition_id="pd-3",
        name="lab",
        pod_type="cml_on_aws",
        content_hash="sha256:stale",
        event_time=earlier,
    )

    result = await handler.handle_async(cmd)

    assert result.is_success
    assert result.data.get("skipped") is True
    assert result.data.get("reason") == "stale_event"
    repo.upsert_async.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_ready_validation_rejects_missing_fields():
    repo = _make_repo()
    handler = ProjectPodDefinitionReadyCommandHandler(repo)

    result = await handler.handle_async(ProjectPodDefinitionReadyCommand())
    assert not result.is_success
    repo.upsert_async.assert_not_awaited()


# ============================================================================
# ProjectPodDefinitionSyncFailedCommand
# ============================================================================


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_sync_failed_records_failure():
    repo = _make_repo()
    handler = ProjectPodDefinitionSyncFailedCommandHandler(repo)

    cmd = ProjectPodDefinitionSyncFailedCommand(
        pod_definition_id="pd-4",
        reason="download timed out",
        error_detail="HTTP 504 from S3",
        name="lab",
        pod_type="cml_on_aws",
        content_hash="",
    )

    result = await handler.handle_async(cmd)

    assert result.is_success
    assert result.data["status"] == "FAILED"
    model: PodDefinitionReadModel = repo.upsert_async.await_args.args[0]
    assert model.status == "FAILED"
    assert model.error_message == "download timed out"
    assert model.error_detail == "HTTP 504 from S3"


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_sync_failed_carries_forward_identity_from_prior_projection():
    """When SE fails before classification, retain prior name/pod_type/etc."""
    existing = PodDefinitionReadModel(
        id="pd-5",
        name="known-lab",
        version="v1",
        pod_type="cml_on_aws",
        status="READY",
        content_hash="sha256:prior",
        source_uri="s3://x/y.zip",
        error_message=None,
        error_detail=None,
    )
    repo = _make_repo()
    repo.get_async.return_value = existing
    handler = ProjectPodDefinitionSyncFailedCommandHandler(repo)

    cmd = ProjectPodDefinitionSyncFailedCommand(
        pod_definition_id="pd-5",
        reason="validation failed",
        # name + pod_type intentionally omitted by SE
    )

    result = await handler.handle_async(cmd)

    assert result.is_success
    model: PodDefinitionReadModel = repo.upsert_async.await_args.args[0]
    assert model.name == "known-lab"
    assert model.pod_type == "cml_on_aws"
    assert model.content_hash == "sha256:prior"
    assert model.source_uri == "s3://x/y.zip"
    assert model.status == "FAILED"


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_sync_failed_validation_rejects_missing_id():
    repo = _make_repo()
    handler = ProjectPodDefinitionSyncFailedCommandHandler(repo)

    result = await handler.handle_async(ProjectPodDefinitionSyncFailedCommand())
    assert not result.is_success
    repo.upsert_async.assert_not_awaited()
