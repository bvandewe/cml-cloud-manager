"""Unit tests for RecordContentSyncResultCommand PodDefinition confirmation (G-07).

Covers the AD-CSI-001 / AD-CSI-004 path where the lablet-controller relays the
SE's confirmed ``pod_definition_id`` + ``pod_type`` after a successful sync.
"""

from unittest.mock import AsyncMock

import pytest
from application.commands.lablet_definition.record_content_sync_result_command import (
    RecordContentSyncResultCommand,
    RecordContentSyncResultCommandHandler,
)
from domain.entities.lablet_definition import LabletDefinition
from domain.enums import LabletDefinitionStatus, LicenseType
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.value_objects.port_template import PortTemplate
from domain.value_objects.resource_requirements import ResourceRequirements
from lcm_core.domain.enums.pod_type import PodType
from lcm_core.domain.value_objects.pod_definition_ref import PodDefinitionRef


@pytest.fixture
def mock_repository() -> AsyncMock:
    repo = AsyncMock(spec=LabletDefinitionRepository)
    repo.get_by_id_async = AsyncMock(return_value=None)
    repo.add_async = AsyncMock(side_effect=lambda e: e)
    repo.update_async = AsyncMock(side_effect=lambda e: e)
    return repo


def _build_definition(pod_definition_ref: PodDefinitionRef | None = None) -> LabletDefinition:
    """Build a PENDING_SYNC LabletDefinition for handler tests."""
    definition = LabletDefinition.create(
        name="test-lablet",
        version="1.0.0",
        form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
        resource_requirements=ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=20),
        license_affinity=[LicenseType.PERSONAL],
        node_count=5,
        port_template=PortTemplate.empty(),
        created_by="test-user",
    )
    if pod_definition_ref is not None:
        definition.state.pod_definition_ref = pod_definition_ref
    return definition


@pytest.fixture
def handler(mock_repository: AsyncMock) -> RecordContentSyncResultCommandHandler:
    return RecordContentSyncResultCommandHandler(lablet_definition_repository=mock_repository)


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_success_with_pod_definition_creates_ref(handler: RecordContentSyncResultCommandHandler, mock_repository: AsyncMock) -> None:
    """G-07: a sync result carrying SE's pod_definition link populates pod_definition_ref."""
    definition = _build_definition()
    mock_repository.get_by_id_async.return_value = definition

    cmd = RecordContentSyncResultCommand(
        definition_id=definition.id(),
        sync_status="success",
        lab_yaml_hash="sha256:lab",
        content_package_hash="sha256:pkg",
        pod_definition_id="pd-001",
        pod_type=PodType.CML_ON_AWS.value,
    )

    result = await handler.handle_async(cmd)

    assert result.is_success, result.error_message
    ref = definition.state.pod_definition_ref
    assert ref is not None
    assert ref.definition_id == "pd-001"
    assert ref.pod_type == PodType.CML_ON_AWS
    assert ref.content_hash == "sha256:pkg"
    assert definition.state.status == LabletDefinitionStatus.ACTIVE


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_success_with_matching_existing_ref_refreshes_hash(handler: RecordContentSyncResultCommandHandler, mock_repository: AsyncMock) -> None:
    """G-07: idempotent — same pod_type just refreshes the content hash."""
    existing_ref = PodDefinitionRef(
        definition_id="pd-001",
        version="1.0.0",
        pod_type=PodType.CML_ON_AWS,
        content_hash="sha256:old",
    )
    definition = _build_definition(pod_definition_ref=existing_ref)
    mock_repository.get_by_id_async.return_value = definition

    cmd = RecordContentSyncResultCommand(
        definition_id=definition.id(),
        sync_status="success",
        lab_yaml_hash="sha256:lab",
        content_package_hash="sha256:new",
        pod_definition_id="pd-001",
        pod_type=PodType.CML_ON_AWS.value,
    )

    result = await handler.handle_async(cmd)

    assert result.is_success, result.error_message
    ref = definition.state.pod_definition_ref
    assert ref is not None
    assert ref.content_hash == "sha256:new"
    assert ref.pod_type == PodType.CML_ON_AWS


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_pod_type_conflict_returns_409(handler: RecordContentSyncResultCommandHandler, mock_repository: AsyncMock) -> None:
    """G-07: SE confirming a different pod_type than the existing ref → conflict."""
    existing_ref = PodDefinitionRef(
        definition_id="pd-001",
        version="1.0.0",
        pod_type=PodType.CML_ON_AWS,
    )
    definition = _build_definition(pod_definition_ref=existing_ref)
    mock_repository.get_by_id_async.return_value = definition

    cmd = RecordContentSyncResultCommand(
        definition_id=definition.id(),
        sync_status="success",
        lab_yaml_hash="sha256:lab",
        content_package_hash="sha256:pkg",
        pod_definition_id="pd-001",
        pod_type=PodType.ROC_RADKIT.value,
    )

    result = await handler.handle_async(cmd)

    assert not result.is_success
    assert result.status_code == 409
    assert "conflict" in (result.error_message or "").lower()


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_unknown_pod_type_returns_400(handler: RecordContentSyncResultCommandHandler, mock_repository: AsyncMock) -> None:
    """G-07: invalid pod_type string is rejected before mutating state."""
    definition = _build_definition()
    mock_repository.get_by_id_async.return_value = definition

    cmd = RecordContentSyncResultCommand(
        definition_id=definition.id(),
        sync_status="success",
        lab_yaml_hash="sha256:lab",
        content_package_hash="sha256:pkg",
        pod_definition_id="pd-001",
        pod_type="not_a_pod_type",
    )

    result = await handler.handle_async(cmd)

    assert not result.is_success
    assert result.status_code == 400
    assert definition.state.pod_definition_ref is None


