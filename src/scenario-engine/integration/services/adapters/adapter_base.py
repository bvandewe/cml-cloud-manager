"""AdapterBase — abstract base class for infrastructure adapters.

Phase 4 extension point. All scenario infrastructure adapters (CML, AWS,
Proxmox, VMWare) will extend this base class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AdapterBase(ABC):
    """Abstract base class for all infrastructure adapters.

    Adapters provide typed interfaces for scenario code to interact with
    infrastructure without coupling to specific implementations.

    Subclasses must implement:
        - adapter_type: Returns the adapter type name (e.g. "cml", "aws")
    """

    @property
    @abstractmethod
    def adapter_type(self) -> str:
        """Return the adapter type identifier (e.g. 'cml', 'aws', 'proxmox')."""
        ...
