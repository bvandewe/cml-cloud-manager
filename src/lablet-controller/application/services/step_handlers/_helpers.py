"""Shared utilities for step handlers.

Common helper functions used across multiple step handler modules.
"""

from __future__ import annotations

from typing import Any


def get_step_result_data(progress: dict[str, Any], step_name: str) -> dict[str, Any] | None:
    """Extract result_data from a completed step in the progress dict.

    Args:
        progress: The pipeline progress dict (step_name → step_info dict).
        step_name: Name of the upstream step to look up.

    Returns:
        The result_data dict from the specified step, or None if not found/invalid.
    """
    step_info = progress.get(step_name)
    if not step_info or not isinstance(step_info, dict):
        return None
    return step_info.get("result_data")
