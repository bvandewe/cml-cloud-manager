import os
from pathlib import Path

import pytest

# Patterns representing the original starter branding variants.
ORIGINAL_VARIANTS = [
    "lablet-cloud-manager",
    "lablet_cloud_manager",
    "Cml Cloud Manager",
    "LabletCloudManager",
    "CML_CLOUD_MANAGER",
]

# File extensions to scan. Adjust as needed.
SCAN_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sh",
    ".html",
    ".js",
    ".css",
}

# Paths (relative to repo root) to ignore (examples, rename script, historical docs).
IGNORE_PATH_PARTS = {
    "scripts/rename_project.py",  # contains examples of old name by design
    "CHANGELOG.md",  # may reference historical name
    "LICENSE",  # legal name may remain
}

# Environment variable to skip this test (e.g., before running rename).
SKIP_ENV = "SKIP_RENAME_INTEGRITY"
FORCE_ENV = "FORCE_RENAME_INTEGRITY"


def iter_candidate_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        # Skip ignored paths
        if any(rel == p or rel.endswith(p) for p in IGNORE_PATH_PARTS):
            continue
        # Skip __pycache__ and compiled artifacts
        if ".__" in rel or "pycache" in rel:
            continue
        if path.suffix in SCAN_EXTENSIONS:
            yield path


def find_occurrences(root: Path):
    offending = {}
    for file_path in iter_candidate_files(root):
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # pragma: no cover - unreadable file
            continue
        hits = []
        for variant in ORIGINAL_VARIANTS:
            # Simple substring search; could be word-boundary constrained if needed
            if variant in text:
                hits.append(variant)
        if hits:
            offending[file_path] = sorted(set(hits))
    return offending


@pytest.mark.skipif(
    os.getenv(SKIP_ENV) == "1",
    reason="Rename integrity check skipped by environment flag.",
)
def test_no_starter_branding_left():
    """Ensure no original starter branding variants remain after rename.

    To run after executing scripts/rename_project.py.
    Set SKIP_RENAME_INTEGRITY=1 to skip when still in starter state.
    """
    # parents[2] to go from tests/cases/test_rename_integrity.py -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    # Walk up to find the git root (the actual project root)
    git_root = repo_root
    while git_root != git_root.parent:
        if (git_root / ".git").exists():
            break
        git_root = git_root.parent
    # Auto-skip if still in original repo name unless forced
    if git_root.name == "lablet-cloud-manager" and os.getenv(FORCE_ENV) != "1":
        pytest.skip("Repository still named lablet-cloud-manager; rename not yet applied.")
    offending = find_occurrences(repo_root)
    if offending:
        formatted = "\n".join(f"{path}: {variants}" for path, variants in offending.items())
        pytest.fail(f"Rename integrity failed; leftover branding variants found:\n{formatted}")


def test_variant_list_is_unique_and_non_empty():
    # Guardrail: keep list meaningful
    assert ORIGINAL_VARIANTS, "Expected at least one variant pattern."
    assert len(ORIGINAL_VARIANTS) == len(set(ORIGINAL_VARIANTS)), "Duplicate entries in ORIGINAL_VARIANTS."
    assert len(ORIGINAL_VARIANTS) == len(set(ORIGINAL_VARIANTS)), "Duplicate entries in ORIGINAL_VARIANTS."
