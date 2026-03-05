"""UserSession entity — LDS session tracking for a LabletSession.

Tracks the Lab Delivery System (LDS) session scoped to a parent
LabletSession. Stored in its own MongoDB collection (``user_sessions``).

Phase 7C (ADR-021 §1): Created as Entity[str] with inline state machine.
Lifecycle driven by LDS CloudEvents received via lablet-controller.

Pattern: @dataclass extending Entity[str] with lifecycle methods
(same pattern as the former LabletRecordRun entity).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from lcm_core.domain.enums import UserSessionStatus
from neuroglia.data import Entity


@dataclass
class UserSession(Entity[str]):
    """LDS session tracking entity scoped to a LabletSession.

    Stored in its own MongoDB collection (``user_sessions``).

    Extends Neuroglia Entity[str] so that MotorRepository can handle
    CRUD and serialization uniformly with other entities.

    Attributes — Identity:
        id: Globally unique session identifier (UUID).
        lablet_session_id: FK → parent LabletSession aggregate.

    Attributes — LDS Integration:
        lds_session_id: External LDS LabSession identifier.
        lds_part_id: LDS LabSessionPart identifier.
        form_qualified_name: Content/form reference for LDS provisioning.
        login_url: JWT-signed launch URL for user to access the lab.
        devices: Provisioned device access info (list of dicts).

    Attributes — Lifecycle:
        status: Current UserSession lifecycle status.
        started_at: When the user logged in (ACTIVE).
        ended_at: When the session ended (ENDED/EXPIRED/FAULTED).
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
    # LDS Integration
    # =========================================================================
    lds_session_id: str = ""
    lds_part_id: str | None = None
    form_qualified_name: str | None = None
    login_url: str | None = None
    devices: list[dict[str, Any]] = field(default_factory=list)

    # =========================================================================
    # Lifecycle
    # =========================================================================
    status: UserSessionStatus = UserSessionStatus.PROVISIONING
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error_message: str | None = None

    # =========================================================================
    # Timestamps
    # =========================================================================
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # =========================================================================
    # Valid transitions
    # =========================================================================

    VALID_TRANSITIONS: dict[UserSessionStatus, set[UserSessionStatus]] = field(
        default=None,  # type: ignore[assignment]
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Initialise the valid transitions table (not persisted)."""
        self.VALID_TRANSITIONS = {
            UserSessionStatus.PROVISIONING: {
                UserSessionStatus.PROVISIONED,
                UserSessionStatus.FAULTED,
            },
            UserSessionStatus.PROVISIONED: {
                UserSessionStatus.ACTIVE,
                UserSessionStatus.FAULTED,
            },
            UserSessionStatus.ACTIVE: {
                UserSessionStatus.PAUSED,
                UserSessionStatus.ENDED,
                UserSessionStatus.EXPIRED,
                UserSessionStatus.FAULTED,
            },
            UserSessionStatus.PAUSED: {
                UserSessionStatus.ACTIVE,
                UserSessionStatus.ENDED,
                UserSessionStatus.EXPIRED,
                UserSessionStatus.FAULTED,
            },
            UserSessionStatus.ENDED: set(),  # Terminal
            UserSessionStatus.EXPIRED: set(),  # Terminal
            UserSessionStatus.FAULTED: set(),  # Terminal
        }

    # =========================================================================
    # Computed properties
    # =========================================================================

    @property
    def is_active(self) -> bool:
        """Return True if the session is currently active."""
        return self.status == UserSessionStatus.ACTIVE

    @property
    def is_terminal(self) -> bool:
        """Return True if the session has reached a terminal state."""
        return self.status in (
            UserSessionStatus.ENDED,
            UserSessionStatus.EXPIRED,
            UserSessionStatus.FAULTED,
        )

    @property
    def has_login_url(self) -> bool:
        """Return True if a login URL has been provisioned."""
        return self.login_url is not None

    # =========================================================================
    # Lifecycle methods
    # =========================================================================

    def _validate_transition(self, new_status: UserSessionStatus) -> None:
        """Validate that a status transition is allowed.

        Raises:
            ValueError: If the transition is not allowed.
        """
        allowed = self.VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(f"Invalid transition: {self.status.value} → {new_status.value}. Allowed: {[s.value for s in allowed]}")

    def mark_provisioned(self, login_url: str, devices: list[dict[str, Any]] | None = None) -> None:
        """Mark the LDS session as provisioned with a login URL.

        Args:
            login_url: JWT-signed launch URL for user access.
            devices: Optional list of device access info dicts.
        """
        self._validate_transition(UserSessionStatus.PROVISIONED)
        self.status = UserSessionStatus.PROVISIONED
        self.login_url = login_url
        if devices is not None:
            self.devices = devices
        self.updated_at = datetime.now(timezone.utc)

    def activate(self) -> None:
        """Transition to ACTIVE state (user logged in via LDS)."""
        self._validate_transition(UserSessionStatus.ACTIVE)
        self.status = UserSessionStatus.ACTIVE
        self.started_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def pause(self) -> None:
        """Transition to PAUSED state (session paused by proctor/system)."""
        self._validate_transition(UserSessionStatus.PAUSED)
        self.status = UserSessionStatus.PAUSED
        self.updated_at = datetime.now(timezone.utc)

    def resume(self) -> None:
        """Resume from PAUSED back to ACTIVE."""
        self._validate_transition(UserSessionStatus.ACTIVE)
        self.status = UserSessionStatus.ACTIVE
        self.updated_at = datetime.now(timezone.utc)

    def end(self) -> None:
        """Transition to ENDED (terminal) state — user finished normally."""
        self._validate_transition(UserSessionStatus.ENDED)
        self.status = UserSessionStatus.ENDED
        self.ended_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def expire(self) -> None:
        """Transition to EXPIRED (terminal) state — session timed out."""
        self._validate_transition(UserSessionStatus.EXPIRED)
        self.status = UserSessionStatus.EXPIRED
        self.ended_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def fault(self, error_message: str | None = None) -> None:
        """Transition to FAULTED (terminal) state from any non-terminal state.

        Args:
            error_message: Error details describing the fault.
        """
        if self.is_terminal:
            raise ValueError(f"Cannot fault a session in terminal state: {self.status.value}")
        self.status = UserSessionStatus.FAULTED
        self.ended_at = datetime.now(timezone.utc)
        self.error_message = error_message
        self.updated_at = datetime.now(timezone.utc)

    # =========================================================================
    # Factory
    # =========================================================================

    @staticmethod
    def create(
        user_session_id: str,
        lablet_session_id: str,
        lds_session_id: str,
        lds_part_id: str | None = None,
        form_qualified_name: str | None = None,
    ) -> "UserSession":
        """Create a new UserSession in PROVISIONING state.

        Args:
            user_session_id: Globally unique identifier.
            lablet_session_id: FK → parent LabletSession.
            lds_session_id: External LDS session reference.
            lds_part_id: LDS content part (optional).
            form_qualified_name: Content identifier (optional).

        Returns:
            A new UserSession in PROVISIONING state.
        """
        return UserSession(
            id=user_session_id,
            lablet_session_id=lablet_session_id,
            lds_session_id=lds_session_id,
            lds_part_id=lds_part_id,
            form_qualified_name=form_qualified_name,
            login_url=None,
            devices=[],
            status=UserSessionStatus.PROVISIONING,
            started_at=None,
            ended_at=None,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
