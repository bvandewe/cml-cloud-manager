"""Deterministic pod-type detection for PAv1 (and legacy) content packages.

See :doc:`docs/architecture/content-format/PAv1.md` §3 and AD-CSI-002 for the
priority chain. The detector operates on either an extracted directory
(:class:`pathlib.Path` pointing at the package root) or an open
:class:`zipfile.ZipFile`.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from zipfile import ZipFile

import yaml

from lcm_core.domain.enums.pod_type import PodType
from lcm_core.infrastructure.content_store.pav1_errors import PodTypeIndeterminate

logger = logging.getLogger(__name__)

PackageRef = Path | ZipFile

_MANIFEST_PATH = "PAv1/manifest.yaml"

# Topology signals — (path inside package, resulting PodType).
# Order matters: explicit manifest already won by the time we reach this list.
_TOPOLOGY_PRIORITY: list[tuple[str, PodType]] = [
    ("PAv1/topology/radkit.yaml", PodType.ROC_RADKIT),
    ("PAv1/topology/proxmox.yaml", PodType.PROXMOX),
    ("PAv1/topology/vmware.yaml", PodType.VMWARE),
    ("PAv1/topology/cml.yaml", PodType.CML_ON_AWS),
    ("PAv1/topology/cml.yml", PodType.CML_ON_AWS),
    # Legacy root-level fallbacks (kept for migration window).
    ("cml.yaml", PodType.CML_ON_AWS),
    ("cml.yml", PodType.CML_ON_AWS),
    ("radkit.yaml", PodType.ROC_RADKIT),
]


class PodTypeDetector:
    """Deterministic pod-type discovery.

    Use :meth:`detect` with either an extracted directory or a :class:`ZipFile`.
    Returns ``(pod_type, signals_considered)`` where ``signals_considered`` is
    an ordered list of every signal name examined (matched or not) for audit
    logging. Raises :class:`PodTypeIndeterminate` if no signal matches.
    """

    @classmethod
    def detect(cls, package: PackageRef) -> tuple[PodType, list[str]]:
        signals: list[str] = []

        # Priority 1 — explicit manifest declaration.
        manifest_data = cls._read_yaml(package, _MANIFEST_PATH)
        if manifest_data is not None:
            signals.append(f"{_MANIFEST_PATH}: present")
            declared = manifest_data.get("pod_type") if isinstance(manifest_data, dict) else None
            if declared:
                signals.append(f"{_MANIFEST_PATH}: pod_type={declared}")
                try:
                    return PodType(declared), signals
                except ValueError as exc:
                    raise PodTypeIndeterminate(signals + [f"invalid pod_type '{declared}'"]) from exc

        # Priorities 2..n — topology / legacy signals.
        for path, pod_type in _TOPOLOGY_PRIORITY:
            if cls._exists(package, path):
                signals.append(f"{path}: present -> {pod_type.value}")
                return pod_type, signals
            signals.append(f"{path}: absent")

        raise PodTypeIndeterminate(signals)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _exists(package: PackageRef, path: str) -> bool:
        if isinstance(package, ZipFile):
            try:
                package.getinfo(path)
                return True
            except KeyError:
                return False
        return (package / path).is_file()

    @classmethod
    def _read_yaml(cls, package: PackageRef, path: str) -> object | None:
        if not cls._exists(package, path):
            return None
        try:
            if isinstance(package, ZipFile):
                with package.open(path) as fp:
                    raw = fp.read()
            else:
                raw = (package / path).read_bytes()
            return yaml.safe_load(io.BytesIO(raw))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("PodTypeDetector: failed to parse %s (%s); ignoring", path, exc)
            return None
