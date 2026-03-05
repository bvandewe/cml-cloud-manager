"""GradingSession entity — grading workflow tracking for a LabletSession.

Tracks the grading lifecycle scoped to a parent LabletSession.
Stored in its own MongoDB collection (``grading_sessions``).

Phase 7C (ADR-021 §2): Created as Entity[str] with inline state machine.
Lifecycle driven by Grading-Engine CloudEvents received via lablet-controller.

Pattern: @dataclass extending Entity[str] with lifecycle methods
(same pattern as the former LabletRecordRun entity).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from lcm_core.domain.enums import GradingSessionStatus
from neuroglia.data import Entity


@dataclass
class GradingSession(Entity[str]):
    """Grading workflow tracking entity scoped to a LabletSession.

    Stored in its own MongoDB collection (``grading_sessions``).

    Extends Neuroglia Entity[str] so that MotorRepository can handle
    CRUD and serialization uniformly with other entities.

    Attributes — Identity:
        id: Globally unique grading session identifier (UUID).
        lablet_session_id: FK → parent LabletSession aggregate.

    Attributes — Grading Engine:
        grading_session_id: External Grading-Engine session identifier.
        grading_part_id: Grading part identifier.
        pod_id: Grading-Engine pod identifier.
        form_qualified_name: Content/form reference for grading.
        grading_rules_uri: URI to the grading rules document.
        devices: Grading device access info (list of dicts).

    Attributes — Lifecycle:
        status: Current GradingSession lifecycle status.
        started_at: When the grading started (COLLECTING or GRADING).
        completed_at: When the grading completed (SUBMITTED or FAULTED).
        error_message: Error details if FAULTED.

    Attributes — Timestamps:
        created_at: When the entity was created.
        updated_at: When the entity was last modified.
    """

    # =========================================================================
    # Identity
    # =========================================================================
    id: str = field(default_factory=lambda: str(uuid4()))
    lablet_session_id: str = ""

    # =========================================================================
    # Grading Engine
    # =========================================================================
    grading_session_id: str = ""
    grading_part_id: str | None = None
    pod_id: str | None = None
    form_qualified_name: str | None = None
    grading_rules_uri: str | None = None
    devices: list[dict[str, Any]] = field(default_factory=list)

    # =========================================================================
    # Lifecycle
    # =========================================================================
    status: GradingSessionStatus = GradingSessionStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None

    # =========================================================================
    # Timestamps
    # =========================================================================
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # =========================================================================
    # Valid transitions
    # =========================================================================

    VALID_TRANSITIONS: dict[GradingSessionStatus, set[GradingSessionStatus]] = field(
        default=None,  # type: ignore[assignment]
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Initialise the valid transitions table (not persisted)."""
        self.VALID_TRANSITIONS = {
            GradingSessionStatus.PENDING: {
                GradingSessionStatus.COLLECTING,
                GradingSessionStatus.FAULTED,
            },
            GradingSessionStatus.COLLECTING: {
                GradingSessionStatus.GRADING,
                GradingSessionStatus.FAULTED,
            },
            GradingSessionStatus.GRADING: {
                GradingSessionStatus.REVIEWING,
                GradingSessionStatus.FAULTED,
            },
            GradingSessionStatus.REVIEWING: {
                GradingSessionStatus.SUBMITTED,
                GradingSessionStatus.FAULTED,
            },
            GradingSessionStatus.SUBMITTED: set(),  # Terminal
            GradingSessionStatus.FAULTED: set(),  # Terminal
        }

    # =========================================================================
    # Computed properties
    # =========================================================================

    @property
    def is_active(self) -> bool:
        """Return True if grading is currently in progress."""
        return self.status in (
            GradingSessionStatus.COLLECTING,
            GradingSessionStatus.GRADING,
            GradingSessionStatus.REVIEWING,
        )

    @property
    def is_terminal(self) -> bool:
        """Return True if the grading session has reached a terminal state."""
        return self.status in (
            GradingSessionStatus.SUBMITTED,
            GradingSessionStatus.FAULTED,
        )

    @property
    def is_pending(self) -> bool:
        """Return True if the grading session has not started yet."""
        return self.status == GradingSessionStatus.PENDING

    @property
    def duration_seconds(self) -> float | None:
        """Compute elapsed seconds from started_at to completed_at."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    # =========================================================================
    # Lifecycle methods
    # =========================================================================

    def _validate_transition(self, new_status: GradingSessionStatus) -> None:
        """Validate that a status transition is allowed.

        Raises:
            ValueError: If the transition is not allowed.
        """
        allowed = self.VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(f"Invalid transition: {self.status.value} → {new_status.value}. Allowed: {[s.value for s in allowed]}")

    def start_collecting(self) -> None:
        """Transition to COLLECTING state (grading engine collecting responses)."""
        self._validate_transition(GradingSessionStatus.COLLECTING)
        self.status = GradingSessionStatus.COLLECTING
        self.started_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def start_grading(self) -> None:
        """Transition to GRADING state (grading engine scoring responses)."""
        self._validate_transition(GradingSessionStatus.GRADING)
        self.status = GradingSessionStatus.GRADING
        self.updated_at = datetime.now(timezone.utc)

    def start_reviewing(self) -> None:
        """Transition to REVIEWING state (scores under review / manual QA)."""
        self._validate_transition(GradingSessionStatus.REVIEWING)
        self.status = GradingSessionStatus.REVIEWING
        self.updated_at = datetime.now(timezone.utc)

    def submit(self) -> None:
        """Transition to SUBMITTED (terminal) state — scores finalised."""
        self._validate_transition(GradingSessionStatus.SUBMITTED)
        self.status = GradingSessionStatus.SUBMITTED
        self.completed_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def fault(self, error_message: str | None = None) -> None:
        """Transition to FAULTED (terminal) state from any non-terminal state.

        Args:
            error_message: Error details describing the fault.
        """
        if self.is_terminal:
            raise ValueError(f"Cannot fault a session in terminal state: {self.status.value}")
        self.status = GradingSessionStatus.FAULTED
        self.completed_at = datetime.now(timezone.utc)
        self.error_message = error_message
        self.updated_at = datetime.now(timezone.utc)

    # =========================================================================
    # Factory
    # =========================================================================

    @staticmethod
    def create(
        grading_session_id: str,
        lablet_session_id: str,
        external_grading_session_id: str | None = None,
        grading_part_id: str | None = None,
        pod_id: str | None = None,
        form_qualified_name: str | None = None,
        grading_rules_uri: str | None = None,
        devices: list[dict[str, Any]] | None = None,
    ) -> "GradingSession":
        """Create a new GradingSession in PENDING state.

        Args:
            grading_session_id: Globally unique entity identifier.
            lablet_session_id: FK → parent LabletSession.
            external_grading_session_id: External Grading-Engine session ref.
            grading_part_id: Grading part (optional).
            pod_id: Grading-Engine pod (optional).
            form_qualified_name: Content identifier (optional).
            grading_rules_uri: URI to grading rules (optional).
            devices: Grading device info (optional).

        Returns:
            A new GradingSession in PENDING state.
        """
        return GradingSession(
            id=grading_session_id,
            lablet_session_id=lablet_session_id,
            grading_session_id=external_grading_session_id or "",
            grading_part_id=grading_part_id,
            pod_id=pod_id,
            form_qualified_name=form_qualified_name,
            grading_rules_uri=grading_rules_uri,
            devices=devices or [],
            status=GradingSessionStatus.PENDING,
            started_at=None,
            completed_at=None,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
