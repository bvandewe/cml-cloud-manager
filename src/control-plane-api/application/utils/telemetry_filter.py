"""Utilities for filtering and processing CML telemetry events."""

import logging
import re
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def parse_event_timestamp(timestamp_str: str) -> datetime:
    """Parse CML telemetry event timestamp.

    CML timestamps can be in multiple ISO 8601 formats:
    - "2025-11-19T10:25:32.810Z" (with microseconds and Z)
    - "2025-11-19T10:25:32Z" (without microseconds, with Z)
    - "2025-11-19T10:25:32" (without microseconds, without Z)

    Args:
        timestamp_str: ISO format timestamp string

    Returns:
        datetime object in UTC
    """
    # Try formats in order of specificity
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",  # With microseconds and Z
        "%Y-%m-%dT%H:%M:%S.%f",  # With microseconds, no Z
        "%Y-%m-%dT%H:%M:%SZ",  # Without microseconds, with Z
        "%Y-%m-%dT%H:%M:%S",  # Without microseconds, no Z
    ]

    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str, fmt).replace(tzinfo=None)
        except ValueError:
            continue

    # If none match, raise error with helpful message
    raise ValueError(f"Timestamp '{timestamp_str}' does not match any expected format. " f"Expected ISO 8601 format like '2025-11-19T10:25:32' or '2025-11-19T10:25:32Z'")


def filter_relevant_events(
    events: list[dict[str, Any]],
    relevant_categories: list[str],
    exclude_user_pattern: str,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Filter telemetry events for genuine user activity.

    Args:
        events: Raw telemetry events from CML API
        relevant_categories: List of event categories to include
        exclude_user_pattern: Regex pattern for user_id to exclude (automated events)
        since: Only include events after this timestamp

    Returns:
        List of filtered events representing genuine user activity
    """
    filtered = []
    excluded_count = 0

    for event in events:
        try:
            # Parse event timestamp
            event_time = parse_event_timestamp(event.get("timestamp", ""))

            # Skip if before cutoff timestamp
            if since and event_time <= since:
                continue

            # Check category
            category = event.get("category", "")
            if category not in relevant_categories:
                excluded_count += 1
                continue

            # Special handling for user_activity - exclude automated API calls
            if category == "user_activity":
                data = event.get("data", {})
                user_id = data.get("user_id", "")

                # Exclude automated admin API calls (UUIDs starting with 00000000-0000-)
                if re.match(exclude_user_pattern, user_id):
                    excluded_count += 1
                    continue

            # Event passed all filters
            filtered.append(event)

        except Exception as e:
            log.warning(f"Error processing event {event}: {e}")
            continue

    log.debug(f"Filtered {len(filtered)} relevant events from {len(events)} total " f"({excluded_count} excluded by filters)")

    return filtered


def get_most_recent_events(events: list[dict[str, Any]], max_count: int = 10) -> list[dict[str, Any]]:
    """Get the N most recent events sorted by timestamp.

    Args:
        events: List of events
        max_count: Maximum number of events to return

    Returns:
        List of most recent events (sorted newest first)
    """
    if not events:
        return []

    # Sort by timestamp descending (newest first)
    try:
        sorted_events = sorted(
            events,
            key=lambda e: parse_event_timestamp(e.get("timestamp", "")),
            reverse=True,
        )
        return sorted_events[:max_count]
    except Exception as e:
        log.warning(f"Error sorting events by timestamp: {e}")
        # Return unsorted if sorting fails
        return events[:max_count]


def get_latest_activity_timestamp(events: list[dict[str, Any]]) -> datetime | None:
    """Get the timestamp of the most recent activity event.

    Args:
        events: List of activity events

    Returns:
        Timestamp of most recent event, or None if no events
    """
    if not events:
        return None

    try:
        timestamps = [parse_event_timestamp(e.get("timestamp", "")) for e in events]
        return max(timestamps) if timestamps else None
    except Exception as e:
        log.warning(f"Error extracting latest timestamp: {e}")
        return None
