"""Grading session status enum — shared across all services.

Represents the LCM-internal lifecycle states for a GradingSession (ADR-021).
These are simplified abstractions of the Grading Engine native session part
states. The lablet-controller maps GE native statuses to these internal values.

Grading Engine native state mapping (for reference):
    GE created     →  PENDING
    (LCM internal) →  COLLECTING  (device output collection, before GE interaction)
    GE grading     →  GRADING
    GE reviewing   →  REVIEWING
    GE locked      →  SUBMITTED
    GE faulted     →  FAULTED

Renamed from GradingStatus → GradingSessionStatus in Phase 7A (AD-P7-06).
"""

from lcm_core.domain.enums.case_insensitive_enum import CaseInsensitiveStrEnum


class GradingSessionStatus(CaseInsensitiveStrEnum):
    """Lifecycle states for a GradingSession (Grading Engine tracking).

    State Machine:
        PENDING → COLLECTING → GRADING → REVIEWING → SUBMITTED
                                                   ↘ FAULTED (from any non-terminal state)
    """

    PENDING = "pending"  # Grading not yet started
    COLLECTING = "collecting"  # Assessment data being collected from lab
    GRADING = "grading"  # Grading engine processing
    REVIEWING = "reviewing"  # Score available, awaiting proctor review
    SUBMITTED = "submitted"  # Final score submitted (terminal)
    FAULTED = "faulted"  # Grading failed (terminal)
