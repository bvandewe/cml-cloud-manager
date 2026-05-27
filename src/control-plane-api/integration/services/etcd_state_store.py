"""etcd State Store for LabletSession and CMLWorker state coordination.

This module provides higher-level state management operations built on top of EtcdClient:
- Session state tracking with watch capabilities
- Worker state and port allocation management
- Leader election support for distributed coordination

Key patterns follow ADR-005: etcd for operational state, MongoDB for spec storage.

Key Structure:
    /lcm/sessions/{id}/state      - LabletSession state (e.g., "RUNNING")
    /lcm/workers/{id}/state       - CMLWorker operational state
    /lcm/workers/{id}/ports       - Port allocations JSON
    /lcm/{service}/leader         - Leader election key
"""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from integration.services.etcd_client import EtcdClient, EtcdLease

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

log = logging.getLogger(__name__)


@dataclass
class SessionStateChange:
    """Represents a state change event for a LabletSession."""

    session_id: str
    old_state: str | None
    new_state: str | None  # None indicates deletion
    timestamp: datetime
    revision: int


@dataclass
class WorkerPortAllocation:
    """Represents port allocations for a worker."""

    worker_id: str
    allocations: dict[str, dict[str, int]]  # session_id -> {port_name: port_number}
    revision: int


@dataclass
class LeaderInfo:
    """Information about current leader."""

    leader_id: str
    service_name: str
    lease_id: int
    acquired_at: datetime


