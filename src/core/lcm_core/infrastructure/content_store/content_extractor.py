"""``ExtractedContent`` dataclass + ``ContentExtractor`` (Phase 1, G-01).

Extracts a PAv1 package (zip) into a target directory and parses the full
``PAv1/`` sub-tree into typed fields. JSON-Schema validation lives in
:class:`lcm_core.infrastructure.content_store.pav1_validator.PAv1Validator`;
the extractor is intentionally schema-agnostic — the caller (SyncContentCommand)
decides which sub-trees to validate.

See CPA↔SE integration plan §3 G-01 and §5 (PAv1 spec).
"""

from __future__ import annotations

import asyncio
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from lcm_core.domain.enums.pod_type import PodType
from lcm_core.infrastructure.content_store.pav1_errors import PAv1ValidationError, PodTypeIndeterminate
from lcm_core.infrastructure.content_store.pod_type_detector import PodTypeDetector

logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    """Typed container for the fields extracted from a PAv1 package.

    All fields are optional/empty by default so the dataclass can be created
    incrementally during extraction without raising for unfinished work.

    AD-CSI-012 (Phase 1): ``detected_pod_type`` is ``PodType | None``; only
    the caller (``SyncContentCommand``) decides whether ``None`` is fatal.
    """

    manifest: dict[str, Any] = field(default_factory=dict)
    topology: dict[str, dict[str, Any]] | None = None
    devices: list[dict[str, Any]] | None = None
    lifecycle_phases: dict[str, Any] | None = None
    scenarios: dict[str, dict[str, Any]] | None = None
    grading_rules: dict[str, dict[str, Any]] | None = None
    reports: dict[str, dict[str, Any]] | None = None
    restore_rules: dict[str, dict[str, Any]] | None = None
    content_hash: str | None = None
    local_path: str | None = None
    detected_pod_type: PodType | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MANIFEST_MEMBER = "PAv1/manifest.yaml"
_LIFECYCLE_MEMBER = "PAv1/lifecycle.yaml"
_TOPOLOGY_PREFIX = "PAv1/topology/"
_SCENARIOS_PREFIX = "PAv1/scenarios/"
_GRADING_PREFIX = "PAv1/grading/"
_REPORTS_PREFIX = "PAv1/reports/"
_RESTORE_PREFIX = "PAv1/restore/"


