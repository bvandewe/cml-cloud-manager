"""Shared enumerations for Lablet Cloud Manager.

These enums are the canonical definitions for domain concepts
shared across all services. They use CaseInsensitiveStrEnum as
their base class, so CMLWorkerStatus("RUNNING") and
CMLWorkerStatus("running") both resolve to the same member.

Services should import from here (or via their local re-export module):
    from lcm_core.domain.enums import CMLWorkerStatus
"""

from lcm_core.domain.enums.aws_region import AwsRegion
from lcm_core.domain.enums.binding_role import BindingRole
from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum
from lcm_core.domain.enums.cml_service_status import CMLServiceStatus
from lcm_core.domain.enums.cml_worker_status import CML_WORKER_VALID_TRANSITIONS, CMLWorkerStatus
from lcm_core.domain.enums.grading_session_status import GradingSessionStatus
from lcm_core.domain.enums.lab_record_status import (
    CML_STATE_TO_LAB_RECORD_STATUS,
    LAB_RECORD_VALID_TRANSITIONS,
    LabRecordStatus,
)
from lcm_core.domain.enums.lablet_definition_status import LabletDefinitionStatus
from lcm_core.domain.enums.lablet_session_status import (
    LABLET_SESSION_VALID_TRANSITIONS,
    LabletSessionStatus,
)
from lcm_core.domain.enums.license import LicenseStatus, LicenseType
from lcm_core.domain.enums.runtime_environment_type import RuntimeEnvironmentType
from lcm_core.domain.enums.user_session_status import UserSessionStatus
from lcm_core.domain.enums.worker_origin import WorkerOrigin

__all__ = [
    "AwsRegion",
    "BindingRole",
    "CaseInsensitiveStrEnum",
    "CML_STATE_TO_LAB_RECORD_STATUS",
    "CML_WORKER_VALID_TRANSITIONS",
    "CMLServiceStatus",
    "CMLWorkerStatus",
    "GradingSessionStatus",
    "LAB_RECORD_VALID_TRANSITIONS",
    "LABLET_SESSION_VALID_TRANSITIONS",
    "LabletDefinitionStatus",
    "LabletSessionStatus",
    "LabRecordStatus",
    "LicenseStatus",
    "LicenseType",
    "RuntimeEnvironmentType",
    "UserSessionStatus",
    "WorkerOrigin",
]