@pytest.mark.unit
@pytest.mark.command
@pytest.mark.asyncio
async def test_backward_compat_no_pod_fields_skips_confirmation(handler: RecordContentSyncResultCommandHandler, mock_repository: AsyncMock) -> None:
    """G-07: existing callers without pod_type/pod_definition_id keep working unchanged."""
    definition = _build_definition()
    mock_repository.get_by_id_async.return_value = definition

    cmd = RecordContentSyncResultCommand(
        definition_id=definition.id(),
        sync_status="success",
        lab_yaml_hash="sha256:lab",
        content_package_hash="sha256:pkg",
    )

    result = await handler.handle_async(cmd)

    assert result.is_success, result.error_message
    assert definition.state.pod_definition_ref is None
    assert definition.state.status == LabletDefinitionStatus.ACTIVE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregate_confirm_pod_definition_validates_inputs() -> None:
    """G-07: confirm_pod_definition() validates pod_definition_id and pod_type."""
    definition = _build_definition()

    with pytest.raises(ValueError, match="pod_definition_id"):
        definition.confirm_pod_definition(pod_definition_id="", pod_type=PodType.CML_ON_AWS)

    with pytest.raises(ValueError, match="Unknown pod_type"):
        definition.confirm_pod_definition(pod_definition_id="pd-001", pod_type="bogus")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_aggregate_confirm_pod_definition_accepts_enum_or_string() -> None:
    """G-07: confirm_pod_definition() accepts both PodType enum and its .value string."""
    definition = _build_definition()

    definition.confirm_pod_definition(pod_definition_id="pd-001", pod_type="cml_on_aws", content_hash="h1")
    assert definition.state.pod_definition_ref is not None
    assert definition.state.pod_definition_ref.pod_type == PodType.CML_ON_AWS

    # Same pod_type as enum → refreshes hash idempotently.
    definition.confirm_pod_definition(pod_definition_id="pd-001", pod_type=PodType.CML_ON_AWS, content_hash="h2")
    assert definition.state.pod_definition_ref.content_hash == "h2"
