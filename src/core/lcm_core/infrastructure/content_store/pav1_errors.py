"""Errors raised by the PAv1 content store package."""

from __future__ import annotations


class PAv1ValidationError(Exception):
    """Raised when a PAv1 payload fails JSON schema validation."""

    def __init__(self, path: str, errors: list[str]) -> None:
        self.path = path
        self.errors = list(errors)
        joined = "; ".join(self.errors) if self.errors else "validation failed"
        super().__init__(f"PAv1 validation failed for '{path}': {joined}")


class PodTypeIndeterminate(Exception):
    """Raised when :class:`PodTypeDetector` cannot determine a pod type."""

    def __init__(self, signals: list[str]) -> None:
        self.signals = list(signals)
        joined = ", ".join(self.signals) if self.signals else "no signals"
        super().__init__(f"Could not determine pod_type from package contents (signals considered: {joined})")
