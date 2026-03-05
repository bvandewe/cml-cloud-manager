"""Assessment integration events for CloudEvent consumption.

These events are received from external Assessment Platform via CloudEvents.
They are decorated with @cloudevent to enable automatic ingestion by
CloudEventIngestor which routes them to their handlers via Mediator.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from neuroglia.eventing.cloud_events.decorators import cloudevent
from neuroglia.integration.models import IntegrationEvent


@cloudevent("assessment.collection.completed.v1")
@dataclass
class AssessmentCollectionCompletedIntegrationEventV1(IntegrationEvent[str]):
    """Event received when Assessment Platform completes data collection.

    Published by: Assessment Platform
    Action: Transition LabletSession from COLLECTING to GRADING

    The Assessment Platform sends this event after it has successfully
    collected all device configurations and states from the lab instance.
    """

    aggregate_id: str  # LabletSession ID
    session_id: str  # Assessment session ID
    collection_id: str  # Unique collection operation ID
    collected_at: datetime
    collection_summary: dict[str, Any] | None = None  # Optional summary of collected data
    device_count: int = 0  # Number of devices collected from
    artifacts_uri: str | None = None  # URI to collected artifacts


@cloudevent("assessment.grading.completed.v1")
@dataclass
class AssessmentGradingCompletedIntegrationEventV1(IntegrationEvent[str]):
    """Event received when Assessment Platform completes grading.

    Published by: Assessment Platform / Grading Engine
    Action: Record grading result and transition LabletSession to STOPPING

    The Grading Engine sends this event after evaluating the collected
    data against the grading rules and computing the final score.
    """

    aggregate_id: str  # LabletSession ID
    session_id: str  # Assessment session ID
    grading_id: str  # Unique grading operation ID
    graded_at: datetime
    score: dict[str, Any]  # Serialized GradingScore
    passed: bool  # Overall pass/fail determination
    feedback: str | None = None  # Optional feedback message
    grading_rules_uri: str | None = None  # Rules used for grading
    grading_rules_version: str | None = None  # Version of rules used


@cloudevent("assessment.collection.failed.v1")
@dataclass
class AssessmentCollectionFailedIntegrationEventV1(IntegrationEvent[str]):
    """Event received when Assessment Platform fails to collect data.

    Published by: Assessment Platform
    Action: Log error and optionally transition to STOPPING state

    This event indicates a failure in the collection process, which
    may require user intervention or automatic retry.
    """

    aggregate_id: str  # LabletSession ID
    session_id: str  # Assessment session ID
    collection_id: str  # Failed collection operation ID
    failed_at: datetime
    error_code: str  # Machine-readable error code
    error_message: str  # Human-readable error message
    retry_possible: bool = False  # Whether retry is possible
    retry_count: int = 0  # Number of retries attempted


@cloudevent("assessment.grading.failed.v1")
@dataclass
class AssessmentGradingFailedIntegrationEventV1(IntegrationEvent[str]):
    """Event received when Assessment Platform fails to grade.

    Published by: Assessment Platform / Grading Engine
    Action: Log error and transition to STOPPING state

    This event indicates a failure in the grading process.
    """

    aggregate_id: str  # LabletSession ID
    session_id: str  # Assessment session ID
    grading_id: str  # Failed grading operation ID
    failed_at: datetime
    error_code: str  # Machine-readable error code
    error_message: str  # Human-readable error message
