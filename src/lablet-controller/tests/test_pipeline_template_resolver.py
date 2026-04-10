"""Tests for PipelineTemplateResolver.

Covers:
- Passthrough when no ``extends``
- Extends from standard templates
- insert_after operator
- insert_before operator
- overrides operator
- remove operator
- Combined operators
- Error cases (unknown template, unknown anchor)
- Top-level field overrides
- Output merging
"""

from __future__ import annotations

import pytest

from application.services.pipeline_template_resolver import (
    PipelineTemplateError,
    PipelineTemplateResolver,
)


@pytest.fixture
def resolver() -> PipelineTemplateResolver:
    """Provide a resolver instance with default templates."""
    return PipelineTemplateResolver()


class TestPassthrough:
    """When no ``extends`` is present, pipeline is returned as-is."""

    def test_inline_pipeline_unchanged(self, resolver: PipelineTemplateResolver) -> None:
        """Inline pipeline definitions should pass through without modification."""
        pipeline = {
            "description": "custom pipeline",
            "trigger": "on_status:instantiating",
            "steps": [
                {"name": "step_a", "handler": "step_a"},
                {"name": "step_b", "handler": "step_b", "needs": ["step_a"]},
            ],
        }
        result = resolver.resolve(pipeline)
        assert result is pipeline  # Same object, not a copy

    def test_empty_pipeline(self, resolver: PipelineTemplateResolver) -> None:
        """Empty pipeline should pass through."""
        pipeline: dict = {}
        result = resolver.resolve(pipeline)
        assert result == {}


class TestExtends:
    """Template extension with no customization operators."""

    def test_extends_standard_instantiate(self, resolver: PipelineTemplateResolver) -> None:
        """Extending a template with no operators returns a copy of the template."""
        pipeline = {"extends": "standard-instantiate"}
        result = resolver.resolve(pipeline)

        # Should have all standard steps
        step_names = [s["name"] for s in result["steps"]]
        assert "content_sync" in step_names
        assert "lab_resolve" in step_names
        assert "mark_ready" in step_names

    def test_extends_standard_teardown(self, resolver: PipelineTemplateResolver) -> None:
        """Extending the teardown template should include teardown steps."""
        pipeline = {"extends": "standard-teardown"}
        result = resolver.resolve(pipeline)

        step_names = [s["name"] for s in result["steps"]]
        assert "stop_lab" in step_names
        assert "wipe_lab" in step_names
        assert "archive" in step_names

    def test_extends_unknown_template_raises(self, resolver: PipelineTemplateResolver) -> None:
        """Unknown template name should raise PipelineTemplateError."""
        with pytest.raises(PipelineTemplateError, match="Unknown pipeline template: 'nonexistent'"):
            resolver.resolve({"extends": "nonexistent"})

    def test_extends_does_not_mutate_template(self, resolver: PipelineTemplateResolver) -> None:
        """Resolving should not mutate the original template."""
        pipeline = {
            "extends": "standard-instantiate",
            "remove": ["lds_provision"],
        }
        # Resolve once
        resolver.resolve(pipeline)

        # Resolve again — template should still have lds_provision
        result2 = resolver.resolve({"extends": "standard-instantiate"})
        step_names = [s["name"] for s in result2["steps"]]
        assert "lds_provision" in step_names


class TestInsertAfter:
    """insert_after operator tests."""

    def test_insert_single_step_after(self, resolver: PipelineTemplateResolver) -> None:
        """Insert a single step after a named anchor."""
        pipeline = {
            "extends": "standard-instantiate",
            "insert_after": {
                "lab_start": [
                    {
                        "name": "transfer_archive",
                        "handler": "execute_command_on_cml_node",
                        "params": {"action": "transfer_file"},
                        "needs": ["lab_start"],
                    }
                ]
            },
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]

        # transfer_archive should be immediately after lab_start
        lab_start_idx = step_names.index("lab_start")
        transfer_idx = step_names.index("transfer_archive")
        assert transfer_idx == lab_start_idx + 1

    def test_insert_multiple_steps_after(self, resolver: PipelineTemplateResolver) -> None:
        """Insert multiple steps after a named anchor (order preserved)."""
        pipeline = {
            "extends": "standard-instantiate",
            "insert_after": {
                "lab_start": [
                    {"name": "cml_cmd_1", "handler": "execute_command_on_cml_node"},
                    {"name": "cml_cmd_2", "handler": "execute_command_on_cml_node"},
                    {"name": "cml_cmd_3", "handler": "execute_command_on_cml_node"},
                ]
            },
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]

        lab_start_idx = step_names.index("lab_start")
        assert step_names[lab_start_idx + 1] == "cml_cmd_1"
        assert step_names[lab_start_idx + 2] == "cml_cmd_2"
        assert step_names[lab_start_idx + 3] == "cml_cmd_3"

    def test_insert_after_unknown_anchor_raises(self, resolver: PipelineTemplateResolver) -> None:
        """Inserting after an unknown step should raise PipelineTemplateError."""
        pipeline = {
            "extends": "standard-instantiate",
            "insert_after": {"nonexistent_step": [{"name": "new_step", "handler": "new_handler"}]},
        }
        with pytest.raises(PipelineTemplateError, match="insert_after: anchor step 'nonexistent_step' not found"):
            resolver.resolve(pipeline)


