"""Pytest fixtures: minimal PAv1 zip archives for content_store tests.

Fixtures are generated in-process (no binary blobs committed) so they are easy
to inspect and amend. The factory functions are also re-exported as session-
scoped fixtures via :mod:`tests.infrastructure.content_store.conftest`.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

_MINIMAL_MANIFEST = """\
format_version: PAv1
name: example-lab
version: 1.0.0
content_id: example-lab
pod_type: cml_on_aws
description: Minimal PAv1 fixture for tests.
"""

_MINIMAL_CML_TOPOLOGY = """\
lab:
  description: Minimal stub CML topology
  notes: []
  title: example-lab
nodes: []
"""

_MINIMAL_LIFECYCLE = """\
phases:
  instantiate:
    steps:
      - name: lab_resolve
        handler: scenario_engine/lab_resolve@v1
"""

_RADKIT_TOPOLOGY_NO_MANIFEST = """\
service:
  id: radkit-stub
endpoints: []
"""

# ---------------------------------------------------------------------------
# "Full" PAv1 payload — exercises every sub-tree the extractor cares about.
# Kept in-process (no .zip on disk) per Phase 1 instructions.
# ---------------------------------------------------------------------------

_FULL_MANIFEST = """\
format_version: PAv1
name: full-lab
version: 2.0.0
content_id: full-lab
pod_type: cml_on_aws
description: PAv1 fixture exercising every sub-tree.
"""

_FULL_CML_TOPOLOGY = """\
lab:
  description: Full CML topology
  title: full-lab
nodes:
  - id: r1
    type: iosv
"""

_FULL_DEVICES = """\
[
  {"hostname": "r1", "mgmt_ip": "10.0.0.1"},
  {"hostname": "sw1", "mgmt_ip": "10.0.0.2"}
]
"""

_FULL_LIFECYCLE = """\
phases:
  instantiate:
    steps:
      - name: lab_resolve
        handler: scenario_engine/lab_resolve@v1
  start:
    steps:
      - name: lab_start
        handler: scenario_engine/lab_start@v1
"""

_FULL_SCENARIO = """\
name: lab_resolve
version: v1
input_schema:
  type: object
  properties:
    worker_id:
      type: string
output_schema:
  type: object
"""

_FULL_GRADING_RULE = """\
items:
  - id: ping_r1
    weight: 50
"""

_FULL_REPORT = """\
sections:
  - id: summary
    title: Lab Summary
"""

_FULL_RESTORE_RULE = """\
snapshots:
  - id: baseline
    path: snapshots/baseline.tar
"""


def build_pav1_minimal_bytes() -> bytes:
    """A minimal valid PAv1 package with explicit ``pod_type: cml_on_aws``."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PAv1/manifest.yaml", _MINIMAL_MANIFEST)
        zf.writestr("PAv1/topology/cml.yaml", _MINIMAL_CML_TOPOLOGY)
        zf.writestr("PAv1/lifecycle.yaml", _MINIMAL_LIFECYCLE)
    return buf.getvalue()


def build_pav1_radkit_topology_no_manifest_bytes() -> bytes:
    """A package with a radkit topology but no ``manifest.yaml`` — exercises
    priority chain step 2 in :class:`PodTypeDetector`.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PAv1/topology/radkit.yaml", _RADKIT_TOPOLOGY_NO_MANIFEST)
    return buf.getvalue()


def build_pav1_full_bytes() -> bytes:
    """A PAv1 package exercising every sub-tree the extractor parses.

    Layout::

        PAv1/manifest.yaml
        PAv1/topology/cml.yaml
        PAv1/topology/devices.json
        PAv1/lifecycle.yaml             (phases envelope)
        PAv1/scenarios/lab_resolve.yaml
        PAv1/grading/default.yaml
        PAv1/reports/summary.yaml
        PAv1/restore/snapshots.yaml
        unrelated/README.txt            (non-PAv1 file, must be ignored)
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("PAv1/manifest.yaml", _FULL_MANIFEST)
        zf.writestr("PAv1/topology/cml.yaml", _FULL_CML_TOPOLOGY)
        zf.writestr("PAv1/topology/devices.json", _FULL_DEVICES)
        zf.writestr("PAv1/lifecycle.yaml", _FULL_LIFECYCLE)
        zf.writestr("PAv1/scenarios/lab_resolve.yaml", _FULL_SCENARIO)
        zf.writestr("PAv1/grading/default.yaml", _FULL_GRADING_RULE)
        zf.writestr("PAv1/reports/summary.yaml", _FULL_REPORT)
        zf.writestr("PAv1/restore/snapshots.yaml", _FULL_RESTORE_RULE)
        zf.writestr("unrelated/README.txt", "ignored by extractor")
    return buf.getvalue()


def write_fixture(target_dir: Path, name: str, payload: bytes) -> Path:
    """Write a fixture bytes payload to ``target_dir/name`` and return the path."""
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    path.write_bytes(payload)
    return path
