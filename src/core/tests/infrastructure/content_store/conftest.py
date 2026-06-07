"""Shared fixtures for content_store tests."""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest

from tests.infrastructure.content_store.fixtures import (
    build_pav1_minimal_bytes,
    build_pav1_radkit_topology_no_manifest_bytes,
    write_fixture,
)


@pytest.fixture
def pav1_minimal_bytes() -> bytes:
    return build_pav1_minimal_bytes()


@pytest.fixture
def pav1_radkit_no_manifest_bytes() -> bytes:
    return build_pav1_radkit_topology_no_manifest_bytes()


@pytest.fixture
def pav1_minimal_zip(tmp_path: Path) -> Path:
    return write_fixture(tmp_path / "pav1_fixtures", "pav1_minimal.zip", build_pav1_minimal_bytes())


@pytest.fixture
def pav1_radkit_no_manifest_zip(tmp_path: Path) -> Path:
    return write_fixture(
        tmp_path / "pav1_fixtures",
        "pav1_radkit_topology_no_manifest.zip",
        build_pav1_radkit_topology_no_manifest_bytes(),
    )


@pytest.fixture
def extract_zip(tmp_path: Path) -> Callable[[bytes, str], Path]:
    """Return a helper that extracts a zip payload into ``tmp_path/<name>``."""

    def _extract(payload: bytes, subdir: str) -> Path:
        target = tmp_path / subdir
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(BytesIO(payload)) as zf:
            zf.extractall(target)
        return target

    return _extract