class TestInsertBefore:
    """insert_before operator tests."""

    def test_insert_single_step_before(self, resolver: PipelineTemplateResolver) -> None:
        """Insert a single step before a named anchor."""
        pipeline = {
            "extends": "standard-instantiate",
            "insert_before": {
                "lab_start": [
                    {
                        "name": "pre_start_check",
                        "handler": "pre_start_check",
                    }
                ]
            },
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]

        lab_start_idx = step_names.index("lab_start")
        pre_check_idx = step_names.index("pre_start_check")
        assert pre_check_idx == lab_start_idx - 1

    def test_insert_before_unknown_anchor_raises(self, resolver: PipelineTemplateResolver) -> None:
        """Inserting before an unknown step should raise PipelineTemplateError."""
        pipeline = {
            "extends": "standard-instantiate",
            "insert_before": {"nonexistent_step": [{"name": "new_step", "handler": "new_handler"}]},
        }
        with pytest.raises(PipelineTemplateError, match="insert_before: anchor step 'nonexistent_step' not found"):
            resolver.resolve(pipeline)


class TestOverrides:
    """overrides operator tests."""

    def test_override_step_timeout(self, resolver: PipelineTemplateResolver) -> None:
        """Override a single field on a step."""
        pipeline = {
            "extends": "standard-instantiate",
            "overrides": {
                "lab_start": {"timeout_seconds": 600},
            },
        }
        result = resolver.resolve(pipeline)
        lab_start = next(s for s in result["steps"] if s["name"] == "lab_start")
        assert lab_start["timeout_seconds"] == 600

    def test_override_step_retry(self, resolver: PipelineTemplateResolver) -> None:
        """Override retry config on a step."""
        pipeline = {
            "extends": "standard-instantiate",
            "overrides": {
                "lab_start": {
                    "retry": {"max_attempts": 10, "delay_seconds": 5},
                },
            },
        }
        result = resolver.resolve(pipeline)
        lab_start = next(s for s in result["steps"] if s["name"] == "lab_start")
        assert lab_start["retry"]["max_attempts"] == 10
        assert lab_start["retry"]["delay_seconds"] == 5

    def test_override_unknown_step_raises(self, resolver: PipelineTemplateResolver) -> None:
        """Overriding a nonexistent step should raise PipelineTemplateError."""
        pipeline = {
            "extends": "standard-instantiate",
            "overrides": {
                "nonexistent": {"timeout_seconds": 60},
            },
        }
        with pytest.raises(PipelineTemplateError, match="overrides: step 'nonexistent' not found"):
            resolver.resolve(pipeline)


class TestRemove:
    """remove operator tests."""

    def test_remove_single_step(self, resolver: PipelineTemplateResolver) -> None:
        """Remove a single step from the template."""
        pipeline = {
            "extends": "standard-instantiate",
            "remove": ["lds_provision"],
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]
        assert "lds_provision" not in step_names

    def test_remove_multiple_steps(self, resolver: PipelineTemplateResolver) -> None:
        """Remove multiple steps from the template."""
        pipeline = {
            "extends": "standard-instantiate",
            "remove": ["lds_provision", "tags_sync", "ports_alloc"],
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]
        assert "lds_provision" not in step_names
        assert "tags_sync" not in step_names
        assert "ports_alloc" not in step_names
        # Other steps should remain
        assert "lab_resolve" in step_names
        assert "lab_start" in step_names

    def test_remove_nonexistent_step_is_silent(self, resolver: PipelineTemplateResolver) -> None:
        """Removing a step that doesn't exist should silently succeed."""
        pipeline = {
            "extends": "standard-instantiate",
            "remove": ["doesnt_exist"],
        }
        result = resolver.resolve(pipeline)
        # Should resolve without error; same step count as original
        original = resolver.resolve({"extends": "standard-instantiate"})
        assert len(result["steps"]) == len(original["steps"])


