"""SSE (Server-Sent Events) Controller for real-time UI updates."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from classy_fastapi.decorators import get as get_route
from fastapi import Depends, Query, Request
from fastapi.responses import StreamingResponse
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.serialization.json import JsonSerializer

from api.dependencies import get_current_user
from api.services import DualAuthService
from application.dtos.lablet_definition_dto import map_lablet_definition_to_summary_dto
from application.dtos.lablet_session_dto import map_lablet_session_to_summary_dto
from application.events.domain.cml_worker_events import _broadcast_worker_snapshot
from application.services.sse_event_relay import SSEEventRelay
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository

logger = logging.getLogger(__name__)


class EventsController(ControllerBase):
    """Controller for Server-Sent Events (SSE) endpoint."""

    def __init__(
        self,
        service_provider: ServiceProviderBase,
        mapper: Mapper,
        mediator: Mediator,
    ):
        """Initialize Events Controller."""
        ControllerBase.__init__(self, service_provider, mapper, mediator)
        self._sse_relay = service_provider.get_required_service(SSEEventRelay)
        self._auth_service = service_provider.get_required_service(DualAuthService)
        self._serializer = service_provider.get_required_service(JsonSerializer)

    async def _event_generator(
        self,
        request: Request,
        user_info: dict,
        worker_ids: set[str] | None = None,
        event_types: set[str] | None = None,
    ) -> AsyncIterator[str]:
        """Generate SSE events from SSEEventRelay with optional filtering.

        Args:
            request: FastAPI request object (to detect client disconnect)
            user_info: User authentication info
            worker_ids: Optional set of worker IDs to filter events by
            event_types: Optional set of event types to filter by

        Yields:
            SSE-formatted event strings
        """
        client_id, event_queue = await self._sse_relay.register_client(worker_ids=worker_ids, event_types=event_types)
        session_id = request.cookies.get("session_id")

        try:
            logger.info(f"SSE client connected - user: {user_info.get('username', 'unknown')}, client_id: {client_id}")

            # Send initial connection event
            yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'user': user_info.get('username'), 'client_id': client_id})}\n\n"

            # Initial full worker snapshots (SSE-first model) unless client filtered by event_types excluding snapshots
            scope = None
            try:
                # Create a service scope to resolve scoped services (CMLWorkerRepository)
                scope = self.service_provider.create_scope()  # type: ignore[attr-defined]
                worker_repo = scope.get_required_service(CMLWorkerRepository)
                if worker_repo:
                    if worker_ids:
                        # Specific workers only
                        for wid in worker_ids:
                            await _broadcast_worker_snapshot(worker_repo, self._sse_relay, self._serializer, wid, reason="initial")
                    else:
                        # All active workers
                        workers = await worker_repo.get_active_workers_async()
                        for w in workers:
                            await _broadcast_worker_snapshot(worker_repo, self._sse_relay, self._serializer, w.id(), reason="initial")
            except Exception as e:
                logger.warning(f"Failed to send initial worker snapshots: {e}")

            # Initial lablet session snapshots
            try:
                if not scope:
                    scope = self.service_provider.create_scope()  # type: ignore[attr-defined]
                session_repo = scope.get_required_service(LabletSessionRepository)
                if session_repo:
                    sessions = await session_repo.list_active_async()
                    for session in sessions:
                        try:
                            dto = map_lablet_session_to_summary_dto(session)
                            snapshot = self._serializer.serialize(dto)
                            if isinstance(snapshot, (bytes, bytearray)):
                                snapshot = json.loads(snapshot.decode("utf-8"))
                            else:
                                snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
                            await self._sse_relay.broadcast_event(
                                event_type="lablet.session.snapshot",
                                data=snapshot,
                                source="domain.lablet_session.snapshot",
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send lablet session snapshot for {session.id()}: {e}")
            except Exception as e:
                logger.warning(f"Failed to send initial lablet session snapshots: {e}")

            # Initial lablet definition snapshots
            try:
                if not scope:
                    scope = self.service_provider.create_scope()  # type: ignore[attr-defined]
                definition_repo = scope.get_required_service(LabletDefinitionRepository)
                if definition_repo:
                    definitions = await definition_repo.list_active_async()
                    for defn in definitions:
                        try:
                            dto = map_lablet_definition_to_summary_dto(defn)
                            snapshot = self._serializer.serialize(dto)
                            if isinstance(snapshot, (bytes, bytearray)):
                                snapshot = json.loads(snapshot.decode("utf-8"))
                            else:
                                snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
                            await self._sse_relay.broadcast_event(
                                event_type="lablet.definition.snapshot",
                                data=snapshot,
                                source="domain.lablet_definition.snapshot",
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send lablet definition snapshot for {defn.id()}: {e}")
            except Exception as e:
                logger.warning(f"Failed to send initial lablet definition snapshots: {e}")

            # Heartbeat interval (30 seconds)
            heartbeat_interval = 30

            async def check_disconnect():
                while True:
                    if await request.is_disconnected():
                        return
                    await asyncio.sleep(1.0)

            disconnect_task = asyncio.create_task(check_disconnect())

            try:
                # Stream events
                while True:
                    get_event_task = asyncio.create_task(event_queue.get())

                    done, pending = await asyncio.wait(
                        [get_event_task, disconnect_task],
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=heartbeat_interval,
                    )

                    if disconnect_task in done:
                        logger.info(f"SSE client disconnected: {client_id}")
                        get_event_task.cancel()
                        break

                    # Check session validity periodically (on heartbeat or event)
                    if session_id:
                        user = self._auth_service.get_user_from_session(session_id)
                        if not user:
                            logger.warning(f"Session expired for SSE client {client_id}, closing connection")
                            yield "event: auth.session.expired\ndata: {}\n\n"
                            get_event_task.cancel()
                            break

                    if get_event_task in done:
                        event_message = get_event_task.result()
                        event_type = event_message.get("type", "message")

                        # JsonSerializer returns bytearray/bytes, need to decode to string for SSE
                        payload = self._serializer.serialize(event_message)
                        if isinstance(payload, (bytes, bytearray)):
                            payload = payload.decode("utf-8")

                        yield f"event: {event_type}\ndata: {payload}\n\n"

                        if event_type == "system.sse.shutdown":
                            logger.info(f"Received system limit shutdown event, closing SSE stream for client {client_id}")
                            break
                    else:
                        # Timeout occurred (Heartbeat)
                        get_event_task.cancel()
                        yield f"event: heartbeat\ndata: {json.dumps({'timestamp': asyncio.get_event_loop().time()})}\n\n"
            finally:
                disconnect_task.cancel()

        except asyncio.CancelledError:
            logger.info(f"SSE stream cancelled for client {client_id}")
            raise
        except Exception as e:
            logger.error(
                f"Error in SSE event generator for client {client_id}: {e}",
                exc_info=True,
            )
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Unregister client on disconnect
            await self._sse_relay.unregister_client(client_id)

    @get_route(
        "/stream",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Server-Sent Events stream",
                "content": {"text/event-stream": {}},
            }
        },
    )
    async def stream_events(
        self,
        request: Request,
        user_info: dict = Depends(get_current_user),
        worker_ids: str | None = Query(
            None,
            description="Comma-separated list of worker IDs to filter events (e.g., 'worker1,worker2')",
        ),
        event_types: str | None = Query(
            None,
            description="Comma-separated list of event types to filter (e.g., 'worker.metrics.updated,worker.status.changed')",
        ),
    ) -> StreamingResponse:
        """Stream server-sent events for real-time UI updates.

        This endpoint streams worker-related events to connected clients:
        - Worker metrics updated
        - Worker status changed
        - Worker created/terminated
        - Labs data updated

        The stream includes periodic heartbeats and auto-reconnection support.

        Optional filtering by worker IDs and/or event types reduces bandwidth usage.

        (**Requires authenticated user.**)

        Args:
            request: FastAPI request object
            user_info: Current user information from authentication
            worker_ids: Comma-separated worker IDs to filter by
            event_types: Comma-separated event types to filter by

        Returns:
            StreamingResponse with SSE events

        Example:
            GET /api/events/stream?worker_ids=abc123,def456&event_types=worker.metrics.updated
        """
        # Parse comma-separated filters
        worker_ids_set = set(wid.strip() for wid in worker_ids.split(",") if wid.strip()) if worker_ids else None
        event_types_set = set(et.strip() for et in event_types.split(",") if et.strip()) if event_types else None

        return StreamingResponse(
            self._event_generator(request, user_info, worker_ids_set, event_types_set),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )
