"""Tests for domain utility functions (lcm-core)."""

import pytest

from lcm_core.domain.utils import slugify_fqn


class TestSlugifyFqn:
    """Tests for slugify_fqn utility."""

    def test_standard_fqn(self) -> None:
        """Test standard 6-component FQN slugification."""
        result = slugify_fqn("Exam Associate CCNA v1.1 LAB 1.3a")
        assert result == "exam-associate-ccna-v1.1-lab-1.3a"

    def test_simple_fqn(self) -> None:
        """Test simple multi-word FQN."""
        result = slugify_fqn("Practice Level1 DEVNET v2.0 MODULE intro")
        assert result == "practice-level1-devnet-v2.0-module-intro"

    def test_already_lowercase(self) -> None:
        """Test FQN that is already lowercase."""
        result = slugify_fqn("exam associate ccna v1.1 lab 1.3a")
        assert result == "exam-associate-ccna-v1.1-lab-1.3a"

    def test_mixed_case(self) -> None:
        """Test FQN with mixed case is lowercased."""
        result = slugify_fqn("EXAM ASSOCIATE CCNA V1.1 LAB 1.3A")
        assert result == "exam-associate-ccna-v1.1-lab-1.3a"

    def test_extra_whitespace_stripped(self) -> None:
        """Test leading/trailing whitespace is stripped."""
        result = slugify_fqn("  Exam Associate CCNA v1.1 LAB 1.3a  ")
        assert result == "exam-associate-ccna-v1.1-lab-1.3a"

    def test_multiple_spaces_collapsed(self) -> None:
        """Test multiple spaces become single dashes."""
        result = slugify_fqn("Exam  Associate   CCNA v1.1 LAB 1.3a")
        assert result == "exam-associate-ccna-v1.1-lab-1.3a"

    def test_special_characters_removed(self) -> None:
        """Test special characters are stripped."""
        result = slugify_fqn("Exam Associate CCNA! v1.1 LAB@ 1.3a")
        assert result == "exam-associate-ccna-v1.1-lab-1.3a"

    def test_dots_preserved(self) -> None:
        """Test dots are preserved (valid in S3 bucket names)."""
        result = slugify_fqn("Exam Associate CCNA v2.3.1 LAB setup")
        assert result == "exam-associate-ccna-v2.3.1-lab-setup"

    def test_empty_string_raises(self) -> None:
        """Test empty string raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            slugify_fqn("")

    def test_whitespace_only_raises(self) -> None:
        """Test whitespace-only string raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            slugify_fqn("   ")

    def test_none_raises(self) -> None:
        """Test None raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            slugify_fqn(None)  # type: ignore[arg-type]

    def test_all_special_chars_raises(self) -> None:
        """Test string of only special chars produces empty slug and raises."""
        with pytest.raises(ValueError, match="empty after processing"):
            slugify_fqn("!@#$%^&*()")

    def test_result_is_valid_s3_bucket_name(self) -> None:
        """Test result contains only valid S3 bucket name characters."""
        import re

        result = slugify_fqn("Exam Associate CCNA v1.1 LAB 1.3a")
        # S3 bucket names: lowercase letters, numbers, hyphens, dots
        assert re.match(r"^[a-z0-9.\-]+$", result), f"Invalid S3 bucket name: {result}"
        # Must not start or end with dash
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_underscores_removed(self) -> None:
        """Test underscores are removed (not valid in S3 bucket names)."""
        result = slugify_fqn("Exam_Associate CCNA v1.1 LAB 1.3a")
        assert "_" not in result

    def test_single_component(self) -> None:
        """Test single-word FQN."""
        result = slugify_fqn("test")
        assert result == "test"
