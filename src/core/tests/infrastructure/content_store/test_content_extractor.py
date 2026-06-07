"""Tests for :class:`lcm_core.infrastructure.content_store.ContentExtractor`."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from lcm_core.domain.enums.pod_type import PodType
from lcm_core.infrastructure.content_store import ContentExtractor, ExtractedContent, PAv1ValidationError


@pytest.fixture
def extractor() -> ContentExtractor:
    return ContentExtractor()


def _write(tmp_path: Path, payload: bytes, name: str = "package.zip") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


class TestMinimalRoundTrip:
    @pytest.mark.asyncio
    async def test_minimal_payload_populates_manifest_only(
        self,
        extractor: ContentExtractor,
        pav1_minimal_bytes: bytes,
        tmp_path: Path,
    ) -> None:
        pkg = _write(tmp_path, pav1_minimal_bytes)
        target = tmp_path / "extracted"

        content: ExtractedContent = await extractor.extract(pkg, target)

        assert content.manifest["name"] == "example-lab"
        assert content.detected_pod_type == PodType.CML_ON_AWS
        # CML topology + lifecycle are both shipped in the minimal fixture.
        assert content.topology is not None
        assert "cml" in content.topology
        assert content.lifecycle_phases is not None
        # Optional sub-trees not in the fixture should stay None.
        assert content.devices is None
        assert content.scenarios is None
        assert content.grading_rules is None
        assert content.reports is None
        assert content.restore_rules is None
        # PAv1/ tree was extracted to disk.
        assert (target / "PAv1" / "manifest.yaml").is_file()


class TestFullRoundTrip:
    @pytest.mark.asyncio
    async def test_full_payload_populates_every_field(
        self,
        extractor: ContentExtractor,
        pav1_full_bytes: bytes,
        tmp_path: Path,
    ) -> None:
        pkg = _write(tmp_path, pav1_full_bytes)
        target = tmp_path / "extracted"

        content = await extractor.extract(pkg, target)

        assert content.manifest["name"] == "full-lab"
        assert content.detected_pod_type == PodType.CML_ON_AWS
        assert content.topology and "cml" in content.topology
        assert content.devices == [
            {"hostname": "r1", "mgmt_ip": "10.0.0.1"},
            {"hostname": "sw1", "mgmt_ip": "10.0.0.2"},
        ]
        # lifecycle.yaml uses the {"phases": {...}} envelope — extractor unwraps it.
        assert content.lifecycle_phases is not None
        assert set(content.lifecycle_phases.keys()) == {"instantiate", "start"}
        assert content.scenarios is not None
        assert "lab_resolve" in content.scenarios
        assert content.grading_rules == {"default": {"items": [{"id": "ping_r1", "weight": 50}]}}
        assert content.reports == {"summary": {"sections": [{"id": "summary", "title": "Lab Summary"}]}}
        assert content.restore_rules == {"snapshots": {"snapshots": [{"id": "baseline", "path": "snapshots/baseline.tar"}]}}
        # local_path round-trips.
        assert content.local_path == str(target)
        # Non-PAv1 files in the zip are not extracted.
        assert not (target / "unrelated").exists()


class TestFailures:
    @pytest.mark.asyncio
    async def test_missing_manifest_raises(
        self,
        extractor: ContentExtractor,
        pav1_radkit_no_manifest_bytes: bytes,
        tmp_path: Path,
    ) -> None:
        pkg = _write(tmp_path, pav1_radkit_no_manifest_bytes)
        with pytest.raises(PAv1ValidationError) as excinfo:
            await extractor.extract(pkg, tmp_path / "extracted")
        # Detected pod_type is surfaced as a hint via the error payload (AD-CSI-012).
        assert any("roc_radkit" in err.lower() for err in excinfo.value.errors)

    @pytest.mark.asyncio
    async def test_corrupt_yaml_in_topology_raises(self, extractor: ContentExtractor, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("PAv1/manifest.yaml", "format_version: PAv1\nname: x\nversion: 1\ncontent_id: x\n")
            zf.writestr("PAv1/topology/cml.yaml", "not: [valid yaml: : :\n  - broken")
        with pytest.raises(PAv1ValidationError) as excinfo:
            await extractor.extract(_write(tmp_path, buf.getvalue()), tmp_path / "out")
        assert "PAv1/topology/cml.yaml" in excinfo.value.path

    @pytest.mark.asyncio
    async def test_manifest_not_object_raises(self, extractor: ContentExtractor, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("PAv1/manifest.yaml", "- not\n- an\n- object\n")
        with pytest.raises(PAv1ValidationError) as excinfo:
            await extractor.extract(_write(tmp_path, buf.getvalue()), tmp_path / "out")
        assert "expected an object" in "; ".join(excinfo.value.errors)