class TestCombinedOperators:
    """Test multiple operators applied together."""

    def test_remove_then_insert(self, resolver: PipelineTemplateResolver) -> None:
        """Remove a step and insert a replacement."""
        pipeline = {
            "extends": "standard-instantiate",
            "remove": ["lds_provision"],
            "insert_after": {
                "lab_start": [
                    {
                        "name": "custom_provision",
                        "handler": "custom_provision",
                        "description": "Custom provisioning instead of LDS",
                    }
                ]
            },
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]
        assert "lds_provision" not in step_names
        assert "custom_provision" in step_names

    def test_insert_after_with_override(self, resolver: PipelineTemplateResolver) -> None:
        """Insert new steps and override existing step timeout."""
        pipeline = {
            "extends": "standard-instantiate",
            "insert_after": {
                "lab_start": [
                    {"name": "cml_custom", "handler": "execute_command_on_cml_node"},
                ]
            },
            "overrides": {
                "lab_start": {"timeout_seconds": 600},
            },
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]
        assert "cml_custom" in step_names

        lab_start = next(s for s in result["steps"] if s["name"] == "lab_start")
        assert lab_start["timeout_seconds"] == 600

    def test_real_world_devnet_expert_pipeline(self, resolver: PipelineTemplateResolver) -> None:
        """Simulate a real-world DevNet Expert lab that needs custom CML commands."""
        pipeline = {
            "extends": "standard-instantiate",
            "description": "DevNet Expert lab — inject custom node config after lab start",
            "insert_after": {
                "lab_start": [
                    {
                        "name": "transfer_archive_to_cml_node",
                        "handler": "execute_command_on_cml_node",
                        "needs": ["lab_start"],
                        "params": {
                            "action": "transfer_file",
                            "node_label": "devbox",
                            "source_url": "s3://lablet-assets/devnet-expert/lab-config.tar.gz",
                            "dest_path": "/tmp/lab-config.tar.gz",
                        },
                        "timeout_seconds": 120,
                    },
                    {
                        "name": "extract_archive_on_cml_node",
                        "handler": "execute_command_on_cml_node",
                        "needs": ["transfer_archive_to_cml_node"],
                        "params": {
                            "action": "execute_command",
                            "node_label": "devbox",
                            "command": "tar xzf /tmp/lab-config.tar.gz -C /opt/lab-config/",
                        },
                        "timeout_seconds": 60,
                    },
                    {
                        "name": "shut_cml_node_interface",
                        "handler": "execute_command_on_cml_node",
                        "needs": ["extract_archive_on_cml_node"],
                        "params": {
                            "action": "shut_interface",
                            "node_label": "devbox",
                            "interface_id": "eth0",
                        },
                        "timeout_seconds": 30,
                    },
                ]
            },
            "overrides": {
                "lab_start": {"timeout_seconds": 600},
                "mark_ready": {"needs": ["lab_start", "lds_provision", "shut_cml_node_interface"]},
            },
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]

        # Standard steps still present
        assert "content_sync" in step_names
        assert "lab_resolve" in step_names
        assert "lab_start" in step_names
        assert "mark_ready" in step_names

        # Custom steps injected in order
        lab_start_idx = step_names.index("lab_start")
        assert step_names[lab_start_idx + 1] == "transfer_archive_to_cml_node"
        assert step_names[lab_start_idx + 2] == "extract_archive_on_cml_node"
        assert step_names[lab_start_idx + 3] == "shut_cml_node_interface"

        # Overrides applied
        lab_start = next(s for s in result["steps"] if s["name"] == "lab_start")
        assert lab_start["timeout_seconds"] == 600

        mark_ready = next(s for s in result["steps"] if s["name"] == "mark_ready")
        assert "shut_cml_node_interface" in mark_ready["needs"]


