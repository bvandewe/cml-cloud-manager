"""ExtractedContent dataclass + ContentExtractor skeleton.

Phase 0 ships the dataclass shape so downstream code (`PodDefinitionState`
field projection, repository round-trip tests) can reference it. Phase 1
will fill in :meth:`ContentExtractor.extract` with the real S3 download,
unzip, schema validation, and field population.

See CPA↔SE integration plan G-01 and G-04.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExtractedContent:
    """Typed container for the fields extracted from a PAv1 package.

    All fields are optional/empty by default so the dataclass can be created
    incrementally during extraction without raising for unfinished work.
    """

    manifest: dict[str, Any] = field(default_factory=dict)
    topology: dict[str, Any] | None = None
    devices: list[dict[str, Any]] | None = None
    lifecycle_phases: dict[str, Any] | None = None
    scenarios: dict[str, dict[str, Any]] | None = None
    grading_rules: dict[str, Any] | None = None
    reports: dict[str, Any] | None = None
    restore_rules: dict[str, Any] | None = None
    content_hash: str | None = None
    local_path: str | None = None


class ContentExtractor:
    """Skeleton extractor — full implementation lands in Phase 1.

    The Phase 0 shape exists so other layers (SE :class:`PodDefinitionState`
    field projection, repository round-trip tests) can import the
    :class:`ExtractedContent` dataclass without circular dependencies.
    """

    def extract(self, package_path: Path, target_dir: Path) -> ExtractedContent:
        """Extract a PAv1 package into ``target_dir`` and return typed fields.

        Raises:
            NotImplementedError: Phase 0 placeholder — implemented in Phase 1
                (G-01) by ``src/scenario-engine/application/commands/sync_content_command.py``.
        """
        raise NotImplementedError("ContentExtractor.extract() lands in Phase 1 (G-01). " "Phase 0 only ships the ExtractedContent dataclass shape.")
