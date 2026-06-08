"""Unit tests for LabletDefinitionDto.pod_definition_ref mapping (AD-CSI-010, Phase 3).

Phase 3 closes the read-path gap where the SE's confirmed PodDefinition reference
was set on the aggregate (via RecordContentSyncResultCommand) but never exposed
through the public DTO — causing lcm-core's read model to always observe
``pod_definition_ref = None`` in production and the Tier-B step handlers in
lablet-controller to fall back to the legacy path.
"""

import pytest
from application.dtos.lablet_definition_dto import map_lablet_definition_to_dto
from domain.entities.lablet_definition import LabletDefinition
from domain.enums import LicenseType
from domain.value_objects.port_template import PortTemplate
from domain.value_objects.resource_requirements import ResourceRequirements
from lcm_core.domain.enums.pod_type import PodType
from lcm_core.domain.value_objects.pod_definition_ref import PodDefinitionRef


def _build_definition() -> LabletDefinition:
    return LabletDefinition.create(
        name="test-lablet",
        version="1.0.0",
        form_qualified_name="Exam Associate CCNA v1.0 LAB 1.1a",
        resource_requirements=ResourceRequirements(cpu_cores=2, memory_gb=4, storage_gb=20),
        license_affinity=[LicenseType.PERSONAL],
        node_count=5,
        port_template=PortTemplate.empty(),
        created_by="test-user",
    )


@pytest.mark.unit
def test_dto_contains_pod_definition_ref_none_when_unset() -> None:
    """When the aggregate has no pod_definition_ref set, the DTO field is None."""
    definition = _build_definition()
    definition.state.pod_definition_ref = None

    dto = map_lablet_definition_to_dto(definition)

    assert dto.pod_definition_ref is None


@pytest.mark.unit
def test_dto_serializes_pod_definition_ref_when_set() -> None:
    """When the aggregate carries a PodDefinitionRef, the DTO exposes its dict form.

    The dict shape must match what lcm-core's LabletDefinitionReadModel.from_dict
    expects (``pod_definition_ref`` key, dict value with definition_id/version/
    pod_type/content_hash).
    """
    definition = _build_definition()
    definition.state.pod_definition_ref = PodDefinitionRef(
        definition_id="exam-ccnp-test-v1-lab-1.1",
        version="1.2.3",
        pod_type=PodType.CML_ON_AWS,
        content_hash="sha256:deadbeef",
    )

    dto = map_lablet_definition_to_dto(definition)

    assert dto.pod_definition_ref is not None
    assert dto.pod_definition_ref["definition_id"] == "exam-ccnp-test-v1-lab-1.1"
    assert dto.pod_definition_ref["version"] == "1.2.3"
    assert dto.pod_definition_ref["pod_type"] == PodType.CML_ON_AWS.value
    assert dto.pod_definition_ref["content_hash"] == "sha256:deadbeef"
