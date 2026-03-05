"""PendingLabImport entity — queued lab import awaiting reconciliation.

ADR-017: Lab import operations use the reconciliation pattern:
1. Control-plane-api stores YAML in PendingLabImport (MongoDB)
2. Lablet-controller watches etcd, sees pending import
3. Lablet-controller imports the lab via CML API
4. Lablet-controller reports success/failure via internal API

Uses Neuroglia Entity[str] base class so that MotorRepository handles
serialization/deserialization transparently (same pattern as LabletLabBinding).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from neuroglia.data import Entity


class PendingLabImportStatus:
    """Status constants for PendingLabImport lifecycle.

    Transitions:
        pending → importing → completed
        pending → importing → failed
        pending → failed (validation error before import)
    """

    PENDING = "pending"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"

    VALID_TRANSITIONS: dict[str, list[str]] = {
        "pending": ["importing", "failed"],
        "importing": ["completed", "failed"],
    }


@dataclass
class PendingLabImport(Entity[str]):
    """Entity representing a queued lab import awaiting reconciliation.

    Stored in its own MongoDB collection (``pending_lab_imports``).

    Extends Neuroglia Entity[str] so that MotorRepository can handle
    CRUD and serialization uniformly with other entities.

    Attributes:
        id: Globally unique import identifier (UUID).
        worker_id: Target CML worker to import the lab to.
        yaml_content: Lab topology in CML2 YAML format.
        title: Optional title override for the imported lab.
        requested_by: Username of the requester (from auth context).
        requested_at: When the import was requested.
        status: Current import status (pending, importing, completed, failed).
        error_message: Error details if import failed.
        created_lab_id: CML lab ID assigned after successful import.
        completed_at: When the import completed (success or failure).
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    worker_id: str = ""
    yaml_content: str = ""
    title: str | None = None
    requested_by: str | None = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = PendingLabImportStatus.PENDING
    error_message: str | None = None
    created_lab_id: str | None = None
    completed_at: datetime | None = None

    # =========================================================================
    # Computed properties
    # =========================================================================

    @property
    def is_pending(self) -> bool:
        """Return True if the import is still pending."""
        return self.status == PendingLabImportStatus.PENDING

    @property
    def is_importing(self) -> bool:
        """Return True if the import is currently in progress."""
        return self.status == PendingLabImportStatus.IMPORTING

    @property
    def is_completed(self) -> bool:
        """Return True if the import completed successfully."""
        return self.status == PendingLabImportStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        """Return True if the import failed."""
        return self.status == PendingLabImportStatus.FAILED

    @property
    def is_terminal(self) -> bool:
        """Return True if the import is in a terminal state (completed or failed)."""
        return self.status in (PendingLabImportStatus.COMPLETED, PendingLabImportStatus.FAILED)

    # =========================================================================
    # Lifecycle methods
    # =========================================================================

    def mark_importing(self) -> None:
        """Mark this import as in progress (lablet-controller picked it up)."""
        self._validate_transition(PendingLabImportStatus.IMPORTING)
        self.status = PendingLabImportStatus.IMPORTING

    def mark_completed(self, lab_id: str, completed_at: datetime | None = None) -> None:
        """Mark this import as successfully completed.

        Args:
            lab_id: The CML lab ID created by the import.
            completed_at: When the import completed (defaults to now).
        """
        self._validate_transition(PendingLabImportStatus.COMPLETED)
        self.status = PendingLabImportStatus.COMPLETED
        self.created_lab_id = lab_id
        self.completed_at = completed_at or datetime.now(timezone.utc)

    def mark_failed(self, error_message: str, failed_at: datetime | None = None) -> None:
        """Mark this import as failed.

        Args:
            error_message: Description of what went wrong.
            failed_at: When the failure occurred (defaults to now).
        """
        self._validate_transition(PendingLabImportStatus.FAILED)
        self.status = PendingLabImportStatus.FAILED
        self.error_message = error_message
        self.completed_at = failed_at or datetime.now(timezone.utc)

    def _validate_transition(self, target_status: str) -> None:
        """Validate that the status transition is allowed.

        Args:
            target_status: The desired new status.

        Raises:
            ValueError: If the transition is not allowed.
        """
        allowed = PendingLabImportStatus.VALID_TRANSITIONS.get(self.status, [])
        if target_status not in allowed:
            raise ValueError(f"Invalid status transition: {self.status} → {target_status}. Allowed transitions from '{self.status}': {allowed}")

    # =========================================================================
    # Factory
    # =========================================================================

    @staticmethod
    def create(
        worker_id: str,
        yaml_content: str,
        title: str | None = None,
        requested_by: str | None = None,
    ) -> "PendingLabImport":
        """Create a new pending lab import.

        Args:
            worker_id: Target CML worker ID.
            yaml_content: Lab topology YAML content.
            title: Optional title override for the lab.
            requested_by: Username of the requester.

        Returns:
            A new PendingLabImport in 'pending' status.
        """
        return PendingLabImport(
            id=str(uuid4()),
            worker_id=worker_id,
            yaml_content=yaml_content,
            title=title,
            requested_by=requested_by,
            requested_at=datetime.now(timezone.utc),
            status=PendingLabImportStatus.PENDING,
            error_message=None,
            created_lab_id=None,
            completed_at=None,
        )
