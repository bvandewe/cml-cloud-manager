"""PodDefinitionRef value object — reference from LCM to SE's PodDefinition.

This value object is embedded in the LCM's LabletDefinition aggregate to
reference the corresponding PodDefinition managed by the ScenarioEngine.

It captures:
- Which content definition this refers to (definition_id + version)
- What infrastructure type is required (pod_type)
- Sync confirmation (content_hash set after SE confirms READY)

ADR-044 §2.6: PodDefinitionRef in LCM.
"""

from dataclasses import dataclass

from lcm_core.domain.enums.pod_type import PodType


@dataclass(frozen=True)
class PodDefinitionRef:
    """Immutable reference from LCM's LabletDefinition to SE's PodDefinition.

    This value object bridges the two bounded contexts:
    - LCM owns LabletDefinition (scheduling, activation, session templates)
    - SE owns PodDefinition (content lifecycle, automation execution)

    The ref allows LCM to:
    - Know which pod_type a definition requires (for worker compatibility checks)
    - Verify content is synced (content_hash is set after SE confirms)
    - Submit jobs to SE with the correct definition_id + version

    Examples:
        >>> ref = PodDefinitionRef(
        ...     definition_id="exam-ccnp-test-v1-lab-1.1",
        ...     version="1.0.0",
        ...     pod_type=PodType.CML_ON_AWS,
        ... )
        >>> ref.is_synced
        False
        >>> ref.with_sync_confirmation("sha256:abc123...")
        PodDefinitionRef(definition_id='exam-ccnp-test-v1-lab-1.1', ...)
    """

    definition_id: str  # e.g. "exam-ccnp-test-v1-lab-1.1"
    version: str  # Semantic version e.g. "1.0.0"
    pod_type: PodType  # Required infrastructure type
    content_hash: str | None = None  # SHA256 set after SE sync confirmation

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.definition_id:
            raise ValueError("definition_id must not be empty")
        if not self.version:
            raise ValueError("version must not be empty")

    @property
    def is_synced(self) -> bool:
        """Whether the SE has confirmed content is synced and ready."""
        return self.content_hash is not None

    def with_sync_confirmation(self, content_hash: str) -> "PodDefinitionRef":
        """Return a new ref with sync confirmation (immutable update)."""
        return PodDefinitionRef(
            definition_id=self.definition_id,
            version=self.version,
            pod_type=self.pod_type,
            content_hash=content_hash,
        )

    def is_compatible_with(self, worker_pod_type: PodType) -> bool:
        """Check if a worker's pod_type is compatible with this definition's requirement."""
        return self.pod_type == worker_pod_type

    def to_dict(self) -> dict:
        """Serialize to dict for MongoDB/JSON storage."""
        return {
            "definition_id": self.definition_id,
            "version": self.version,
            "pod_type": self.pod_type.value,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PodDefinitionRef":
        """Deserialize from dict."""
        return cls(
            definition_id=data["definition_id"],
            version=data["version"],
            pod_type=PodType(data["pod_type"]),
            content_hash=data.get("content_hash"),
        )
