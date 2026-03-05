"""ScoreReport entity + ScoreSection value object — grading results for a LabletSession.

Captures the final grading outcome scoped to a parent LabletSession
and linked to a GradingSession.  Stored in its own MongoDB collection
(``score_reports``).

Phase 7C (ADR-021 §3): Created as Entity[str] — **immutable after creation**.
Once recorded, the score report is an auditable evidence record and
should never be modified (append-only pattern).

Pattern: @dataclass extending Entity[str] with frozen ScoreSection VO.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from neuroglia.data import Entity

# =============================================================================
# ScoreSection Value Object
# =============================================================================


@dataclass(frozen=True)
class ScoreSection:
    """Immutable section-level scoring result.

    Represents a grading rubric section with its score, maximum,
    cut-off, and detailed scoring breakdown.

    Attributes:
        name: Section display name (e.g. "Connectivity Check").
        score: Achieved score for this section.
        max_score: Maximum achievable score for this section.
        cut_score: Minimum score required to pass this section.
        passed: Whether the section was passed (score >= cut_score).
        details: Optional fine-grained scoring details.
    """

    name: str
    score: float
    max_score: float
    cut_score: float = 0.0
    passed: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    # -------------------------------------------------------------------------
    # Computed properties
    # -------------------------------------------------------------------------

    @property
    def percentage(self) -> float:
        """Return the score as a percentage of max_score."""
        return (self.score / self.max_score * 100) if self.max_score > 0 else 0.0

    # -------------------------------------------------------------------------
    # Serialization helpers (for MongoDB persistence)
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to dict for MongoDB storage."""
        return {
            "name": self.name,
            "score": self.score,
            "max_score": self.max_score,
            "cut_score": self.cut_score,
            "passed": self.passed,
            "details": self.details,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ScoreSection":
        """Deserialise from a MongoDB dict."""
        return ScoreSection(
            name=data["name"],
            score=float(data.get("score", 0)),
            max_score=float(data.get("max_score", 0)),
            cut_score=float(data.get("cut_score", 0)),
            passed=bool(data.get("passed", True)),
            details=data.get("details", {}),
        )


# =============================================================================
# ScoreReport Entity
# =============================================================================


@dataclass
class ScoreReport(Entity[str]):
    """Immutable score report entity scoped to a LabletSession.

    Stored in its own MongoDB collection (``score_reports``).

    Once created, a ScoreReport **must not be modified** — it is an
    auditable evidence record.

    Extends Neuroglia Entity[str] for MotorRepository compatibility.

    Attributes — Identity:
        id: Globally unique score report identifier (UUID).
        lablet_session_id: FK → parent LabletSession aggregate.
        grading_session_id: FK → the GradingSession that produced this report.

    Attributes — Scoring:
        score: Total achieved score.
        max_score: Maximum achievable score.
        cut_score: Minimum score required to pass.
        passed: Whether the overall assessment was passed.
        grade_result: Human-readable grade string (e.g. "PASS", "FAIL", "80%").
        sections: Per-section scoring breakdown.

    Attributes — Timestamps:
        submitted_at: When the score report was created/submitted.
    """

    # =========================================================================
    # Identity
    # =========================================================================
    id: str = field(default_factory=lambda: str(uuid4()))
    lablet_session_id: str = ""
    grading_session_id: str = ""

    # =========================================================================
    # Scoring
    # =========================================================================
    score: float = 0.0
    max_score: float = 0.0
    cut_score: float = 0.0
    passed: bool = False
    grade_result: str = ""
    sections: list[ScoreSection] = field(default_factory=list)

    # =========================================================================
    # Timestamps
    # =========================================================================
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # =========================================================================
    # Computed properties
    # =========================================================================

    @property
    def percentage(self) -> float:
        """Return the total score as a percentage of max_score."""
        return (self.score / self.max_score * 100) if self.max_score > 0 else 0.0

    @property
    def passed_sections(self) -> int:
        """Return the count of passed sections."""
        return sum(1 for s in self.sections if s.passed)

    @property
    def total_sections(self) -> int:
        """Return the total number of sections."""
        return len(self.sections)

    @property
    def passed_percentage(self) -> float:
        """Return the percentage of sections that passed."""
        return (self.passed_sections / self.total_sections * 100) if self.total_sections > 0 else 0.0

    @property
    def section_names(self) -> list[str]:
        """Return the names of all sections."""
        return [s.name for s in self.sections]

    # =========================================================================
    # Factory
    # =========================================================================

    @staticmethod
    def create(
        score_report_id: str,
        lablet_session_id: str,
        grading_session_id: str,
        score: float,
        max_score: float,
        cut_score: float = 0.0,
        passed: bool = False,
        grade_result: str = "",
        sections: list[ScoreSection] | None = None,
    ) -> "ScoreReport":
        """Create a new ScoreReport (immutable after creation).

        Args:
            score_report_id: Globally unique identifier.
            lablet_session_id: FK → parent LabletSession.
            grading_session_id: FK → GradingSession that produced this.
            score: Total achieved score.
            max_score: Maximum achievable score.
            cut_score: Minimum score to pass (default 0.0).
            passed: Whether the assessment was passed.
            grade_result: Human-readable grade string.
            sections: Per-section scoring breakdown.

        Returns:
            A new immutable ScoreReport.
        """
        return ScoreReport(
            id=score_report_id,
            lablet_session_id=lablet_session_id,
            grading_session_id=grading_session_id,
            score=score,
            max_score=max_score,
            cut_score=cut_score,
            passed=passed,
            grade_result=grade_result,
            sections=sections or [],
            submitted_at=datetime.now(timezone.utc),
        )

    # =========================================================================
    # Serialization helpers (for sections list)
    # =========================================================================

    def sections_to_dicts(self) -> list[dict[str, Any]]:
        """Serialise sections list for MongoDB storage."""
        return [s.to_dict() for s in self.sections]

    @staticmethod
    def sections_from_dicts(data: list[dict[str, Any]]) -> list["ScoreSection"]:
        """Deserialise sections list from MongoDB."""
        return [ScoreSection.from_dict(d) for d in data]
