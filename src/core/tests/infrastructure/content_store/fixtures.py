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


def write_fixture(target_dir: Path, name: str, payload: bytes) -> Path:
    """Write a fixture bytes payload to ``target_dir/name`` and return the path."""
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    path.write_bytes(payload)
    return path
