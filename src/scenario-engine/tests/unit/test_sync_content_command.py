"""End-to-end orchestration tests for ``SyncContentCommandHandler`` (Phase 1 G-01).

We mock the S3 + extractor + validator + detector + CloudEvent surface so the
handler's 10-step flow can be exercised hermetically.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from application.commands.sync_content_command import (
    SyncContentCommand,
    SyncContentCommandHandler,
    _classify_failure,
)
from application.settings import Settings
from domain.entities.pod_definition import PodDefinition
from lcm_core.domain.enums import PodType
from lcm_core.infrastructure.content_store.content_extractor import ExtractedContent
from lcm_core.infrastructure.content_store.pav1_errors import PAv1ValidationError, PodTypeIndeterminate
from lcm_core.infrastructure.content_store.s3_content_client import S3ContentClientError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_dummy_zip(path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PAv1/manifest.yaml", "format_version: PAv1\nname: x\nversion: 1\ncontent_id: x\n")
        zf.writestr("PAv1/topology/cml.yaml", "labs: []\n")
    path.write_bytes(buf.getvalue())


def _make_extracted(manifest: dict[str, Any] | None = None) -> ExtractedContent:
    return ExtractedContent(
        manifest=manifest or {"format_version": "PAv1", "name": "lab", "version": "1.0.0", "content_id": "c"},
        topology={"cml": {"labs": []}},
        devices=[{"hostname": "r1"}],
        lifecycle_phases={"instantiate": {"steps": []}},
        scenarios={"lab_resolve": {"name": "lab_resolve", "version": "v1"}},
        grading_rules={"default": {}},
        reports={"summary": {}},
        restore_rules={"snapshots": {}},
        content_hash="dummy",
        local_path="dummy",
        detected_pod_type=PodType.CML_ON_AWS,
    )


@pytest.fixture
def mock_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_id_async = AsyncMock(return_value=None)
    repo.add_async = AsyncMock()
    repo.update_async = AsyncMock()
    repo.expire_superseded_definitions_async = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_s3() -> AsyncMock:
    async def _download(uri: str, dest: Path) -> Path:
        _write_dummy_zip(dest)
        return dest

    client = AsyncMock()
    client.download = AsyncMock(side_effect=_download)
    return client


@pytest.fixture
def mock_extractor() -> AsyncMock:
    extractor = AsyncMock()
    extractor.extract = AsyncMock(return_value=_make_extracted())
    return extractor


@pytest.fixture
def mock_validator() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_detector() -> MagicMock:
    detector = MagicMock()
    detector.detect = MagicMock(return_value=(PodType.CML_ON_AWS, ["manifest.yaml: present"]))
    return detector


@pytest.fixture
def mock_events() -> AsyncMock:
    events = AsyncMock()
    events.emit_content_synced = AsyncMock()
    events.emit_sync_failed = AsyncMock()
    return events


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def handler(
    mock_repo: AsyncMock,
    mock_s3: AsyncMock,
    mock_extractor: AsyncMock,
    mock_validator: MagicMock,
    mock_detector: MagicMock,
    mock_events: AsyncMock,
    settings: Settings,
) -> SyncContentCommandHandler:
    return SyncContentCommandHandler(
        pod_definition_repository=mock_repo,
        s3_content_client=mock_s3,
        content_extractor=mock_extractor,
        pav1_validator=mock_validator,
        pod_type_detector=mock_detector,
        cloud_event_service=mock_events,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_happy_path_creates_aggregate_and_marks_ready(
    handler: SyncContentCommandHandler,
    mock_repo: AsyncMock,
    mock_extractor: AsyncMock,
    mock_validator: MagicMock,
    mock_events: AsyncMock,
) -> None:
    result = await handler.handle_async(
        SyncContentCommand(
            name="lab",
            version="1.0.0",
            source_uri="s3://lcm-content/packages/lab.zip",
        )
    )

    assert result.is_success
    assert result.status_code == 202
    assert result.data["status"] == "ready"
    assert result.data["pod_type"] == PodType.CML_ON_AWS.value
    assert result.data["content_hash"]
    assert result.data["superseded_ids"] == []

    # add_async called once (new aggregate), update_async called twice
    # (SYNCHRONIZING then READY).
    mock_repo.add_async.assert_awaited_once()
    assert mock_repo.update_async.await_count == 2
    mock_extractor.extract.assert_awaited_once()
    mock_validator.validate_manifest.assert_called_once()
    mock_validator.validate_lifecycle.assert_called_once()
    mock_validator.validate_scenario.assert_called()
    mock_events.emit_content_synced.assert_awaited_once()


# ---------------------------------------------------------------------------
# Force re-sync + supersession
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_force_resync_triggers_supersession(
    handler: SyncContentCommandHandler,
    mock_repo: AsyncMock,
    mock_events: AsyncMock,
) -> None:
    # Existing READY PodDefinition with a different hash.
    existing = PodDefinition.create(
        name="lab",
        version="0.9",
        pod_type=PodType.CML_ON_AWS,
        source_uri="s3://lcm-content/packages/lab-old.zip",
        definition_id="pd-old",
    )
    existing.start_sync()
    existing.mark_ready(local_path="/d", manifest={"x": 1}, content_hash="hash-old")
    mock_repo.get_by_id_async = AsyncMock(return_value=existing)
    mock_repo.expire_superseded_definitions_async = AsyncMock(return_value=["pd-older-1", "pd-older-2"])

    result = await handler.handle_async(
        SyncContentCommand(
            definition_id="pd-old",
            name="lab",
            version="1.0.0",
            source_uri="s3://lcm-content/packages/lab.zip",
            force=True,
        )
    )

    assert result.is_success
    assert result.data["superseded_ids"] == ["pd-older-1", "pd-older-2"]
    mock_repo.expire_superseded_definitions_async.assert_awaited_once()
    kwargs = mock_repo.expire_superseded_definitions_async.await_args.kwargs
    assert kwargs["name"] == "lab"
    assert kwargs["pod_type"] == PodType.CML_ON_AWS
    assert kwargs["current_definition_id"] == "pd-old"
    mock_events.emit_content_synced.assert_awaited_once()


# ---------------------------------------------------------------------------
# Conflict — already READY without force
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ready_without_force_returns_conflict(
    handler: SyncContentCommandHandler,
    mock_repo: AsyncMock,
    mock_s3: AsyncMock,
) -> None:
    existing = PodDefinition.create(
        name="lab",
        version="1.0.0",
        pod_type=PodType.CML_ON_AWS,
        source_uri="s3://lcm-content/packages/lab.zip",
        definition_id="pd-1",
    )
    existing.start_sync()
    existing.mark_ready(local_path="/d", manifest={"x": 1}, content_hash="h")
    mock_repo.get_by_id_async = AsyncMock(return_value=existing)

    result = await handler.handle_async(SyncContentCommand(definition_id="pd-1", source_uri="s3://lcm-content/packages/lab.zip"))

    assert not result.is_success
    assert result.status_code == 409
    mock_s3.download.assert_not_called()


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_s3_failure_marks_failed_and_emits_event(
    handler: SyncContentCommandHandler,
    mock_repo: AsyncMock,
    mock_s3: AsyncMock,
    mock_events: AsyncMock,
) -> None:
    mock_s3.download = AsyncMock(side_effect=S3ContentClientError("denied", uri="s3://lcm-content/x", bucket="lcm-content", key="x"))

    result = await handler.handle_async(SyncContentCommand(name="lab", source_uri="s3://lcm-content/x"))

    assert not result.is_success
    assert result.status_code == 500
    # SYNCHRONIZING update + FAILED update = 2 updates.
    assert mock_repo.update_async.await_count == 2
    mock_events.emit_sync_failed.assert_awaited_once()
    mock_events.emit_content_synced.assert_not_awaited()
    failed_kwargs = mock_events.emit_sync_failed.await_args.kwargs
    assert "S3 download failed" in failed_kwargs["reason"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pav1_validation_failure_marks_failed(
    handler: SyncContentCommandHandler,
    mock_validator: MagicMock,
    mock_repo: AsyncMock,
    mock_events: AsyncMock,
) -> None:
    mock_validator.validate_manifest = MagicMock(side_effect=PAv1ValidationError("manifest.yaml", ["name: required"]))

    result = await handler.handle_async(SyncContentCommand(name="lab", source_uri="s3://lcm-content/packages/lab.zip"))

    assert not result.is_success
    assert result.status_code == 500
    mock_events.emit_sync_failed.assert_awaited_once()
    failed_kwargs = mock_events.emit_sync_failed.await_args.kwargs
    assert "PAv1 validation failed" in failed_kwargs["reason"]
    assert failed_kwargs["error_detail"] == "name: required"


# ---------------------------------------------------------------------------
# Pod type override + detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pod_type_override_bypasses_detection(
    handler: SyncContentCommandHandler,
    mock_detector: MagicMock,
    mock_events: AsyncMock,
) -> None:
    result = await handler.handle_async(
        SyncContentCommand(
            name="lab",
            source_uri="s3://lcm-content/packages/lab.zip",
            pod_type_override=PodType.ROC_RADKIT.value,
        )
    )

    assert result.is_success
    assert result.data["pod_type"] == PodType.ROC_RADKIT.value
    mock_detector.detect.assert_not_called()
    emitted_kwargs = mock_events.emit_content_synced.await_args.kwargs
    assert emitted_kwargs["pod_type"] == PodType.ROC_RADKIT.value


# ---------------------------------------------------------------------------
# _classify_failure unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_classify_failure_s3_error() -> None:
    reason, detail = _classify_failure(S3ContentClientError("boom"))
    assert "S3 download failed" in reason
    assert detail is None


@pytest.mark.unit
def test_classify_failure_pod_type_indeterminate() -> None:
    reason, detail = _classify_failure(PodTypeIndeterminate(["a: absent", "b: absent"]))
    assert "Pod type could not be determined" in reason
    assert "a: absent" in (detail or "")


@pytest.mark.unit
def test_classify_failure_pav1() -> None:
    reason, detail = _classify_failure(PAv1ValidationError("lifecycle.yaml", ["err1", "err2"]))
    assert "PAv1 validation failed at lifecycle.yaml" in reason
    assert detail == "err1; err2"


@pytest.mark.unit
def test_classify_failure_unknown() -> None:
    reason, detail = _classify_failure(RuntimeError("kaboom"))
    assert "Unhandled sync error: RuntimeError" in reason
    assert detail is None
