#!/usr/bin/env python3
"""
Project Renamer Utility
=======================

Purpose:
    Rename the project from "Lablet Cloud Manager" (CCM) to "Lablet Cloud Manager" (LCM)
    by safely replacing all occurrences of the original project name variants.

Features:
    - Replaces all common variants: CCM/LCM, ccm/lcm, LabletCloudManager/LabletCloudManager, etc.
    - Handles special cases like lcm-core, lcm_core, /lcm/ (etcd prefix), etc.
    - Dry-run mode shows planned changes without modifying files.
    - Skips binary/large/unrelated paths (venv, .git, node_modules, __pycache__, etc.).
    - Prints a concise summary of changed files.

Usage Examples:
    Dry run (recommended first):
        python scripts/rename_project.py --dry-run

    Execute replacements:
        python scripts/rename_project.py

    Restrict to src + docs only:
        python scripts/rename_project.py --include src docs

Caution:
    - Commit or stash your work before running.
    - Review dry-run output carefully.
    - Renaming Keycloak realm/client requires external Keycloak adjustments.

Exit Codes:
    0 success, 1 usage error, 2 runtime error.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

# Replacement mapping: OLD -> NEW
# Order matters! More specific patterns should come first to avoid partial replacements.
REPLACEMENTS: list[tuple[str, str]] = [
    # Full project names (most specific first)
    ("Lablet Cloud Manager", "Lablet Cloud Manager"),
    ("lablet-cloud-manager", "lablet-cloud-manager"),
    ("lablet_cloud_manager", "lablet_cloud_manager"),
    ("LabletCloudManager", "LabletCloudManager"),
    # Core package naming
    ("lcm-core", "lcm-core"),
    ("lcm_core", "lcm_core"),
    ("LcmCore", "LcmCore"),
    # etcd key prefix (careful - very specific)
    ('key_prefix="/lcm"', 'key_prefix="/lcm"'),
    ('key_prefix: str = "/lcm"', 'key_prefix: str = "/lcm"'),
    ("/lcm-test", "/lcm-test"),  # test prefixes
    ("/lcm/", "/lcm/"),  # key paths in comments/docs
    # Abbreviations in various contexts
    ("LCM_", "LCM_"),  # environment variables
    ("LCM-", "LCM-"),  # kebab-case identifiers
    ("lcm-", "lcm-"),  # kebab-case identifiers
    ("lcm_", "lcm_"),  # snake_case identifiers
    # Standalone abbreviations (be careful - only in specific contexts)
    # These are commented out as they're too aggressive and could match "CML" incorrectly
    # ("CCM", "LCM"),  # uppercase abbreviation
    # ("ccm", "lcm"),  # lowercase abbreviation
]

# Files/directories to ignore when traversing
DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "static",
    "logs",
    ".pytest_cache",
    ".parcel-cache",
    "site",  # mkdocs build output
    "htmlcov",  # coverage reports
}

# Extensions to skip (binary / generated)
SKIP_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".lock", ".woff", ".woff2", ".map", ".db", ".sqlite"}
SKIP_FILE_PATTERNS = {".pyc", ".pyo"}

# Files to skip entirely (by name)
SKIP_FILES = {"poetry.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rename project from 'Lablet Cloud Manager' (CCM) to 'Lablet Cloud Manager' (LCM).")
    p.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    p.add_argument("--include", nargs="*", help="Limit replacements to these top-level paths")
    p.add_argument("--exclude", nargs="*", help="Additional paths to exclude")
    p.add_argument("--verbose", "-v", action="store_true", help="Show detailed replacement info")
    return p.parse_args()


def should_skip(path: Path) -> bool:
    if any(part in DEFAULT_EXCLUDES for part in path.parts):
        return True
    if path.is_dir():
        return False
    if path.name in SKIP_FILES:
        return True
    if path.suffix.lower() in SKIP_EXTS:
        return True
    if any(str(path).endswith(pattern) for pattern in SKIP_FILE_PATTERNS):
        return True
    # skip large files > 2MB
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return True
    except OSError:
        return True
    return False


def iter_candidate_files(root: Path, includes: list[str] | None) -> Iterable[Path]:
    if includes:
        for inc in includes:
            base = root / inc
            if not base.exists():
                continue
            if base.is_file():
                yield base
            else:
                for p in base.rglob("*"):
                    if p.is_file() and not should_skip(p):
                        yield p
        return
    for p in root.rglob("*"):
        if p.is_file() and not should_skip(p):
            yield p


def replace_in_file(path: Path, replacements: list[tuple[str, str]], verbose: bool = False) -> tuple[bool, int, list[str]]:
    """Replace all occurrences in a file. Returns (modified, count, details)."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False, 0, []
    original = text
    total_subs = 0
    details = []
    for old, new in replacements:
        if old in text:
            count = text.count(old)
            text = text.replace(old, new)
            total_subs += count
            if verbose:
                details.append(f"    '{old}' -> '{new}' ({count}x)")
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True, total_subs, details
    return False, 0, []


