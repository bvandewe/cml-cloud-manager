"""Domain tests for ScoreReport entity and ScoreSection value object.

Phase 7C: Tests immutability, factory, computed properties,
and serialization for ScoreReport (ADR-021 §3).
"""

import pytest
from domain.entities.score_report import ScoreReport, ScoreSection

# =============================================================================
# Tests — ScoreSection Value Object
# =============================================================================


class TestScoreSection:
    """Tests for the frozen ScoreSection value object."""

    def test_create_score_section(self) -> None:
        section = ScoreSection(name="Connectivity", score=8.0, max_score=10.0, cut_score=6.0, passed=True)
        assert section.name == "Connectivity"
        assert section.score == 8.0
        assert section.max_score == 10.0
        assert section.cut_score == 6.0
        assert section.passed is True

    def test_percentage(self) -> None:
        section = ScoreSection(name="Test", score=7.5, max_score=10.0)
        assert section.percentage == 75.0

    def test_percentage_zero_max(self) -> None:
        section = ScoreSection(name="Test", score=0, max_score=0)
        assert section.percentage == 0.0

    def test_frozen_immutability(self) -> None:
        section = ScoreSection(name="Test", score=5.0, max_score=10.0)
        with pytest.raises(AttributeError):
            section.score = 9.0  # type: ignore[misc]

    def test_to_dict(self) -> None:
        section = ScoreSection(
            name="Routing",
            score=9.0,
            max_score=10.0,
            cut_score=7.0,
            passed=True,
            details={"ospf": "pass", "bgp": "pass"},
        )
        d = section.to_dict()
        assert d["name"] == "Routing"
        assert d["score"] == 9.0
        assert d["details"]["ospf"] == "pass"

    def test_from_dict(self) -> None:
        data = {
            "name": "Switching",
            "score": 6.0,
            "max_score": 10.0,
            "cut_score": 7.0,
            "passed": False,
            "details": {},
        }
        section = ScoreSection.from_dict(data)
        assert section.name == "Switching"
        assert section.score == 6.0
        assert section.passed is False

    def test_from_dict_defaults(self) -> None:
        data = {"name": "Minimal", "score": 5}
        section = ScoreSection.from_dict(data)
        assert section.max_score == 0.0
        assert section.cut_score == 0.0
        assert section.passed is True
        assert section.details == {}

    def test_roundtrip_serialization(self) -> None:
        original = ScoreSection(name="Test", score=8.5, max_score=10.0, cut_score=6.0, passed=True, details={"a": 1})
        restored = ScoreSection.from_dict(original.to_dict())
        assert restored == original


# =============================================================================
# Tests — ScoreReport Creation
# =============================================================================


class TestScoreReportCreation:
    """Tests for ScoreReport.create() factory."""

    def test_create_basic(self) -> None:
        report = ScoreReport.create(
            score_report_id="sr-001",
            lablet_session_id="ls-001",
            grading_session_id="gs-001",
            score=85.0,
            max_score=100.0,
            cut_score=70.0,
            passed=True,
            grade_result="pass",
        )
        assert report.id == "sr-001"
        assert report.lablet_session_id == "ls-001"
        assert report.grading_session_id == "gs-001"
        assert report.score == 85.0
        assert report.max_score == 100.0
        assert report.cut_score == 70.0
        assert report.passed is True
        assert report.grade_result == "pass"
        assert report.submitted_at is not None

    def test_create_with_sections(self) -> None:
        sections = [
            ScoreSection(name="Routing", score=18.0, max_score=20.0, cut_score=14.0, passed=True),
            ScoreSection(name="Switching", score=12.0, max_score=20.0, cut_score=14.0, passed=False),
        ]
        report = ScoreReport.create(
            score_report_id="sr-002",
            lablet_session_id="ls-002",
            grading_session_id="gs-002",
            score=30.0,
            max_score=40.0,
            cut_score=28.0,
            passed=True,
            grade_result="pass",
            sections=sections,
        )
        assert len(report.sections) == 2
        assert report.sections[0].name == "Routing"
        assert report.sections[1].name == "Switching"

    def test_create_defaults(self) -> None:
        report = ScoreReport.create(
            score_report_id="sr-003",
            lablet_session_id="ls-003",
            grading_session_id="gs-003",
            score=0,
            max_score=0,
        )
        assert report.cut_score == 0.0
        assert report.passed is False
        assert report.grade_result == ""
        assert report.sections == []


