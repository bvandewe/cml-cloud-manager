"""Repository interface for PendingLabImport entities.

ADR-017: PendingLabImport records are created by the control-plane-api
when a lab import is requested. The lablet-controller watches for pending
imports and reconciles them by calling the CML API.

Extends the base CRUD contract (inherited from MotorRepository) with
import-specific queries for worker-scoped lookups and status filtering.

Standard CRUD operations (add_async, update_async, remove_async,
get_async/contains_async) are provided by MotorRepository base class
and should NOT be redeclared here — except for the abstract interface.
"""

from abc import ABC, abstractmethod

from domain.entities.pending_lab_import import PendingLabImport


class PendingLabImportRepository(ABC):
    """Repository for managing PendingLabImport persistence.

    Provides lookups by worker_id and status for the reconciliation
    pattern where lablet-controller polls for pending imports.

    Standard CRUD (add_async, update_async, remove_async, get_async)
    is inherited from MotorRepository — only custom queries are declared here.
    """

    @abstractmethod
    async def get_by_id_async(self, import_id: str) -> PendingLabImport | None:
        """Get a pending lab import by its ID."""

    @abstractmethod
    async def get_by_worker_id_async(self, worker_id: str) -> list[PendingLabImport]:
        """Get all pending lab imports for a specific worker."""

    @abstractmethod
    async def get_pending_by_worker_id_async(self, worker_id: str) -> list[PendingLabImport]:
        """Get only pending (not yet started) imports for a worker."""

    @abstractmethod
    async def get_all_pending_async(self) -> list[PendingLabImport]:
        """Get all pending imports across all workers."""

    @abstractmethod
    async def add_async(self, pending_import: PendingLabImport) -> None:
        """Add a new pending lab import."""

    @abstractmethod
    async def update_async(self, pending_import: PendingLabImport) -> None:
        """Update an existing pending lab import."""

    @abstractmethod
    async def remove_async(self, pending_import: PendingLabImport) -> None:
        """Remove a pending lab import."""

    @abstractmethod
    async def remove_by_id_async(self, import_id: str) -> None:
        """Remove a pending lab import by ID."""
