"""Read model for LabletDefinition entities."""

from dataclasses import dataclass
from typing import Any


@dataclass
class LabletDefinitionReadModel:
    """Read model for a LabletDefinition from the Control Plane API.

    Used for understanding lab topology requirements and content sync metadata.
    """

    id: str
    name: str
    description: str | None = None
    topology_yaml: str | None = None
    node_count: int = 0
    required_licenses: list[str] | None = None
    metadata: dict[str, Any] | None = None
    form_qualified_name: str | None = None  # FQN: "{trackType} {trackLevel} ..."

    # Content identification (derived from FQN)
    bucket_name: str = ""

    # Package configuration
    user_session_package_name: str = "SVN.zip"
    grading_ruleset_package_name: str = "SVN.zip"
    user_session_type: str = "LDS"
    user_session_default_region: str | None = None

    # Content metadata (populated by sync — ADR-025)
    content_package_hash: str | None = None
    upstream_version: str | None = None
    cml_yaml_content: str | None = None
    devices_json: str | None = None
    grade_xml_path: str | None = None
    cml_yaml_path: str | None = None

    # Status
    status: str = "pending_sync"
    sync_status: str | None = None

    # Lab binding options (Phase 7)
    lab_reuse_enabled: bool = False
    multi_lab_enabled: bool = False

    # Instantiation timing (AD-P10-01)
    boot_lead_time_minutes: int | None = None  # Per-definition override, None = use global setting

    # Pipeline definitions (ADR-034)
    pipelines: dict | None = None  # Pipeline DAG definitions keyed by lifecycle phase

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LabletDefinitionReadModel":
        """Create from API response dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description"),
            topology_yaml=data.get("topology_yaml"),
            node_count=data.get("node_count", 0),
            required_licenses=data.get("required_licenses"),
            metadata=data.get("metadata"),
            form_qualified_name=data.get("form_qualified_name"),
            bucket_name=data.get("bucket_name", ""),
            user_session_package_name=data.get("user_session_package_name", "SVN.zip"),
            grading_ruleset_package_name=data.get("grading_ruleset_package_name", "SVN.zip"),
            user_session_type=data.get("user_session_type", "LDS"),
            user_session_default_region=data.get("user_session_default_region"),
            content_package_hash=data.get("content_package_hash"),
            upstream_version=data.get("upstream_version"),
            cml_yaml_content=data.get("cml_yaml_content"),
            devices_json=data.get("devices_json"),
            grade_xml_path=data.get("grade_xml_path"),
            cml_yaml_path=data.get("cml_yaml_path"),
            status=data.get("status", "pending_sync"),
            sync_status=data.get("sync_status"),
            lab_reuse_enabled=data.get("lab_reuse_enabled", False),
            multi_lab_enabled=data.get("multi_lab_enabled", False),
            boot_lead_time_minutes=data.get("boot_lead_time_minutes"),
            pipelines=data.get("pipelines"),
        )
