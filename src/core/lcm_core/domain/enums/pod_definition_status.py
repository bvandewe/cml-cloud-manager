"""Pod definition status enum — lifecycle states for SE-managed PodDefinitions.

Represents the lifecycle of a PodDefinition entity in the ScenarioEngine.
A PodDefinition progresses through these states as content is synced
and managed over time.

ADR-044 §2.5: PodDefinition domain model with lifecycle persistence.
AD-CSI-011 (Phase 1): FAILED state for sync errors.
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class PodDefinitionStatus(CaseInsensitiveStrEnum):
    """Lifecycle status of a PodDefinition in the ScenarioEngine.

    Lifecycle:
        DEFINED → SYNCHRONIZING → READY → EXPIRED / SUPERSEDED
                              ↘ FAILED ↗ (force re-sync re-enters SYNCHRONIZING)

        DEFINED:        Created, awaiting content sync from BlobStorage
        SYNCHRONIZING:  Downloading and extracting LAB.zip from S3
        READY:          Content synced, scenarios validated, available for jobs
        FAILED:         Sync failed (download / extract / validate error);
                        ``error_message`` populated; force re-sync allowed.
        EXPIRED:        Timeslot ended or TTL exceeded, no longer usable
        SUPERSEDED:     A newer version of this definition is now READY
    """

    DEFINED = "defined"
    SYNCHRONIZING = "synchronizing"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


# Valid state transitions for PodDefinition lifecycle
POD_DEFINITION_VALID_TRANSITIONS: dict[PodDefinitionStatus, list[PodDefinitionStatus]] = {
    PodDefinitionStatus.DEFINED: [PodDefinitionStatus.SYNCHRONIZING],
    PodDefinitionStatus.SYNCHRONIZING: [
        PodDefinitionStatus.READY,
        PodDefinitionStatus.FAILED,
    ],
    PodDefinitionStatus.READY: [PodDefinitionStatus.EXPIRED, PodDefinitionStatus.SUPERSEDED],
    PodDefinitionStatus.FAILED: [PodDefinitionStatus.SYNCHRONIZING],  # force re-sync
    PodDefinitionStatus.EXPIRED: [],  # Terminal state
    PodDefinitionStatus.SUPERSEDED: [],  # Terminal state
}
