"""Read model for ScoreReport entities.

Immutable DTO representing the assessment score report for a LabletSession.
Created in Phase 7A per ADR-021 (child entity architecture).

ScoreReport stores the final grading results from the Grading Engine,
including the overall score, pass/fail determination, and per-section
score breakdowns.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ScoreSectionReadModel:
    """Read model for an individual scoring section within a ScoreReport.

    Value object — no independent identity. Embedded in ScoreReportReadModel.
    """

    name: str
    score: float
    max_score: float
    weight: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoreSectionReadModel":
        """Create from API response dictionary."""
        return cls(
            name=data.get("name", ""),
            score=data.get("score", 0.0),
            max_score=data.get("max_score", 0.0),
            weight=data.get("weight", 1.0),
        )


@dataclass
class ScoreReportReadModel:
    """Read model for a ScoreReport from the Control Plane API.

    Used by:
    - frontend: For displaying assessment results
    - reporting: For score aggregation and analytics

    All fields except id and lablet_session_id are optional.
    """

    # Core identity
    id: str
    lablet_session_id: str  # FK → LabletSession
    grading_session_id: str | None = None  # FK → GradingSession

    # Scores
    score: float = 0.0
    max_score: float = 0.0
    cut_score: float | None = None  # Passing threshold
    passed: bool | None = None

    # Section breakdowns
    sections: list[ScoreSectionReadModel] = field(default_factory=list)

    # Timestamps
    submitted_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoreReportReadModel":
        """Create from API response dictionary."""
        sections_data = data.get("sections", [])
        sections = [ScoreSectionReadModel.from_dict(s) for s in sections_data]

        return cls(
            id=data.get("id", ""),
            lablet_session_id=data.get("lablet_session_id", ""),
            grading_session_id=data.get("grading_session_id"),
            score=data.get("score", 0.0),
            max_score=data.get("max_score", 0.0),
            cut_score=data.get("cut_score"),
            passed=data.get("passed"),
            sections=sections,
            submitted_at=data.get("submitted_at"),
            created_at=data.get("created_at"),
        )
