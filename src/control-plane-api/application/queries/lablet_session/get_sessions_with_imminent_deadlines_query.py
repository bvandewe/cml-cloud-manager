"""Query for sessions with imminent timeslot deadlines.

AD-TIMESLOT-001: Provides server-side filtered queries for the
TimeslotWatcherService to efficiently detect sessions that need
proactive lifecycle transitions:

1. SCHEDULED sessions approaching their boot window (timeslot_start)
2. Non-terminal sessions past their timeslot_end

Uses MongoDB indexes idx_timeslot_start and idx_timeslot_end for
efficient range queries instead of fetching all sessions client-side.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from application.queries.query_handler_base import QueryHandlerBase
from domain.enums import LabletSessionStatus
from domain.repositories.lablet_session_repository import LabletSessionRepository
from neuroglia.core import OperationResult
from neuroglia.mediation import Query, QueryHandler

logger = logging.getLogger(__name__)


@dataclass
class SessionDeadlineInfo:
    """Lightweight DTO for a session with an imminent deadline.

    Contains only the fields needed by TimeslotWatcherService to
    trigger reconciliation — no enrichment overhead.
    """

    id: str
    status: str
    timeslot_start: str | None
    timeslot_end: str | None
    worker_id: str | None
    definition_id: str | None


@dataclass
class ImminentDeadlinesResult:
    """Result containing sessions approaching start and sessions past end."""

    approaching_start: list[SessionDeadlineInfo] = field(default_factory=list)
    past_end: list[SessionDeadlineInfo] = field(default_factory=list)


@dataclass
class GetSessionsWithImminentDeadlinesQuery(Query[OperationResult[ImminentDeadlinesResult]]):
    """Query for sessions with imminent timeslot deadlines.

    Args:
        boot_window_minutes: How far ahead to look for SCHEDULED sessions
            whose timeslot_start is approaching. Should be >= the maximum
            boot lead time (default 35 min covers 20 min boot + 15 min margin).
    """

    boot_window_minutes: int = 35


class GetSessionsWithImminentDeadlinesQueryHandler(QueryHandlerBase, QueryHandler[GetSessionsWithImminentDeadlinesQuery, OperationResult[ImminentDeadlinesResult]]):
    """Handle querying for sessions with imminent deadlines.

    Executes two targeted MongoDB queries:
    1. SCHEDULED sessions with timeslot_start <= now + boot_window
    2. Non-terminal sessions with timeslot_end <= now
    """

    def __init__(self, lablet_session_repository: LabletSessionRepository):
        super().__init__()
        self._repository = lablet_session_repository

    async def handle_async(self, request: GetSessionsWithImminentDeadlinesQuery) -> OperationResult[ImminentDeadlinesResult]:
        try:
            now = datetime.now(timezone.utc)
            start_threshold = now + timedelta(minutes=request.boot_window_minutes)

            # 1. SCHEDULED sessions approaching their boot window
            approaching = await self._repository.list_approaching_start_async(before=start_threshold)

            # 2. Non-terminal sessions past their timeslot_end
            past_end = await self._repository.list_past_end_async(as_of=now)

            # Map to lightweight DTOs
            result = ImminentDeadlinesResult(
                approaching_start=[
                    SessionDeadlineInfo(
                        id=s.id(),
                        status=s.state.status.value if isinstance(s.state.status, LabletSessionStatus) else str(s.state.status),
                        timeslot_start=s.state.timeslot_start.isoformat() if s.state.timeslot_start else None,
                        timeslot_end=s.state.timeslot_end.isoformat() if s.state.timeslot_end else None,
                        worker_id=s.state.worker_id,
                        definition_id=s.state.definition_id,
                    )
                    for s in approaching
                ],
                past_end=[
                    SessionDeadlineInfo(
                        id=s.id(),
                        status=s.state.status.value if isinstance(s.state.status, LabletSessionStatus) else str(s.state.status),
                        timeslot_start=s.state.timeslot_start.isoformat() if s.state.timeslot_start else None,
                        timeslot_end=s.state.timeslot_end.isoformat() if s.state.timeslot_end else None,
                        worker_id=s.state.worker_id,
                        definition_id=s.state.definition_id,
                    )
                    for s in past_end
                ],
            )

            total = len(result.approaching_start) + len(result.past_end)
            if total > 0:
                logger.info(
                    "Imminent deadlines: %d approaching start (window=%d min), %d past end",
                    len(result.approaching_start),
                    request.boot_window_minutes,
                    len(result.past_end),
                )
            else:
                logger.debug("No imminent deadlines found (window=%d min)", request.boot_window_minutes)

            return self.ok(result)

        except Exception as e:
            logger.error("Error querying imminent deadlines: %s", e, exc_info=True)
            return self.internal_server_error(str(e))