def _stem(member: str) -> str:
    name = member.rsplit("/", 1)[-1]
    for suffix in (".yaml", ".yml", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _load_yaml(path: str, raw: bytes) -> Any:
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PAv1ValidationError(path, [f"<root>: invalid YAML: {exc}"]) from exc


def _load_json(path: str, raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PAv1ValidationError(path, [f"<root>: invalid JSON: {exc}"]) from exc


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class ContentExtractor:
    """Extract a PAv1 zip into a directory and parse the typed sub-trees.

    Usage::

        extractor = ContentExtractor()
        content = await extractor.extract(package_path, target_dir)

    The returned :class:`ExtractedContent` carries every parsed file plus
    the ``detected_pod_type`` reported by :class:`PodTypeDetector`. Missing
    optional sub-trees come back as ``None`` (see field defaults). A missing
    ``PAv1/manifest.yaml`` raises :class:`PAv1ValidationError` so the caller
    can mark the PodDefinition as ``FAILED`` immediately.
    """

    async def extract(self, package_path: Path, target_dir: Path) -> ExtractedContent:
        """Extract ``package_path`` into ``target_dir`` and parse PAv1 fields.

        Args:
            package_path: Local path to the downloaded zip package.
            target_dir: Directory to extract the zip into (will be created if
                missing). The extractor mirrors the in-zip layout, so the
                manifest ends up at ``target_dir/PAv1/manifest.yaml``.

        Returns:
            A populated :class:`ExtractedContent`.

        Raises:
            PAv1ValidationError: If ``manifest.yaml`` is missing or any
                discovered YAML/JSON sub-tree fails to parse.
        """
        return await asyncio.to_thread(self._extract_sync, package_path, target_dir)

    # ------------------------------------------------------------------
    # Sync core (offloaded via asyncio.to_thread above)
    # ------------------------------------------------------------------

    def _extract_sync(self, package_path: Path, target_dir: Path) -> ExtractedContent:
        target_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(package_path, "r") as zf:
            detected_pod_type = self._safe_detect(zf)
            members = zf.namelist()
            # Extract the PAv1/ tree (only) into the target directory so the
            # caller can keep the original zip without exploding non-PAv1 files.
            for member in members:
                if member.startswith("PAv1/"):
                    zf.extract(member, str(target_dir))

            manifest = self._load_manifest(zf, members, detected_pod_type)
            topology = self._load_topology(zf, members)
            devices = self._load_devices(zf, members)
            lifecycle_phases = self._load_lifecycle(zf, members)
            scenarios = self._load_mapping_dir(zf, members, _SCENARIOS_PREFIX)
            grading_rules = self._load_mapping_dir(zf, members, _GRADING_PREFIX)
            reports = self._load_mapping_dir(zf, members, _REPORTS_PREFIX)
            restore_rules = self._load_mapping_dir(zf, members, _RESTORE_PREFIX)

        return ExtractedContent(
            manifest=manifest,
            topology=topology,
            devices=devices,
            lifecycle_phases=lifecycle_phases,
            scenarios=scenarios,
            grading_rules=grading_rules,
            reports=reports,
            restore_rules=restore_rules,
            local_path=str(target_dir),
            detected_pod_type=detected_pod_type,
        )

    # ------------------------------------------------------------------
    # Per-tree loaders
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_detect(zf: zipfile.ZipFile) -> PodType | None:
        try:
            pod_type, signals = PodTypeDetector.detect(zf)
            logger.debug("PodTypeDetector: %s (signals=%s)", pod_type, signals)
            return pod_type
        except PodTypeIndeterminate as exc:
            logger.info("PodTypeDetector indeterminate: %s", exc)
            return None

    def _load_manifest(
        self,
        zf: zipfile.ZipFile,
        members: list[str],
        detected_pod_type: PodType | None,
    ) -> dict[str, Any]:
        if _MANIFEST_MEMBER not in members:
            # Surface the detected pod_type via the error payload so the caller
            # can decide whether to keep the package (e.g. as a legacy import).
            hint = f"detected_pod_type={detected_pod_type.value}" if detected_pod_type else "detected_pod_type=unknown"
            raise PAv1ValidationError(
                _MANIFEST_MEMBER,
                [f"<root>: required manifest.yaml is missing ({hint})"],
            )
        raw = zf.read(_MANIFEST_MEMBER)
        data = _load_yaml(_MANIFEST_MEMBER, raw)
        if not isinstance(data, dict):
            raise PAv1ValidationError(
                _MANIFEST_MEMBER,
                [f"<root>: expected an object, got {type(data).__name__}"],
            )
        return data

    def _load_topology(self, zf: zipfile.ZipFile, members: list[str]) -> dict[str, dict[str, Any]] | None:
        topology: dict[str, dict[str, Any]] = {}
        for member in members:
            if not member.startswith(_TOPOLOGY_PREFIX):
                continue
            if not (member.endswith(".yaml") or member.endswith(".yml")):
                continue
            data = _load_yaml(member, zf.read(member))
            if data is None:
                continue
            if not isinstance(data, dict):
                raise PAv1ValidationError(
                    member,
                    [f"<root>: expected an object, got {type(data).__name__}"],
                )
            topology[_stem(member)] = data
        return topology or None

    def _load_devices(self, zf: zipfile.ZipFile, members: list[str]) -> list[dict[str, Any]] | None:
        # Preferred path lives under PAv1/topology/devices.json; legacy fallback
        # at PAv1/devices.json kept for older fixtures (and pre-PAv1 packages).
        for candidate in ("PAv1/topology/devices.json", "PAv1/devices.json"):
            if candidate in members:
                data = _load_json(candidate, zf.read(candidate))
                if not isinstance(data, list):
                    raise PAv1ValidationError(
                        candidate,
                        [f"<root>: expected an array, got {type(data).__name__}"],
                    )
                return data
        return None

    def _load_lifecycle(self, zf: zipfile.ZipFile, members: list[str]) -> dict[str, Any] | None:
        if _LIFECYCLE_MEMBER not in members:
            return None
        data = _load_yaml(_LIFECYCLE_MEMBER, zf.read(_LIFECYCLE_MEMBER))
        if data is None:
            return None
        if not isinstance(data, dict):
            raise PAv1ValidationError(
                _LIFECYCLE_MEMBER,
                [f"<root>: expected an object, got {type(data).__name__}"],
            )
        # If the document uses the canonical {"phases": {...}} envelope, return
        # the inner phases map directly to match AD-CSI-004's lifecycle_phases
        # shape; otherwise return the document as-is.
        phases = data.get("phases")
        if isinstance(phases, dict):
            return phases
        return data

    def _load_mapping_dir(
        self,
        zf: zipfile.ZipFile,
        members: list[str],
        prefix: str,
    ) -> dict[str, dict[str, Any]] | None:
        out: dict[str, dict[str, Any]] = {}
        for member in members:
            if not member.startswith(prefix):
                continue
            if not (member.endswith(".yaml") or member.endswith(".yml")):
                continue
            data = _load_yaml(member, zf.read(member))
            if data is None:
                continue
            if not isinstance(data, dict):
                raise PAv1ValidationError(
                    member,
                    [f"<root>: expected an object, got {type(data).__name__}"],
                )
            out[_stem(member)] = data
        return out or None