def main() -> int:
    args = parse_args()

    # Use the predefined replacements
    replacements = REPLACEMENTS

    excludes = set(DEFAULT_EXCLUDES)
    if args.exclude:
        excludes.update(args.exclude)

    root = Path.cwd()
    print("=" * 60)
    print("  Lablet Cloud Manager -> Lablet Cloud Manager Rename")
    print("=" * 60)
    print(f"\nRoot: {root}")
    if args.dry_run:
        print("Mode: DRY-RUN (no files will be modified)")
    else:
        print("Mode: EXECUTE (files will be modified)")
    print(f"\nReplacements ({len(replacements)} patterns):")
    for old, new in replacements:
        print(f"  '{old}' -> '{new}')")

    changed_files: list[tuple[Path, int, list[str]]] = []
    total_subs = 0
    scanned = 0

    for file_path in iter_candidate_files(root, args.include):
        if any(part in excludes for part in file_path.parts):
            continue
        scanned += 1
        try:
            with file_path.open("r", encoding="utf-8") as fh:
                content = fh.read()
        except UnicodeDecodeError:
            continue

        new_content = content
        file_subs = 0
        details = []

        for old, new in replacements:
            if old in new_content:
                count = new_content.count(old)
                new_content = new_content.replace(old, new)
                file_subs += count
                if args.verbose:
                    details.append(f"    '{old}' -> '{new}' ({count}x)")

        if file_subs > 0:
            if not args.dry_run:
                file_path.write_text(new_content, encoding="utf-8")
            changed_files.append((file_path, file_subs, details))
            total_subs += file_subs

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print("=" * 60)
    print(f"  Files scanned: {scanned}")
    print(f"  Files changed: {len(changed_files)}")
    print(f"  Total substitutions: {total_subs}")

    if changed_files:
        print("\nChanged files:")
        for fp, count, details in changed_files[:50]:  # limit output
            rel_path = fp.relative_to(root) if fp.is_relative_to(root) else fp
            print(f"  ✓ {rel_path} ({count} substitutions)")
            if args.verbose and details:
                for d in details:
                    print(d)
        if len(changed_files) > 50:
            print(f"  ... (+{len(changed_files) - 50} more files)")

    if args.dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN COMPLETE - No files were modified.")
        print("Re-run without --dry-run to apply changes.")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("RENAME COMPLETE")
        print("=" * 60)

    print("\nManual steps required:")
    print("  1. Rename the repository folder: lablet-cloud-manager -> lablet-cloud-manager")
    print("  2. Update git remote origin URL if applicable")
    print("  3. Update Keycloak realm/client names if used")
    print("  4. Update Docker image names/tags")
    print("  5. Run tests: 'make test' or 'pytest'")
    print("  6. Search for any remaining 'ccm' or 'cml-cloud' occurrences")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[abort] Interrupted by user.")
        sys.exit(2)
