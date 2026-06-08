"""PodDefinition read model — CPA-side projection of SE PodDefinition state.

Owned by CPA, populated by the
``ProjectPodDefinitionReady`` / ``ProjectPodDefinitionSyncFailed`` projection
commands invoked by the CloudEvent ingestion controller. Read by the UI and
by ``ContentDrivenTemplateLoader`` (G-09).

ADR-044 / G-12 / AD-CSI-007 — projection is **last-write-wins** from the SE
event payload (Q-05 resolution). CPA never mutates this collection through
any command other than the projection handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PodDefinitionReadModel:
    """Read-only projection of a Scenario-Engine ``PodDefinition`` aggregate.

    Mirrors the subset of SE state CPA needs to (a) display the active /
    superseded / failed PodDefinitions in the UI and (b) drive the upcoming
    content-driven pipeline loader (G-09). Source of truth lives in SE.

    Attributes:
        id: PodDefinition aggregate id from SE (primary key).
        name: PodDefinition logical name (unique with ``pod_type`` modulo
            version + content_hash).
        version: Content version string (e.g. ``"v1"``).
        pod_type: Pod type string (e.g. ``"cml_on_aws"``).
        status: Lifecycle status — ``"READY"``, ``"SUPERSEDED"``, ``"FAILED"``.
        content_hash: SHA-256 of the source package.
        source_uri: BlobStorage URI of the source package.
        error_message: Failure summary when ``status == "FAILED"``.
        error_detail: Optional structured error detail.
        last_event_at: Timestamp of the most recent projected event.
            Used as a staleness guard — out-of-order events with an older
            timestamp are dropped (AD-CSI-015).
        projected_at: Timestamp of the last projection write (server clock).
        raw_event: Full event payload kept for debuggability / replay.
    """

    id: str
    name: str
    version: str
    pod_type: str
    status: str
    content_hash: str
    source_uri: str | None = None
    error_message: str | None = None
    error_detail: str | None = None
    last_event_at: datetime | None = None
    projected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_event: dict[str, Any] = field(default_factory=dict)
