"""Discover Lab Records Command.

Discovery with:
- Status tracking via LabRecordStatus (DISCOVERED for new labs, mapped state for existing)
- Topology change detection (SHA-256 checksum → new LabRevision if changed)
- Orphan detection (DB labs not in CML scan → mark ORPHANED, don’t auto-delete)

Called by lablet-controller’s LabDiscoveryService after fetching labs
from CML. Per ADR-001: Control Plane API is the only component that writes to MongoDB.

Architecture ref: §7 (Discovery & Synchronisation), §8.2 (internal endpoints).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from domain.entities.lab_record import LabRecord
from domain.repositories.lab_record_repository import LabRecordRepository
from domain.value_objects.lab_topology_spec import LabTopologySpec
from lcm_core.domain.enums import CML_STATE_TO_LAB_RECORD_STATUS, LabRecordStatus
from neuroglia.core import OperationResult
from neuroglia.mediation import Command, CommandHandler
from opentelemetry import trace

from ..command_handler_base import CommandHandlerBase

log = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class DiscoverLabRecordsResult:
    """Result of lab records discovery operation."""

    synced: int  # Total labs processed
    discovered: int  # New lab records created (status=DISCOVERED)
    updated: int  # Existing lab records updated
    orphaned: int  # DB labs not in CML scan (marked ORPHANED)
    revisions_created: int  # Topology revisions detected
    errors: list[str]  # Any errors encountered


@dataclass
class DiscoverLabRecordsCommand(Command[OperationResult[DiscoverLabRecordsResult]]):
    """Command to discover lab records for a worker from CML scan data.

    Typed status and topology tracking.
    Called by lablet-controller's LabDiscoveryService after fetching labs from CML.

    Args:
        worker_id: ID of the worker hosting these labs.
        labs: List of lab data from CML (each dict has id, title, state, etc.).
        source: Source of the discovery (e.g., "lab-discovery-service").
    """

    worker_id: str = ""
    labs: list[dict] = field(default_factory=list)
    source: str = "lab-discovery-service"
    partial_scan: bool = False  # When True, skip orphan sweep (single-lab registration)


class DiscoverLabRecordsCommandHandler(
    CommandHandlerBase,
    CommandHandler[DiscoverLabRecordsCommand, OperationResult[DiscoverLabRecordsResult]],
):
    """Handle discovery of lab records from lablet-controller scan data."""

    def __init__(self, lab_record_repository: LabRecordRepository):
        self._lab_repository = lab_record_repository

    async def handle_async(self, request: DiscoverLabRecordsCommand) -> OperationResult[DiscoverLabRecordsResult]:
        """Handle lab records discovery with typed status and topology tracking.

        Flow:
        1. Fetch existing LabRecords for the worker
        2. For each lab in CML scan:
           a. New → Create with LabRecord.discover() (status=DISCOVERED)
           b. Existing → Update metadata, detect topology changes
        3. DB labs not in CML scan → Mark ORPHANED (don't auto-delete)
        4. Return discovery statistics
        """
        if not request.worker_id:
            return self.bad_request("worker_id is required")

        with tracer.start_as_current_span("discover_lab_records") as span:
            span.set_attribute("discovery.worker_id", request.worker_id)
            span.set_attribute("discovery.source", request.source)
            span.set_attribute("discovery.lab_count", len(request.labs))

            log.info(
                "🔍 Discovering %d labs for worker %s (source=%s)",
                len(request.labs),
                request.worker_id,
                request.source,
            )

            errors: list[str] = []
            discovered_count = 0
            updated_count = 0
            orphaned_count = 0
            revisions_created_count = 0

            # 1. Get existing lab records for this worker
            existing_records = await self._lab_repository.get_all_by_worker_async(request.worker_id)
            existing_by_lab_id: dict[str, LabRecord] = {r.state.lab_id: r for r in existing_records}

            # Track which CML lab IDs we've seen
            seen_lab_ids: set[str] = set()

            # 2. Process each lab from CML scan
            for lab_data in request.labs:
                lab_id = lab_data.get("id")
                if not lab_id:
                    errors.append("Lab missing 'id' field")
                    continue

                seen_lab_ids.add(lab_id)

                try:
                    if lab_id in existing_by_lab_id:
                        # Update existing record
                        existing = existing_by_lab_id[lab_id]
                        revision_created = self._update_existing_record(existing, lab_data)
                        await self._lab_repository.update_async(existing)
                        updated_count += 1
                        if revision_created:
                            revisions_created_count += 1
                    else:
                        # Discover new lab
                        new_record = self._create_discovered_record(request.worker_id, lab_data)
                        await self._lab_repository.add_async(new_record)
                        discovered_count += 1

                except Exception as e:
                    error_msg = f"Failed to process lab {lab_id}: {e}"
                    log.error(error_msg, exc_info=True)
                    errors.append(error_msg)

            # 3. Mark orphaned records (DB labs not in CML scan)
            #    Skip orphan sweep for partial scans (e.g. single-lab registration)
            #    to avoid false-orphaning labs not included in the partial payload.
            if request.partial_scan:
                log.info(
                    "🔍 Partial scan — skipping orphan sweep (only %d labs submitted)",
                    len(request.labs),
                )
            for lab_id, record in existing_by_lab_id.items():
                if request.partial_scan:
                    break
                if lab_id not in seen_lab_ids:
                    # Skip already terminal or orphaned records
                    if record.is_terminal or record.is_orphaned:
                        continue
                    try:
                        record.mark_orphaned()
                        await self._lab_repository.update_async(record)
                        orphaned_count += 1
                        log.info("🔍 Lab marked orphaned: lab_id=%s (not found in CML scan)", lab_id)
                    except Exception as e:
                        error_msg = f"Failed to orphan lab {lab_id}: {e}"
                        log.error(error_msg, exc_info=True)
                        errors.append(error_msg)

            result = DiscoverLabRecordsResult(
                synced=len(request.labs),
                discovered=discovered_count,
                updated=updated_count,
                orphaned=orphaned_count,
                revisions_created=revisions_created_count,
                errors=errors,
            )

            span.set_attribute("discovery.discovered", discovered_count)
            span.set_attribute("discovery.updated", updated_count)
            span.set_attribute("discovery.orphaned", orphaned_count)
            span.set_attribute("discovery.revisions_created", revisions_created_count)
            span.set_attribute("discovery.errors", len(errors))

            log.info(
                "✅ Lab discovery complete for worker %s: discovered=%d, updated=%d, orphaned=%d, revisions=%d, errors=%d",
                request.worker_id,
                discovered_count,
                updated_count,
                orphaned_count,
                revisions_created_count,
                len(errors),
            )

            return self.ok(result)

    def _create_discovered_record(self, worker_id: str, lab_data: dict) -> LabRecord:
        """Create a new LabRecord from discovery scan data."""
        record = LabRecord.discover(
            lab_id=lab_data["id"],
            worker_id=worker_id,
            title=lab_data.get("title"),
            description=lab_data.get("description"),
            state=lab_data.get("state", "DEFINED_ON_CORE"),
            owner_username=lab_data.get("owner"),
            node_count=lab_data.get("node_count", 0),
            link_count=lab_data.get("link_count", 0),
            notes=lab_data.get("notes"),
            worker_ip=lab_data.get("worker_ip"),
            based_on_definition_id=lab_data.get("based_on_definition_id"),
        )

        # Build and attach topology_spec from discovery node/link data
        self._apply_topology_from_discovery(record, lab_data)

        return record

    def _update_existing_record(self, record: LabRecord, lab_data: dict) -> bool:
        """Update an existing LabRecord with fresh CML data.

        Returns True if a topology revision was created.
        """
        now = datetime.now(timezone.utc)
        revision_created = False

        # Link to definition if provided and not already set
        # (pipeline-lab-resolve sends based_on_definition_id for labs
        # that were imported from a LabletDefinition)
        incoming_def_id = lab_data.get("based_on_definition_id")
        if incoming_def_id and not record.state.based_on_definition_id:
            record.state.based_on_definition_id = incoming_def_id
            log.info(
                "Linked LabRecord %s to definition %s",
                record.state.lab_id,
                incoming_def_id,
            )

        # Parse cml_modified_at from discovery data
        cml_modified_at = None
        raw_modified = lab_data.get("modified_at")
        if raw_modified:
            try:
                parsed = datetime.fromisoformat(raw_modified) if isinstance(raw_modified, str) else raw_modified
                # Ensure UTC-aware (CML may return naive datetimes)
                cml_modified_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                cml_modified_at = now

        # Update metadata via legacy sync path (backward compat)
        record.update_from_cml(
            title=lab_data.get("title", ""),
            description=lab_data.get("description"),
            notes=lab_data.get("notes"),
            state=lab_data.get("state", ""),
            owner_username=lab_data.get("owner"),
            owner_fullname=lab_data.get("owner_fullname"),
            node_count=lab_data.get("node_count", 0),
            link_count=lab_data.get("link_count", 0),
            groups=lab_data.get("groups"),
            cml_modified_at=cml_modified_at,
            worker_ip=lab_data.get("worker_ip"),
        )

        # Map CML state to typed status (if different from current)
        cml_state = lab_data.get("state", "")
        mapped_status = CML_STATE_TO_LAB_RECORD_STATUS.get(cml_state)
        if mapped_status and mapped_status != record.state.status:
            # Direct status update for discovery sync (no transition guard for sync)
            record.state.status = mapped_status

        # Build topology_spec from discovery node/link data
        self._apply_topology_from_discovery(record, lab_data)

        # Topology change detection via checksum
        raw_yaml = lab_data.get("topology_yaml") or lab_data.get("raw_yaml")
        if raw_yaml:
            try:
                topology_spec = LabTopologySpec(
                    nodes=(),
                    links=(),
                    annotations=(),
                    raw_yaml=raw_yaml,
                )
                previous_revision = record.state.revision
                record.update_topology(topology_spec, change_summary="Discovery sync")
                revision_created = record.state.revision > previous_revision
            except Exception as e:
                log.warning(
                    "Failed to parse topology for lab %s: %s",
                    record.state.lab_id,
                    e,
                )

        # Un-orphan if previously orphaned and now found again
        if record.is_orphaned:
            record.state.status = LabRecordStatus.DISCOVERED

        return revision_created

    def _apply_topology_from_discovery(self, record: LabRecord, lab_data: dict) -> None:
        """Build and apply topology_spec from discovery node/link summary data.

        This is the hybrid topology approach: node/link summaries are collected
        during discovery and stored as a LabTopologySpec. Full YAML download
        remains a separate user-triggered operation.
        """
        nodes_data = lab_data.get("nodes", [])
        links_data = lab_data.get("links", [])

        if not nodes_data and not links_data:
            return

        try:
            from domain.value_objects.lab_topology_spec import TopologyLink, TopologyNode

            nodes = tuple(
                TopologyNode(
                    label=n.get("label", ""),
                    node_definition=n.get("node_definition", ""),
                    x=n.get("x", 0),
                    y=n.get("y", 0),
                    tags={t: "" for t in n.get("tags", [])} if isinstance(n.get("tags"), list) else n.get("tags", {}),
                )
                for n in nodes_data
            )

            links = tuple(
                TopologyLink(
                    source_node=lnk.get("node_a", ""),
                    source_interface=lnk.get("interface_a", ""),
                    target_node=lnk.get("node_b", ""),
                    target_interface=lnk.get("interface_b", ""),
                    label=lnk.get("label"),
                )
                for lnk in links_data
            )

            topology_spec = LabTopologySpec(
                nodes=nodes,
                links=links,
            )
            record.state.topology_spec = topology_spec.to_dict()

        except Exception as e:
            log.warning(
                "Failed to build topology_spec for lab %s: %s",
                lab_data.get("id"),
                e,
            )
