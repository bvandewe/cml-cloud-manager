"""Tests for shared domain models."""


class TestPackageImport:
    """Test that the core package can be imported."""

    def test_import_lcm_core(self):
        """Test lcm_core package imports successfully."""
        import lcm_core

        assert lcm_core.__version__ == "0.1.0"

    def test_import_domain(self):
        """Test domain subpackage imports successfully."""
        from lcm_core import domain

        assert domain is not None

    def test_import_domain_entities(self):
        """Test domain.entities subpackage imports successfully."""
        from lcm_core.domain import entities

        assert entities is not None

    def test_import_domain_enums(self):
        """Test domain.enums subpackage imports successfully."""
        from lcm_core.domain import enums

        assert enums is not None

    def test_import_domain_value_objects(self):
        """Test domain.value_objects subpackage imports successfully."""
        from lcm_core.domain import value_objects

        assert value_objects is not None

    def test_import_domain_events(self):
        """Test domain.events subpackage imports successfully."""
        from lcm_core.domain import events

        assert events is not None

    def test_import_integration(self):
        """Test integration subpackage imports successfully."""
        from lcm_core import integration

        assert integration is not None

    def test_import_infrastructure(self):
        """Test infrastructure subpackage imports successfully."""
        from lcm_core import infrastructure

        assert infrastructure is not None
