"""Tests for PodTypeDetector.

Covers AD-CSI-002 priority chain on both extracted directories and ZipFile
inputs, plus the indeterminate case.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from lcm_core.domain.enums.pod_type import PodType
from lcm_core.infrastructure.content_store import PodTypeDetector, PodTypeIndeterminate


class TestPodTypeDetectorFromZip:
    def test_explicit_manifest_pod_type_wins_over_topology(self, pav1_minimal_bytes: bytes) -> None:
        # Fixture has BOTH manifest.yaml (pod_type=cml_on_aws) and PAv1/topology/cml.yaml.
        # Manifest must win per priority 1.
        with zipfile.ZipFile(BytesIO(pav1_minimal_bytes)) as zf:
            pod_type, signals = PodTypeDetector.detect(zf)
        assert pod_type == PodType.CML_ON_AWS
        assert any("manifest.yaml: pod_type=cml_on_aws" in s for s in signals)

    def test_radkit_topology_resolves_without_manifest(self, pav1_radkit_no_manifest_bytes: bytes) -> None:
        with zipfile.ZipFile(BytesIO(pav1_radkit_no_manifest_bytes)) as zf:
            pod_type, signals = PodTypeDetector.detect(zf)
        assert pod_type == PodType.ROC_RADKIT
        assert any("radkit.yaml" in s and "ROC_RADKIT".lower() in s.lower() for s in signals)
        assert not any("manifest.yaml" in s for s in signals)

    def test_ambiguous_zip_raises_with_signals(self, tmp_path: Path) -> None:
        # An empty zip has no signals at all.
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("README.txt", "no PAv1 content")
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            with pytest.raises(PodTypeIndeterminate) as excinfo:
                PodTypeDetector.detect(zf)
        # Signals should include every absent path checked.
        assert excinfo.value.signals
        assert any("absent" in s for s in excinfo.value.signals)


class TestPodTypeDetectorFromDirectory:
    @pytest.mark.parametrize(
        "topology_path,expected",
        [
            ("PAv1/topology/radkit.yaml", PodType.ROC_RADKIT),
            ("PAv1/topology/proxmox.yaml", PodType.PROXMOX),
            ("PAv1/topology/vmware.yaml", PodType.VMWARE),
            ("PAv1/topology/cml.yaml", PodType.CML_ON_AWS),
            ("PAv1/topology/cml.yml", PodType.CML_ON_AWS),
            ("cml.yaml", PodType.CML_ON_AWS),
            ("cml.yml", PodType.CML_ON_AWS),
            ("radkit.yaml", PodType.ROC_RADKIT),
        ],
    )
    def test_topology_signal_resolves(self, tmp_path: Path, topology_path: str, expected: PodType) -> None:
        package = tmp_path / "pkg"
        target = package / topology_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stub: true\n", encoding="utf-8")

        pod_type, signals = PodTypeDetector.detect(package)
        assert pod_type == expected
        assert any(topology_path in s and "present" in s for s in signals)

    def test_radkit_in_pav1_beats_root_cml_legacy(self, tmp_path: Path) -> None:
        # Both PAv1/topology/radkit.yaml and root-level cml.yaml present.
        # Priority chain says radkit wins because it appears earlier.
        package = tmp_path / "pkg"
        (package / "PAv1/topology").mkdir(parents=True)
        (package / "PAv1/topology/radkit.yaml").write_text("stub: true", encoding="utf-8")
        (package / "cml.yaml").write_text("legacy: true", encoding="utf-8")

        pod_type, _ = PodTypeDetector.detect(package)
        assert pod_type == PodType.ROC_RADKIT

    def test_manifest_invalid_pod_type_raises_indeterminate(self, tmp_path: Path) -> None:
        package = tmp_path / "pkg"
        manifest_dir = package / "PAv1"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "manifest.yaml").write_text(
            "format_version: PAv1\nname: x\nversion: 1.0.0\ncontent_id: x\npod_type: not_a_real_type\n",
            encoding="utf-8",
        )
        with pytest.raises(PodTypeIndeterminate) as excinfo:
            PodTypeDetector.detect(package)
        assert any("invalid pod_type" in s for s in excinfo.value.signals)

    def test_extracted_minimal_fixture(self, pav1_minimal_bytes: bytes, extract_zip: Callable[[bytes, str], Path]) -> None:
        package = extract_zip(pav1_minimal_bytes, "extracted_minimal")
        pod_type, signals = PodTypeDetector.detect(package)
        assert pod_type == PodType.CML_ON_AWS
        # Even when detecting from a directory, signals must record the manifest.
        assert any("manifest.yaml: pod_type=cml_on_aws" in s for s in signals)