class TestTopLevelOverrides:
    """Test overriding top-level pipeline fields."""

    def test_override_description(self, resolver: PipelineTemplateResolver) -> None:
        """Pipeline-level description should override template description."""
        pipeline = {
            "extends": "standard-instantiate",
            "description": "Custom description for this lab variant",
        }
        result = resolver.resolve(pipeline)
        assert result["description"] == "Custom description for this lab variant"

    def test_override_max_retries(self, resolver: PipelineTemplateResolver) -> None:
        """Pipeline-level max_retries should override template value."""
        pipeline = {
            "extends": "standard-instantiate",
            "max_retries": 5,
        }
        result = resolver.resolve(pipeline)
        assert result["max_retries"] == 5


class TestOutputMerging:
    """Test output expression merging."""

    def test_outputs_merged(self, resolver: PipelineTemplateResolver) -> None:
        """Custom outputs should be merged into template outputs."""
        pipeline = {
            "extends": "standard-instantiate",
            "outputs": {
                "custom_output": "$STEPS.transfer_archive.result",
            },
        }
        result = resolver.resolve(pipeline)
        assert "custom_output" in result["outputs"]
        # Original outputs also present
        assert "cml_lab_id" in result["outputs"]

    def test_outputs_override_existing(self, resolver: PipelineTemplateResolver) -> None:
        """Custom outputs can override template output expressions."""
        pipeline = {
            "extends": "standard-instantiate",
            "outputs": {
                "cml_lab_id": "$STEPS.custom_resolve.lab_id",  # Override existing
            },
        }
        result = resolver.resolve(pipeline)
        assert result["outputs"]["cml_lab_id"] == "$STEPS.custom_resolve.lab_id"


class TestExtraTemplates:
    """Test registering additional templates."""

    def test_extra_template_registered(self) -> None:
        """Extra templates passed to constructor should be available."""
        extra = {
            "custom-template": {
                "description": "Custom pipeline",
                "steps": [
                    {"name": "custom_step", "handler": "custom_handler"},
                ],
            }
        }
        resolver = PipelineTemplateResolver(extra_templates=extra)
        result = resolver.resolve({"extends": "custom-template"})
        assert result["steps"][0]["name"] == "custom_step"

    def test_extra_template_does_not_shadow_builtins(self) -> None:
        """Extra templates should not prevent access to built-in templates."""
        extra = {"my-template": {"steps": []}}
        resolver = PipelineTemplateResolver(extra_templates=extra)
        # Built-in templates should still work
        result = resolver.resolve({"extends": "standard-teardown"})
        step_names = [s["name"] for s in result["steps"]]
        assert "stop_lab" in step_names

    def test_get_template_names_includes_extras(self) -> None:
        """get_template_names should list both built-in and extra templates."""
        extra = {"my-custom": {"steps": []}}
        resolver = PipelineTemplateResolver(extra_templates=extra)
        names = resolver.get_template_names()
        assert "my-custom" in names
        assert "standard-instantiate" in names
        assert "standard-teardown" in names


class TestOperatorApplicationOrder:
    """Verify that operators are applied in the correct order: remove → insert_before → insert_after → overrides."""

    def test_remove_before_insert_after(self, resolver: PipelineTemplateResolver) -> None:
        """Removing a step and inserting after its neighbor should work."""
        pipeline = {
            "extends": "standard-instantiate",
            "remove": ["tags_sync"],
            "insert_after": {
                "ports_alloc": [
                    {"name": "custom_tags", "handler": "custom_tags"},
                ]
            },
        }
        result = resolver.resolve(pipeline)
        step_names = [s["name"] for s in result["steps"]]
        assert "tags_sync" not in step_names
        assert "custom_tags" in step_names
        # custom_tags should be after ports_alloc
        assert step_names.index("custom_tags") == step_names.index("ports_alloc") + 1

    def test_insert_before_then_override_inserted(self, resolver: PipelineTemplateResolver) -> None:
        """Cannot override a step that was just inserted (overrides only work on steps already in base)."""
        pipeline = {
            "extends": "standard-instantiate",
            "insert_before": {
                "lab_start": [
                    {"name": "new_step", "handler": "new_handler", "timeout_seconds": 30},
                ]
            },
            "overrides": {
                # This should find "new_step" because insert_before runs before overrides
                "new_step": {"timeout_seconds": 120},
            },
        }
        result = resolver.resolve(pipeline)
        new_step = next(s for s in result["steps"] if s["name"] == "new_step")
        assert new_step["timeout_seconds"] == 120
