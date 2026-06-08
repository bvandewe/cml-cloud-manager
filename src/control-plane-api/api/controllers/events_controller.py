"""SSE (Server-Sent Events) Controller for real-time UI updates."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from api.dependencies import get_current_user
from api.services import DualAuthService
from application.commands.pod_definition_read.project_pod_definition_ready_command import (
    ProjectPodDefinitionReadyCommand,
)
from application.commands.pod_definition_read.project_pod_definition_sync_failed_command import (
    ProjectPodDefinitionSyncFailedCommand,
)
from application.dtos.lablet_definition_dto import map_lablet_definition_to_summary_dto
from application.dtos.lablet_session_dto import map_lablet_session_to_summary_dto
from application.events.domain.cml_worker_events import _broadcast_worker_snapshot
from application.services.sse_event_relay import SSEEventRelay
from classy_fastapi.decorators import get as get_route
from classy_fastapi.decorators import post
from domain.repositories.cml_worker_repository import CMLWorkerRepository
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.repositories.lablet_definition_repository import LabletDefinitionRepository
from domain.repositories.lablet_session_repository import LabletSessionRepository
from fastapi import Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from neuroglia.dependency_injection import ServiceProviderBase
from neuroglia.mapping import Mapper
from neuroglia.mediation import Mediator
from neuroglia.mvc import ControllerBase
from neuroglia.serialization.json import JsonSerializer

logger = logging.getLogger(__name__)

# CloudEvent types emitted by Scenario Engine (G-12 / Phase 2)
CE_POD_DEFINITION_READY = "scenario_engine.pod_definition.ready.v1"
CE_POD_DEFINITION_SYNC_FAILED = "scenario_engine.pod_definition.sync_failed.v1"


def _lab_record_to_snapshot_dict(record) -> dict:
    """Convert a LabRecord aggregate to a snapshot dict for SSE broadcast.

    Matches the shape returned by GetLabRecordsQueryHandler for consistency
    between API responses and SSE snapshots.
    """
    s = record.state
    return {
        "id": record.id(),
        "lab_id": s.lab_id,
        "worker_id": s.worker_id,
        "worker_ip": s.worker_ip,
        "title": s.title,
        "description": s.description,
        "status": s.status.value if hasattr(s.status, "value") else str(s.status),
        "state": s.state,
        "owner_username": s.owner_username,
        "node_count": s.node_count,
        "link_count": s.link_count,
        "revision": s.revision,
        "source": s.source,
        "pending_action": s.pending_action,
        "created": s.cml_created_at.isoformat() if s.cml_created_at else None,
        "modified": s.modified_at.isoformat() if s.modified_at else None,
        "last_synced": s.last_synced_at.isoformat() if s.last_synced_at else None,
    }


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

            # Initial lab record snapshots (non-terminal lab records)
            try:
                if not scope:
                    scope = self.service_provider.create_scope()  # type: ignore[attr-defined]
                lab_record_repo = scope.get_required_service(LabRecordRepository)
                if lab_record_repo:
                    all_records = await lab_record_repo.get_all_async()
                    # Filter to non-terminal records only
                    records = [r for r in all_records if not r.is_terminal and not r.is_orphaned]
                    for record in records:
                        try:
                            snapshot = _lab_record_to_snapshot_dict(record)
                            await self._sse_relay.broadcast_event(
                                event_type="lab.snapshot",
                                data=snapshot,
                                source="domain.lab_record.snapshot",
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send lab record snapshot for {record.id()}: {e}")
            except Exception as e:
                logger.warning(f"Failed to send initial lab record snapshots: {e}")

            # Heartbeat interval (30 seconds)
            heartbeat_interval = 30

            async def check_disconnect():
                while True:
                    if await request.is_disconnected():
                        return
                    await asyncio.sleep(1.0)

            disconnect_task = asyncio.create_task(check_disconnect())
            shutdown_task = asyncio.create_task(self._sse_relay.shutdown_event.wait())

            try:
                # Stream events
                while True:
                    get_event_task = asyncio.create_task(event_queue.get())

                    done, pending = await asyncio.wait(
                        [get_event_task, disconnect_task, shutdown_task],
                        return_when=asyncio.FIRST_COMPLETED,
                        timeout=heartbeat_interval,
                    )

                    # Server shutdown (uvicorn reload / stop)
                    if shutdown_task in done:
                        logger.info(f"SSE relay shutting down, closing stream for client {client_id}")
                        get_event_task.cancel()
                        yield "event: system.sse.shutdown\ndata: {}\n\n"
                        break

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
                if not shutdown_task.done():
                    shutdown_task.cancel()

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

    # ==========================================================================
    # CloudEvent ingestion (Phase 2 / G-12) — Scenario Engine → CPA projection
    # ==========================================================================

    @post(
        "/",
        summary="Ingest CloudEvent",
        status_code=202,
        tags=["Events"],
        responses={
            202: {"description": "CloudEvent accepted (processed or known-unknown type)"},
            400: {"description": "Malformed CloudEvent (missing required fields)"},
            500: {"description": "Internal error projecting CloudEvent"},
        },
    )
    async def ingest_cloud_event(self, request: Request) -> Response:
        """Receive a CloudEvent from the Scenario Engine.

        Supports both structured-mode (``application/cloudevents+json``) and
        binary content-mode (``ce-*`` headers). Returns 202 even for unknown
        event types (forward compatibility — SE may emit new types ahead of
        CPA catching up). Returns 400 only when the envelope itself is
        malformed.
        """
        event = await _parse_cloud_event(request)
        if event is None:
            return Response(status_code=400, content="Invalid CloudEvent")

        event_type = event.get("type", "")
        subject = event.get("subject", "")
        data = event.get("data") or {}
        event_time = event.get("time")
        source = event.get("source", "")
        event_id = event.get("id", "")

        logger.info(
            "Received CloudEvent: type=%s id=%s subject=%s source=%s",
            event_type,
            event_id,
            subject,
            source,
        )

        try:
            if event_type == CE_POD_DEFINITION_READY:
                command = ProjectPodDefinitionReadyCommand(
                    pod_definition_id=data.get("pod_definition_id") or subject,
                    name=data.get("name", ""),
                    version=data.get("version", "v1"),
                    pod_type=data.get("pod_type", ""),
                    content_hash=data.get("content_hash", ""),
                    source_uri=data.get("source_uri"),
                    superseded_ids=list(data.get("superseded_ids", []) or []),
                    event_time=event_time,
                    raw_event=dict(data),
                )
                result = await self.mediator.execute_async(command)
                if not result.is_success:
                    logger.error(
                        "Failed to project pod_definition.ready event id=%s: %s",
                        event_id,
                        result.error_message,
                    )
                    return Response(status_code=500, content=result.error_message or "projection failed")
                return Response(status_code=202)

            if event_type == CE_POD_DEFINITION_SYNC_FAILED:
                command = ProjectPodDefinitionSyncFailedCommand(
                    pod_definition_id=data.get("pod_definition_id") or subject,
                    reason=data.get("reason", ""),
                    error_detail=data.get("error_detail"),
                    name=data.get("name", ""),
                    pod_type=data.get("pod_type", ""),
                    version=data.get("version", "v1"),
                    content_hash=data.get("content_hash", ""),
                    source_uri=data.get("source_uri"),
                    event_time=event_time,
                    raw_event=dict(data),
                )
                result = await self.mediator.execute_async(command)
                if not result.is_success:
                    logger.error(
                        "Failed to project pod_definition.sync_failed event id=%s: %s",
                        event_id,
                        result.error_message,
                    )
                    return Response(status_code=500, content=result.error_message or "projection failed")
                return Response(status_code=202)

            # Unknown / not-yet-handled event type — accept for forward
            # compatibility but log a warning so we notice.
            logger.warning("Unhandled CloudEvent type: %s id=%s", event_type, event_id)
            return Response(status_code=202)

        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("Error projecting CloudEvent %s: %s", event_type, exc)
            return Response(status_code=500, content=str(exc))


# ==============================================================================
# CloudEvent parsing helpers (module-level — mirror lablet-controller)
# ==============================================================================


async def _parse_cloud_event(request: Request) -> dict[str, Any] | None:
    """Parse a CloudEvent from the request (structured or binary mode).

    Structured mode: ``Content-Type: application/cloudevents+json`` — full
    envelope is in the JSON body.

    Binary mode: ``ce-*`` headers carry the envelope; body is the ``data``
    payload.

    Returns:
        Dict with ``type``, ``source``, ``subject``, ``id``, ``time``, ``data``.
        ``time`` is parsed into a timezone-aware ``datetime`` when present;
        otherwise ``None`` (handlers fall back to the server clock).
        Returns ``None`` if the envelope cannot be parsed.
    """
    content_type = request.headers.get("content-type", "")

    try:
        if "cloudevents+json" in content_type:
            body = await request.json()
            return {
                "type": body.get("type", ""),
                "source": body.get("source", ""),
                "subject": body.get("subject", ""),
                "id": body.get("id", ""),
                "time": _parse_event_time(body.get("time")),
                "data": body.get("data", {}),
            }
        # Binary content mode — metadata in ce-* headers.
        try:
            body = await request.json()
        except Exception:  # nosec B110 — body may be empty
            body = {}
        return {
            "type": request.headers.get("ce-type", ""),
            "source": request.headers.get("ce-source", ""),
            "subject": request.headers.get("ce-subject", ""),
            "id": request.headers.get("ce-id", ""),
            "time": _parse_event_time(request.headers.get("ce-time")),
            "data": body if body else {},
        }
    except Exception as exc:
        logger.error("Failed to parse CloudEvent: %s", exc)
        return None


def _parse_event_time(raw: Any) -> datetime | None:
    """Parse a CloudEvent ``time`` attribute (RFC 3339 string) to datetime.

    Returns ``None`` for missing or unparseable values. Always coerces to
    timezone-aware UTC.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        # Accept both "Z" and explicit offsets.
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None
