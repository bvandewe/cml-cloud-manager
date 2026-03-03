#!/usr/bin/env python3
"""
Update mkdocs.yml with environment variables.

This script reads the .env file and updates the mkdocs.yml configuration
with the documentation settings.
"""

import sys
from pathlib import Path


def load_env_file(env_path: Path) -> dict:
    """Load environment variables from .env file."""
    env_vars = {}
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    # Remove quotes if present
                    value = value.strip().strip('"').strip("'")
                    env_vars[key] = value
    return env_vars


def update_mkdocs_yml(mkdocs_path: Path, env_vars: dict):
    """Update mkdocs.yml with environment variables."""
    if not mkdocs_path.exists():
        print(f"Error: {mkdocs_path} not found")
        sys.exit(1)

    # Read current mkdocs.yml
    with open(mkdocs_path, "r") as f:
        lines = f.readlines()

    # Get values from env vars or keep defaults
    site_name = env_vars.get("DOCS_SITE_NAME", "Cml Cloud Manager")
    site_url = env_vars.get("DOCS_SITE_URL", "https://bvandewe.github.io/lablet-cloud-manager")
    docs_dir = env_vars.get("DOCS_FOLDER", "./docs").lstrip("./")

    # Update specific lines
    updated_lines = []
    for line in lines:
        if line.startswith("site_name:"):
            updated_lines.append(f"site_name: {site_name}\n")
        elif line.startswith("site_url:"):
            updated_lines.append(f"site_url: {site_url}\n")
        elif line.startswith("docs_dir:"):
            updated_lines.append(f"docs_dir: {docs_dir}\n")
        else:
            updated_lines.append(line)

    # Write updated mkdocs.yml
    with open(mkdocs_path, "w") as f:
        f.writelines(updated_lines)

    print(f"✅ Updated {mkdocs_path}")
    print(f"   Site Name: {site_name}")
    print(f"   Site URL:  {site_url}")
    print(f"   Docs Dir:  {docs_dir}")


def main():
    """Main function."""
    # Get project root (script is in scripts/ subdirectory)
    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"
    mkdocs_path = project_root / "mkdocs.yml"

    # Load environment variables
    env_vars = load_env_file(env_path)

    # Update mkdocs.yml
    update_mkdocs_yml(mkdocs_path, env_vars)


if __name__ == "__main__":
    main()