class EtcdStateStore:
    """High-level state store operations using etcd.

    This class provides domain-specific state management for:
    - LabletSession lifecycle states
    - CMLWorker operational states
    - Port allocation tracking
    - Leader election for distributed services

    Example:
        ```python
        store = EtcdStateStore(etcd_client)

        # Track session state
        await store.set_session_state("sess-123", "RUNNING")
        state = await store.get_session_state("sess-123")

        # Watch for state changes
        async for change in store.watch_sessions_by_state("PENDING"):
            print(f"Session {change.session_id} changed to {change.new_state}")
        ```
    """

    # Key patterns (relative to /ccm prefix configured in EtcdClient)
    SESSION_STATE_KEY = "/sessions/{id}/state"
    SESSION_METADATA_KEY = "/sessions/{id}/metadata"
    SESSION_DESIRED_STATE_KEY = "/sessions/{id}/desired_state"  # ADR-034 Sprint E: Desired lifecycle state (spec)
    WORKER_STATE_KEY = "/workers/{id}/state"
    WORKER_DESIRED_STATE_KEY = "/workers/{id}/desired_state"  # ADR-015: Spec for reconciliation
    WORKER_LICENSE_KEY = "/workers/{id}/license"  # ADR-016: License pending operation for reactive reconciliation
    WORKER_PORTS_KEY = "/workers/{id}/ports"
    LAB_RECORD_PENDING_ACTION_KEY = "/lab_records/{id}/pending_action"  # AD-023: Lab action reactive reconciliation
    DEFINITION_CONTENT_SYNC_KEY = "/definitions/{id}/content_sync"  # AD-CS-001: Content sync reactive reconciliation
    SESSION_OBSERVE_RESOURCES_KEY = "/sessions/{id}/observe_resources"  # ADR-030: Manual observation trigger
    WORKER_DISCOVER_LABS_KEY = "/workers/{id}/discover_labs"  # ADR-041 Phase 2: Targeted lab discovery trigger
    LEADER_KEY = "/{service}/leader"

    def __init__(self, etcd_client: EtcdClient):
        """Initialize the state store.

        Args:
            etcd_client: Configured EtcdClient instance
        """
        self._etcd = etcd_client

    # -------------------------------------------------------------------------
    # Session State Operations
    # -------------------------------------------------------------------------

    async def get_session_state(self, session_id: str) -> str | None:
        """Get the current state of a LabletSession.

        Args:
            session_id: The session ID

        Returns:
            State string (e.g., "RUNNING") or None if not found
        """
        key = self.SESSION_STATE_KEY.format(id=session_id)
        result = await self._etcd.get(key)
        return result.value if result else None

    async def set_session_state(
        self,
        session_id: str,
        state: str,
        lease_id: int | None = None,
    ) -> None:
        """Set the state of a LabletSession.

        Args:
            session_id: The session ID
            state: The new state (e.g., "RUNNING", "TERMINATED")
            lease_id: Optional lease ID for ephemeral state
        """
        key = self.SESSION_STATE_KEY.format(id=session_id)
        await self._etcd.put(key, state, lease_id=lease_id)
        log.debug(f"Set session {session_id} state to {state}")

    async def get_session_desired_state(self, session_id: str) -> str | None:
        """Get the desired state (spec) of a LabletSession.

        ADR-034 Sprint E / ADR-015 pattern: desired_status = spec (what user wants).

        Args:
            session_id: The session ID

        Returns:
            Desired state string or None if not found
        """
        key = self.SESSION_DESIRED_STATE_KEY.format(id=session_id)
        result = await self._etcd.get(key)
        return result.value if result else None

    async def set_session_desired_state(self, session_id: str, desired_state: str) -> None:
        """Set the desired state (spec) of a LabletSession.

        ADR-034 Sprint E / ADR-015 pattern: This triggers watch-based
        reconciliation in lablet-controller. When desired_state != state,
        lablet-controller will reconcile.

        Args:
            session_id: The session ID
            desired_state: The desired state (e.g., "running", "stopped", "terminated")
        """
        key = self.SESSION_DESIRED_STATE_KEY.format(id=session_id)
        await self._etcd.put(key, desired_state)
        log.info(f"Set session {session_id} desired_state to {desired_state}")

    async def delete_session_state(self, session_id: str) -> bool:
        """Delete the state of a LabletSession.

        Args:
            session_id: The session ID

        Returns:
            True if deleted, False if not found
        """
        key = self.SESSION_STATE_KEY.format(id=session_id)
        deleted = await self._etcd.delete(key)

        # Also delete metadata if present
        metadata_key = self.SESSION_METADATA_KEY.format(id=session_id)
        await self._etcd.delete(metadata_key)

        # Also delete desired_state if present (ADR-034 Sprint E)
        desired_key = self.SESSION_DESIRED_STATE_KEY.format(id=session_id)
        await self._etcd.delete(desired_key)

        return deleted

    async def get_sessions_by_state(self, state: str) -> list[str]:
        """Get all session IDs in a specific state.

        Args:
            state: The state to filter by (e.g., "PENDING")

        Returns:
            List of session IDs in the specified state
        """
        prefix = "/sessions/"
        results = await self._etcd.get_prefix(prefix)

        return [kv.key.split("/")[2] for kv in results if kv.key.endswith("/state") and kv.value == state]  # Extract session_id from /sessions/{id}/state

    async def get_all_session_states(self) -> dict[str, str]:
        """Get all session states.

        Returns:
            Dictionary of session_id -> state
        """
        prefix = "/sessions/"
        results = await self._etcd.get_prefix(prefix)

        states = {}
        for kv in results:
            if kv.key.endswith("/state"):
                session_id = kv.key.split("/")[2]
                states[session_id] = kv.value

        return states

    async def watch_session_state(self, session_id: str, start_revision: int | None = None) -> AsyncIterator[SessionStateChange]:
        """Watch a specific session for state changes.

        Args:
            session_id: The session ID to watch
            start_revision: Optional revision to start from

        Yields:
            SessionStateChange events
        """
        key = self.SESSION_STATE_KEY.format(id=session_id)
        current_state = await self.get_session_state(session_id)

        async for event in self._etcd.watch(key, start_revision=start_revision):
            change = SessionStateChange(
                session_id=session_id,
                old_state=current_state,
                new_state=event.value,
                timestamp=datetime.now(timezone.utc),
                revision=event.mod_revision,
            )
            current_state = event.value
            yield change

    async def watch_sessions_by_state(self, target_state: str, start_revision: int | None = None) -> AsyncIterator[SessionStateChange]:
        """Watch for sessions entering a specific state.

        Args:
            target_state: The state to watch for (e.g., "PENDING", "RUNNING")
            start_revision: Optional revision to start from

        Yields:
            SessionStateChange events for sessions entering the target state
        """
        prefix = "/sessions/"
        state_cache: dict[str, str | None] = {}

        async for event in self._etcd.watch_prefix(prefix, start_revision=start_revision):
            if not event.key.endswith("/state"):
                continue

            session_id = event.key.split("/")[2]
            old_state = state_cache.get(session_id)
            new_state = event.value

            # Only yield if transitioning TO the target state
            if new_state == target_state or (new_state is None and old_state == target_state):
                yield SessionStateChange(
                    session_id=session_id,
                    old_state=old_state,
                    new_state=new_state,
                    timestamp=datetime.now(timezone.utc),
                    revision=event.mod_revision,
                )

            state_cache[session_id] = new_state

    # -------------------------------------------------------------------------
    # Worker State Operations
    # -------------------------------------------------------------------------

    async def get_worker_state(self, worker_id: str) -> str | None:
        """Get the operational state of a CMLWorker.

        Args:
            worker_id: The worker ID

        Returns:
            State string or None if not found
        """
        key = self.WORKER_STATE_KEY.format(id=worker_id)
        result = await self._etcd.get(key)
        return result.value if result else None

    async def set_worker_state(self, worker_id: str, state: str) -> None:
        """Set the operational state of a CMLWorker.

        Args:
            worker_id: The worker ID
            state: The new state
        """
        key = self.WORKER_STATE_KEY.format(id=worker_id)
        await self._etcd.put(key, state)
        log.debug(f"Set worker {worker_id} state to {state}")

    async def get_worker_desired_state(self, worker_id: str) -> str | None:
        """Get the desired state (spec) of a CMLWorker.

        ADR-015: desired_status = spec (what user wants)

        Args:
            worker_id: The worker ID

        Returns:
            Desired state string or None if not found
        """
        key = self.WORKER_DESIRED_STATE_KEY.format(id=worker_id)
        result = await self._etcd.get(key)
        return result.value if result else None

    async def set_worker_desired_state(self, worker_id: str, desired_state: str) -> None:
        """Set the desired state (spec) of a CMLWorker.

        ADR-015: This triggers watch-based reconciliation in worker-controller.
        When desired_state != state, worker-controller will reconcile.

        Args:
            worker_id: The worker ID
            desired_state: The desired state (e.g., "RUNNING", "STOPPED", "TERMINATED")
        """
        key = self.WORKER_DESIRED_STATE_KEY.format(id=worker_id)
        await self._etcd.put(key, desired_state)
        log.info(f"Set worker {worker_id} desired_state to {desired_state}")

    async def delete_worker_state(self, worker_id: str) -> bool:
        """Delete all state for a worker (state + desired_state + ports).

        Args:
            worker_id: The worker ID

        Returns:
            True if any keys deleted
        """
        state_deleted = await self._etcd.delete(self.WORKER_STATE_KEY.format(id=worker_id))
        desired_deleted = await self._etcd.delete(self.WORKER_DESIRED_STATE_KEY.format(id=worker_id))
        license_deleted = await self._etcd.delete(self.WORKER_LICENSE_KEY.format(id=worker_id))
        ports_deleted = await self._etcd.delete(self.WORKER_PORTS_KEY.format(id=worker_id))
        return state_deleted or desired_deleted or license_deleted or ports_deleted

    # -------------------------------------------------------------------------
    # Worker License Pending Operations (ADR-016)
    # -------------------------------------------------------------------------

    async def get_worker_license_pending(self, worker_id: str) -> dict | None:
        """Get the pending license operation for a worker.

        ADR-016: License operations are stored as pending_operation for
        reactive watch-based reconciliation by worker-controller.

        Args:
            worker_id: The worker ID

        Returns:
            Dict with operation and optional token, or None if no pending operation
            Example: {"operation": "register", "token": "abc123"}
                     {"operation": "deregister"}
        """
        key = self.WORKER_LICENSE_KEY.format(id=worker_id)
        result = await self._etcd.get(key)
        if not result:
            return None
        return json.loads(result.value)

    async def set_worker_license_pending(
        self,
        worker_id: str,
        operation: str,
        token: str | None = None,
        reregister: bool = False,
    ) -> None:
        """Set a pending license operation for a worker.

        ADR-016: This triggers watch-based reconciliation in worker-controller.
        Worker-controller watches /workers/{id}/license for changes.

        Args:
            worker_id: The worker ID
            operation: The operation type ("register" or "deregister")
            token: The license token (required for register, ignored for deregister)
            reregister: Whether this is a re-registration (optional)
        """
        key = self.WORKER_LICENSE_KEY.format(id=worker_id)
        data = {"operation": operation}
        if operation == "register":
            data["token"] = token
            data["reregister"] = reregister
        await self._etcd.put(key, json.dumps(data))
        log.info(f"Set worker {worker_id} license pending: {operation}")

    async def delete_worker_license_pending(self, worker_id: str) -> bool:
        """Delete the pending license operation for a worker.

        Called after license operation completes (success or failure).

        Args:
            worker_id: The worker ID

        Returns:
            True if deleted, False if not found
        """
        key = self.WORKER_LICENSE_KEY.format(id=worker_id)
        deleted = await self._etcd.delete(key)
        if deleted:
            log.info(f"Deleted worker {worker_id} license pending")
        return deleted

    # -------------------------------------------------------------------------
    # Port Allocation Operations
    # -------------------------------------------------------------------------

    async def get_worker_ports(self, worker_id: str) -> WorkerPortAllocation | None:
        """Get port allocations for a worker.

        Args:
            worker_id: The worker ID

        Returns:
            WorkerPortAllocation or None if no allocations
        """
        key = self.WORKER_PORTS_KEY.format(id=worker_id)
        result = await self._etcd.get(key)

        if not result:
            return None

        allocations = json.loads(result.value)
        return WorkerPortAllocation(
            worker_id=worker_id,
            allocations=allocations,
            revision=result.mod_revision,
        )

    async def set_worker_ports(self, worker_id: str, allocations: dict[str, dict[str, int]]) -> None:
        """Set port allocations for a worker.

        Args:
            worker_id: The worker ID
            allocations: Dict of session_id -> {port_name: port_number}
        """
        key = self.WORKER_PORTS_KEY.format(id=worker_id)
        await self._etcd.put(key, json.dumps(allocations))
        log.debug(f"Updated port allocations for worker {worker_id}")

    async def allocate_session_ports(
        self,
        worker_id: str,
        session_id: str,
        ports: dict[str, int],
    ) -> bool:
        """Atomically allocate ports for a session on a worker.

        Uses compare-and-swap to prevent race conditions.

        Args:
            worker_id: The worker ID
            session_id: The session ID
            ports: Dict of port_name -> port_number

        Returns:
            True if allocation succeeded, False if conflict
        """
        # Get current allocations
        current = await self.get_worker_ports(worker_id)
        allocations = current.allocations if current else {}

        # Check for conflicts (port already in use)
        used_ports = set()
        for inst_ports in allocations.values():
            used_ports.update(inst_ports.values())

        for port in ports.values():
            if port in used_ports:
                log.warning(f"Port {port} already allocated on worker {worker_id}")
                return False

        # Add new allocation
        allocations[session_id] = ports

        # TODO: Use etcd transaction for true atomicity
        # For now, simple put (acceptable for initial implementation)
        await self.set_worker_ports(worker_id, allocations)
        log.info(f"Allocated ports {ports} for session {session_id} on worker {worker_id}")
        return True

    async def release_session_ports(self, worker_id: str, session_id: str) -> dict[str, int] | None:
        """Release ports allocated to a session.

        Args:
            worker_id: The worker ID
            session_id: The session ID

        Returns:
            The released ports, or None if session had no allocations
        """
        current = await self.get_worker_ports(worker_id)
        if not current or session_id not in current.allocations:
            return None

        released = current.allocations.pop(session_id)
        await self.set_worker_ports(worker_id, current.allocations)

        log.info(f"Released ports {released} for session {session_id} on worker {worker_id}")
        return released

    async def get_allocated_ports_for_worker(self, worker_id: str) -> set[int]:
        """Get all currently allocated ports for a worker.

        Args:
            worker_id: The worker ID

        Returns:
            Set of allocated port numbers
        """
        current = await self.get_worker_ports(worker_id)
        if not current:
            return set()

        ports = set()
        for inst_ports in current.allocations.values():
            ports.update(inst_ports.values())
        return ports

    # -------------------------------------------------------------------------
    # Leader Election
    # -------------------------------------------------------------------------

    async def try_acquire_leadership(
        self,
        service_name: str,
        leader_id: str,
        lease_ttl: int | None = None,
    ) -> tuple[bool, EtcdLease | None]:
        """Try to acquire leadership for a service.

        Uses etcd lease-based leader election. The leader must maintain
        the lease via keepalive to retain leadership.

        Args:
            service_name: Name of the service (e.g., "scheduler")
            leader_id: Unique identifier for this leader candidate
            lease_ttl: Lease TTL in seconds (uses default if not specified)

        Returns:
            Tuple of (is_leader, lease) - lease is None if not leader
        """
        key = self.LEADER_KEY.format(service=service_name)

        # Create a lease for this leadership attempt
        lease = await self._etcd.grant_lease(lease_ttl)

        # Try to create the key (only succeeds if not exists)
        leader_data = json.dumps(
            {
                "leader_id": leader_id,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        is_leader = await self._etcd.put_if_not_exists(key, leader_data, lease_id=lease.lease_id)

        if is_leader:
            log.info(f"🏆 Acquired leadership for {service_name} as {leader_id}")
            return True, lease
        else:
            # Not leader, revoke our unused lease
            await self._etcd.revoke_lease(lease.lease_id)
            log.debug(f"Failed to acquire leadership for {service_name} (another leader exists)")
            return False, None

    async def get_current_leader(self, service_name: str) -> LeaderInfo | None:
        """Get the current leader for a service.

        Args:
            service_name: Name of the service

        Returns:
            LeaderInfo or None if no leader
        """
        key = self.LEADER_KEY.format(service=service_name)
        result = await self._etcd.get(key)

        if not result:
            return None

        data = json.loads(result.value)
        return LeaderInfo(
            leader_id=data["leader_id"],
            service_name=service_name,
            lease_id=result.lease_id or 0,
            acquired_at=datetime.fromisoformat(data["acquired_at"]),
        )

    async def watch_leadership(self, service_name: str) -> AsyncIterator[LeaderInfo | None]:
        """Watch for leadership changes.

        Args:
            service_name: Name of the service to watch

        Yields:
            LeaderInfo when leadership changes, None when leadership is lost
        """
        key = self.LEADER_KEY.format(service=service_name)

        async for event in self._etcd.watch(key):
            if event.event_type == "DELETE" or event.value is None:
                yield None
            else:
                data = json.loads(event.value)
                yield LeaderInfo(
                    leader_id=data["leader_id"],
                    service_name=service_name,
                    lease_id=0,  # Not available from watch event
                    acquired_at=datetime.fromisoformat(data["acquired_at"]),
                )

    async def release_leadership(self, service_name: str, lease_id: int) -> None:
        """Release leadership by revoking the lease.

        Args:
            service_name: Name of the service
            lease_id: The lease ID to revoke
        """
        await self._etcd.revoke_lease(lease_id)
        log.info(f"Released leadership for {service_name}")

    # -------------------------------------------------------------------------
    # Lab Record Pending Action Operations (AD-023)
    # -------------------------------------------------------------------------

    async def get_lab_pending_action(self, lab_record_id: str) -> dict | None:
        """Get the pending action for a lab record.

        AD-023: Lab actions are stored as pending_action for
        reactive watch-based reconciliation by lablet-controller.

        Args:
            lab_record_id: The lab record aggregate ID

        Returns:
            Dict with action details, or None if no pending action.
            Example: {"action": "start", "lab_id": "lab-abc", "worker_id": "w-123",
                       "requested_at": "2025-01-01T00:00:00Z"}
        """
        key = self.LAB_RECORD_PENDING_ACTION_KEY.format(id=lab_record_id)
        result = await self._etcd.get(key)
        if not result:
            return None
        return json.loads(result.value)

    async def set_lab_pending_action(
        self,
        lab_record_id: str,
        action: str,
        lab_id: str,
        worker_id: str,
        requested_at: str | None = None,
    ) -> None:
        """Set a pending action for a lab record.

        AD-023: This triggers watch-based reconciliation in lablet-controller.
        LabRecordReconciler watches /lab_records/ prefix for changes.

        Args:
            lab_record_id: The lab record aggregate ID
            action: The action type ("start", "stop", "wipe", "delete")
            lab_id: The CML lab ID on the worker
            worker_id: The CML worker ID hosting the lab
            requested_at: ISO timestamp of request (defaults to now)
        """
        key = self.LAB_RECORD_PENDING_ACTION_KEY.format(id=lab_record_id)
        data = {
            "action": action,
            "lab_id": lab_id,
            "worker_id": worker_id,
            "requested_at": requested_at or datetime.now(timezone.utc).isoformat(),
        }
        await self._etcd.put(key, json.dumps(data))
        log.info(f"Set lab record {lab_record_id} pending action: {action} (lab={lab_id}, worker={worker_id})")

    async def delete_lab_pending_action(self, lab_record_id: str) -> bool:
        """Delete the pending action for a lab record.

        Called after lab action completes (success or failure) or is cleared.

        Args:
            lab_record_id: The lab record aggregate ID

        Returns:
            True if deleted, False if not found
        """
        key = self.LAB_RECORD_PENDING_ACTION_KEY.format(id=lab_record_id)
        deleted = await self._etcd.delete(key)
        if deleted:
            log.info(f"Deleted lab record {lab_record_id} pending action")
        return deleted

    # -------------------------------------------------------------------------
    # LabletDefinition Content Sync (AD-CS-001)
    # -------------------------------------------------------------------------

    async def get_definition_content_sync(self, definition_id: str) -> dict | None:
        """Get the pending content sync request for a definition.

        AD-CS-001: Content sync requests are stored for reactive watch-based
        reconciliation by lablet-controller's ContentSyncService.

        Args:
            definition_id: The lablet definition aggregate ID

        Returns:
            Dict with sync request details, or None if no pending sync.
            Example: {"name": "ccna-routing", "version": "1.0.0",
                       "requested_by": "admin", "requested_at": "2025-01-01T00:00:00Z"}
        """
        key = self.DEFINITION_CONTENT_SYNC_KEY.format(id=definition_id)
        result = await self._etcd.get(key)
        if not result:
            return None
        return json.loads(result.value)

    async def set_definition_content_sync(
        self,
        definition_id: str,
        name: str,
        version: str,
        form_qualified_name: str = "",
        requested_by: str = "",
        requested_at: str | None = None,
    ) -> None:
        """Set a pending content sync request for a definition.

        AD-CS-001: This triggers watch-based reconciliation in lablet-controller.
        ContentSyncService watches /definitions/ prefix for content_sync keys.

        Args:
            definition_id: The lablet definition aggregate ID
            name: Definition name
            version: Definition version
            form_qualified_name: FQN for content lookup
            requested_by: User/system that requested sync
            requested_at: ISO timestamp of request (defaults to now)
        """
        key = self.DEFINITION_CONTENT_SYNC_KEY.format(id=definition_id)
        data = {
            "name": name,
            "version": version,
            "form_qualified_name": form_qualified_name,
            "requested_by": requested_by,
            "requested_at": requested_at or datetime.now(timezone.utc).isoformat(),
        }
        await self._etcd.put(key, json.dumps(data))
        log.info(f"Set definition {definition_id} content sync: name={name}, version={version}, fqn={form_qualified_name}")

    async def delete_definition_content_sync(self, definition_id: str) -> bool:
        """Delete the pending content sync request for a definition.

        Called after content sync completes (success or failure) to
        clean up the etcd key.

        Args:
            definition_id: The lablet definition aggregate ID

        Returns:
            True if deleted, False if not found
        """
        key = self.DEFINITION_CONTENT_SYNC_KEY.format(id=definition_id)
        deleted = await self._etcd.delete(key)
        if deleted:
            log.info(f"Deleted definition {definition_id} content sync key")
        return deleted

    # -------------------------------------------------------------------------
    # LabletSession Observe Resources (ADR-030)
    # -------------------------------------------------------------------------

    async def set_session_observe_resources(
        self,
        session_id: str,
        requested_by: str = "",
        requested_at: str | None = None,
    ) -> None:
        """Set a pending observe-resources request for a session.

        ADR-030: This triggers watch-based reconciliation in lablet-controller.
        LabletReconciler watches /sessions/ prefix and reacts to observe_resources keys.

        Args:
            session_id: The lablet session aggregate ID
            requested_by: User/system that requested observation
            requested_at: ISO timestamp of request (defaults to now)
        """
        key = self.SESSION_OBSERVE_RESOURCES_KEY.format(id=session_id)
        data = {
            "session_id": session_id,
            "requested_by": requested_by,
            "requested_at": requested_at or datetime.now(timezone.utc).isoformat(),
        }
        await self._etcd.put(key, json.dumps(data))
        log.info(f"Set session {session_id} observe_resources: requested_by={requested_by}")

    async def delete_session_observe_resources(self, session_id: str) -> bool:
        """Delete the pending observe-resources request for a session.

        Called after observation completes or is no longer applicable.

        Args:
            session_id: The lablet session aggregate ID

        Returns:
            True if deleted, False if not found
        """
        key = self.SESSION_OBSERVE_RESOURCES_KEY.format(id=session_id)
        deleted = await self._etcd.delete(key)
        if deleted:
            log.info(f"Deleted session {session_id} observe_resources key")
        return deleted

    # -------------------------------------------------------------------------
    # Worker Lab Discovery (ADR-041 Phase 2)
    # -------------------------------------------------------------------------

    async def set_worker_discover_labs(
        self,
        worker_id: str,
        lab_ids: list[str],
        source: str,
        triggered_at: str | None = None,
    ) -> None:
        """Set a lab discovery trigger for a worker.

        ADR-041 Phase 2: This triggers watch-based targeted discovery in
        lablet-controller. LabDiscoveryService watches /workers/ prefix for
        discover_labs keys and reacts immediately.

        Args:
            worker_id: The CML worker ID where new labs were detected
            lab_ids: CML lab IDs detected (informational for targeted scan)
            source: Source of the trigger (e.g., "websocket-lab-stats")
            triggered_at: ISO timestamp (defaults to now)
        """
        key = self.WORKER_DISCOVER_LABS_KEY.format(id=worker_id)
        data = {
            "lab_ids": lab_ids,
            "source": source,
            "triggered_at": triggered_at or datetime.now(timezone.utc).isoformat(),
        }
        await self._etcd.put(key, json.dumps(data))
        log.info(f"Set worker {worker_id} discover_labs: lab_ids={lab_ids}, source={source}")

    async def delete_worker_discover_labs(self, worker_id: str) -> bool:
        """Delete the pending lab discovery trigger for a worker.

        Called after lablet-controller completes targeted discovery.

        Args:
            worker_id: The CML worker ID

        Returns:
            True if deleted, False if not found
        """
        key = self.WORKER_DISCOVER_LABS_KEY.format(id=worker_id)
        deleted = await self._etcd.delete(key)
        if deleted:
            log.info(f"Deleted worker {worker_id} discover_labs key")
        return deleted

    # -------------------------------------------------------------------------
    # Health & Utilities
    # -------------------------------------------------------------------------

    async def health(self) -> bool:
        """Check if the state store is healthy.

        Returns:
            True if healthy
        """
        return await self._etcd.health()

    async def cleanup_session(self, session_id: str) -> None:
        """Clean up all state for a terminated session.

        Args:
            session_id: The session ID to clean up
        """
        await self.delete_session_state(session_id)
        log.debug(f"Cleaned up state for session {session_id}")

    # -------------------------------------------------------------------------
    # Service Configuration (Neuroglia DI Pattern)
    # -------------------------------------------------------------------------

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Configure EtcdStateStore in the application builder.

        Requires EtcdClient to be configured first.

        Args:
            builder: WebApplicationBuilder instance for service registration
        """
        log.info("🔧 Configuring etcd State Store...")

        # Get the EtcdClient from builder services (already registered)
        # Note: We defer construction until services are built
        from neuroglia.dependency_injection import ServiceProviderBase

        def _factory(sp: ServiceProviderBase) -> "EtcdStateStore":
            etcd_client = sp.get_required_service(EtcdClient)
            return EtcdStateStore(etcd_client)

        builder.services.add_singleton(EtcdStateStore, implementation_factory=_factory)
        log.info("✅ etcd State Store registered")
