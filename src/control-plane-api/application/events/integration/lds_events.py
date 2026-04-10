"""LDS (Lab Delivery System) integration events for CloudEvent consumption.

These events are received from external LDS (pylds) instances via CloudEvents.
They are decorated with @cloudevent to enable automatic ingestion by
CloudEventIngestor which routes them to their handlers via Mediator.

LDS publishes events with prefix ``io.lablet.lds`` to a CloudEvents channel.
The CPA's CloudEventMiddleware intercepts incoming POSTs and routes them
to the handlers in lds_events_handler.py.

CloudEvent envelope example (LDS session running):
    {
        "specversion": "1.0",
        "id": "2ae7af87-9b35-415d-88d7-a3e50524c09a",
        "time": "2026-04-09T16:36:44.266371Z",
        "datacontenttype": "application/json",
        "type": "io.lablet.lds.session.running.v1",
        "source": "https://labs.lcm.io",
        "subject": "3e27515a-8ab5-4424-92d3-dcacca1d12c9",
        "data": {
            "aggregateId": "3e27515a-8ab5-4424-92d3-dcacca1d12c9",
            "sessionId": "3e27515a-8ab5-4424-92d3-dcacca1d12c9"
        }
    }

AD-SSE-RACE-001: These events trigger lifecycle transitions that propagate
to the frontend via SSE (domain event → SSE handler → browser).
"""

from dataclasses import dataclass
from datetime import datetime

from neuroglia.eventing.cloud_events.decorators import cloudevent
from neuroglia.integration.models import IntegrationEvent

# ---------------------------------------------------------------------------
# 1. Session Running — User logged in and started working
# ---------------------------------------------------------------------------


@cloudevent("io.lablet.lds.session.running.v1")
@dataclass
class LdsSessionRunningIntegrationEventV1(IntegrationEvent[str]):
    """Event received when the candidate logs in to the LDS session.

    Published by: LDS (pylds)
    Action: Transition LabletSession from READY → RUNNING

    The LDS publishes this event when a candidate accesses the lab session
    and the session enters the ``running`` state (active usage).

    CloudEvent fields:
        type: io.lablet.lds.session.running.v1
        subject: <lds_session_id> (same as LCM lablet_session_id)
    """

    aggregate_id: str = ""  # LDS session ID (= LCM LabletSession ID)
    session_id: str = ""  # Alias for aggregate_id (LDS convention)
    created_at: datetime = datetime.min  # Populated from CloudEvent envelope `time` field


# ---------------------------------------------------------------------------
# 2. Session Paused — User idle / session paused
# ---------------------------------------------------------------------------


@cloudevent("io.lablet.lds.session.paused.v1")
@dataclass
class LdsSessionPausedIntegrationEventV1(IntegrationEvent[str]):
    """Event received when the LDS session is paused (user idle).

    Published by: LDS (pylds)
    Action: Informational — logged but no state transition (future: idle detection)

    CloudEvent fields:
        type: io.lablet.lds.session.paused.v1
        subject: <lds_session_id>
    """

    aggregate_id: str = ""
    session_id: str = ""
    reason: str = ""
    created_at: datetime = datetime.min


# ---------------------------------------------------------------------------
# 3. Session Ended — LDS session terminated (timeout, user logout, etc.)
# ---------------------------------------------------------------------------


@cloudevent("io.lablet.lds.session.ended.v1")
@dataclass
class LdsSessionEndedIntegrationEventV1(IntegrationEvent[str]):
    """Event received when the LDS session ends.

    Published by: LDS (pylds)
    Action: Informational — may trigger COLLECTING if session is RUNNING.

    CloudEvent fields:
        type: io.lablet.lds.session.ended.v1
        subject: <lds_session_id>
    """

    aggregate_id: str = ""
    session_id: str = ""
    reason: str = ""
    ended_by: str = ""  # "timeout", "user", "admin", "system"
    created_at: datetime = datetime.min
