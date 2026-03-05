"""Domain utility functions — shared across all services.

This module provides pure domain utilities that don't depend on
infrastructure or external services. Available to all microservices
via the lcm-core package.
"""

import re


def slugify_fqn(form_qualified_name: str) -> str:
    """Convert a Form Qualified Name to a valid S3 bucket name.

    FQN format: "{trackType} {trackLevel} {trackAcronym} {examVersion} {moduleAcronym} {formName}"
    Example: "Exam Associate CCNA v1.1 LAB 1.3a" → "exam-associate-ccna-v1.1-lab-1.3a"

    Rules:
    - Convert to lowercase
    - Replace spaces with dashes
    - Strip any characters not valid in S3 bucket names
    - Collapse multiple consecutive dashes
    - Strip leading/trailing dashes

    Args:
        form_qualified_name: The FQN string (6 space-separated components).

    Returns:
        A valid S3 bucket name string.

    Raises:
        ValueError: If the FQN is empty or produces an empty slug.
    """
    if not form_qualified_name or not form_qualified_name.strip():
        raise ValueError("form_qualified_name cannot be empty")

    slug = form_qualified_name.strip().lower()
    slug = slug.replace(" ", "-")
    # Remove any chars that aren't lowercase alphanumeric, dash, or dot
    slug = re.sub(r"[^a-z0-9.\-]", "", slug)
    # Collapse multiple dashes
    slug = re.sub(r"-{2,}", "-", slug)
    # Strip leading/trailing dashes
    slug = slug.strip("-")

    if not slug:
        raise ValueError(f"Slugified FQN is empty after processing: '{form_qualified_name}'")

    return slug
