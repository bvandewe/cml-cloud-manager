"""GradingScore value object for assessment results.

Represents the result of automated grading for a LabletSession,
including individual check results and overall scoring.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class GradingCheckResult:
    """Result of a single grading check.

    Each check evaluates a specific aspect of the lab configuration
    or state against expected criteria.
    """

    check_id: str  # Unique identifier for the check
    check_name: str  # Human-readable name
    passed: bool  # Whether the check passed
    points_earned: float  # Points earned for this check
    points_possible: float  # Maximum points for this check
    message: str | None = None  # Explanation or feedback
    details: dict[str, Any] | None = None  # Additional check-specific data

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "check_id": self.check_id,
            "check_name": self.check_name,
            "passed": self.passed,
            "points_earned": self.points_earned,
            "points_possible": self.points_possible,
            "message": self.message,
            "details": self.details,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "GradingCheckResult":
        """Create from dictionary."""
        return GradingCheckResult(
            check_id=data["check_id"],
            check_name=data["check_name"],
            passed=data["passed"],
            points_earned=data["points_earned"],
            points_possible=data["points_possible"],
            message=data.get("message"),
            details=data.get("details"),
        )

    @property
    def percentage(self) -> float:
        """Calculate percentage score for this check."""
        if self.points_possible == 0:
            return 100.0 if self.passed else 0.0
        return (self.points_earned / self.points_possible) * 100


@dataclass(frozen=True)
class GradingScore:
    """Aggregate grading result for a LabletSession.

    Contains overall score and individual check results from
    the grading service evaluation.
    """

    total_points_earned: float
    total_points_possible: float
    check_results: tuple[GradingCheckResult, ...]  # Immutable tuple
    graded_at: datetime
    grading_rules_uri: str | None = None  # Reference to rules used
    grading_rules_version: str | None = None  # Version of rules
    grader_version: str | None = None  # Version of grading service

    def __post_init__(self) -> None:
        """Validate grading score on creation."""
        if self.total_points_earned < 0:
            raise ValueError("total_points_earned cannot be negative")
        if self.total_points_possible < 0:
            raise ValueError("total_points_possible cannot be negative")
        if self.total_points_earned > self.total_points_possible:
            raise ValueError("total_points_earned cannot exceed total_points_possible")

    @property
    def percentage(self) -> float:
        """Calculate overall percentage score."""
        if self.total_points_possible == 0:
            return 100.0
        return (self.total_points_earned / self.total_points_possible) * 100

    @property
    def passed_checks(self) -> int:
        """Count of passed checks."""
        return sum(1 for c in self.check_results if c.passed)

    @property
    def failed_checks(self) -> int:
        """Count of failed checks."""
        return sum(1 for c in self.check_results if not c.passed)

    @property
    def total_checks(self) -> int:
        """Total number of checks."""
        return len(self.check_results)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_points_earned": self.total_points_earned,
            "total_points_possible": self.total_points_possible,
            "check_results": [c.to_dict() for c in self.check_results],
            "graded_at": self.graded_at.isoformat(),
            "grading_rules_uri": self.grading_rules_uri,
            "grading_rules_version": self.grading_rules_version,
            "grader_version": self.grader_version,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "GradingScore":
        """Create from dictionary."""
        check_results = tuple(GradingCheckResult.from_dict(c) for c in data.get("check_results", []))
        return GradingScore(
            total_points_earned=data["total_points_earned"],
            total_points_possible=data["total_points_possible"],
            check_results=check_results,
            graded_at=datetime.fromisoformat(data["graded_at"]),
            grading_rules_uri=data.get("grading_rules_uri"),
            grading_rules_version=data.get("grading_rules_version"),
            grader_version=data.get("grader_version"),
        )

    @staticmethod
    def empty() -> "GradingScore":
        """Create an empty grading score (no checks performed)."""
        from datetime import timezone

        return GradingScore(
            total_points_earned=0,
            total_points_possible=0,
            check_results=(),
            graded_at=datetime.now(timezone.utc),
        )