# =============================================================================
# Tests — Computed Properties
# =============================================================================


class TestScoreReportProperties:
    """Tests for computed properties."""

    def test_percentage(self) -> None:
        report = ScoreReport.create(
            score_report_id="sr-01",
            lablet_session_id="ls-01",
            grading_session_id="gs-01",
            score=85.0,
            max_score=100.0,
            passed=True,
        )
        assert report.percentage == 85.0

    def test_percentage_zero_max(self) -> None:
        report = ScoreReport.create(
            score_report_id="sr-01",
            lablet_session_id="ls-01",
            grading_session_id="gs-01",
            score=0,
            max_score=0,
        )
        assert report.percentage == 0.0

    def test_passed_sections(self) -> None:
        sections = [
            ScoreSection(name="A", score=10, max_score=10, passed=True),
            ScoreSection(name="B", score=3, max_score=10, passed=False),
            ScoreSection(name="C", score=8, max_score=10, passed=True),
        ]
        report = ScoreReport.create(
            score_report_id="sr-01",
            lablet_session_id="ls-01",
            grading_session_id="gs-01",
            score=21,
            max_score=30,
            passed=True,
            sections=sections,
        )
        assert report.passed_sections == 2
        assert report.total_sections == 3

    def test_passed_percentage(self) -> None:
        sections = [
            ScoreSection(name="A", score=10, max_score=10, passed=True),
            ScoreSection(name="B", score=3, max_score=10, passed=False),
        ]
        report = ScoreReport.create(
            score_report_id="sr-01",
            lablet_session_id="ls-01",
            grading_session_id="gs-01",
            score=13,
            max_score=20,
            passed=False,
            sections=sections,
        )
        assert report.passed_percentage == 50.0

    def test_section_names(self) -> None:
        sections = [
            ScoreSection(name="Routing", score=10, max_score=10),
            ScoreSection(name="Switching", score=8, max_score=10),
        ]
        report = ScoreReport.create(
            score_report_id="sr-01",
            lablet_session_id="ls-01",
            grading_session_id="gs-01",
            score=18,
            max_score=20,
            passed=True,
            sections=sections,
        )
        assert report.section_names == ["Routing", "Switching"]


# =============================================================================
# Tests — Serialization Helpers
# =============================================================================


class TestScoreReportSerialization:
    """Tests for sections serialization helpers."""

    def test_sections_to_dicts(self) -> None:
        sections = [
            ScoreSection(name="A", score=10, max_score=10),
            ScoreSection(name="B", score=8, max_score=10),
        ]
        report = ScoreReport.create(
            score_report_id="sr-01",
            lablet_session_id="ls-01",
            grading_session_id="gs-01",
            score=18,
            max_score=20,
            passed=True,
            sections=sections,
        )
        dicts = report.sections_to_dicts()
        assert len(dicts) == 2
        assert dicts[0]["name"] == "A"
        assert dicts[1]["score"] == 8

    def test_sections_from_dicts(self) -> None:
        data = [
            {"name": "A", "score": 10, "max_score": 10, "cut_score": 7, "passed": True},
            {"name": "B", "score": 5, "max_score": 10, "cut_score": 7, "passed": False},
        ]
        sections = ScoreReport.sections_from_dicts(data)
        assert len(sections) == 2
        assert sections[0].name == "A"
        assert sections[1].passed is False

    def test_roundtrip_sections(self) -> None:
        original = [
            ScoreSection(name="X", score=9.5, max_score=10, cut_score=7, passed=True, details={"q1": "ok"}),
        ]
        restored = ScoreReport.sections_from_dicts([s.to_dict() for s in original])
        assert restored[0] == original[0]
