"""Tests for PAv1Validator (manifest / lifecycle / scenario schemas)."""

from __future__ import annotations

from typing import Any

import pytest
from lcm_core.infrastructure.content_store import PAv1ValidationError, PAv1Validator


@pytest.fixture
def validator() -> PAv1Validator:
    return PAv1Validator()


def _minimal_manifest() -> dict[str, Any]:
    return {
        "format_version": "PAv1",
        "name": "example-lab",
        "version": "1.0.0",
        "content_id": "example-lab",
        "pod_type": "cml_on_aws",
    }


class TestManifestSchema:
    def test_minimal_manifest_passes(self, validator: PAv1Validator) -> None:
        validator.validate_manifest(_minimal_manifest())

    def test_manifest_without_optional_pod_type_passes(self, validator: PAv1Validator) -> None:
        data = _minimal_manifest()
        del data["pod_type"]
        validator.validate_manifest(data)  # pod_type is optional per spec

    def test_missing_format_version_fails(self, validator: PAv1Validator) -> None:
        data = _minimal_manifest()
        del data["format_version"]
        with pytest.raises(PAv1ValidationError) as excinfo:
            validator.validate_manifest(data)
        assert any("format_version" in err for err in excinfo.value.errors)

    def test_wrong_format_version_fails(self, validator: PAv1Validator) -> None:
        data = _minimal_manifest()
        data["format_version"] = "PAv2"
        with pytest.raises(PAv1ValidationError):
            validator.validate_manifest(data)

    def test_unknown_pod_type_fails(self, validator: PAv1Validator) -> None:
        data = _minimal_manifest()
        data["pod_type"] = "made_up_type"
        with pytest.raises(PAv1ValidationError) as excinfo:
            validator.validate_manifest(data)
        assert any("pod_type" in err for err in excinfo.value.errors)

    def test_non_dict_input_fails(self, validator: PAv1Validator) -> None:
        with pytest.raises(PAv1ValidationError):
            validator.validate_manifest("not a dict")  # type: ignore[arg-type]


class TestLifecycleSchema:
    def test_minimal_lifecycle_passes(self, validator: PAv1Validator) -> None:
        validator.validate_lifecycle({"phases": {"instantiate": {"steps": [{"name": "lab_resolve", "handler": "scenario_engine/lab_resolve@v1"}]}}})

    def test_lifecycle_with_full_step_metadata_passes(self, validator: PAv1Validator) -> None:
        validator.validate_lifecycle(
            {
                "phases": {
                    "instantiate": {
                        "steps": [
                            {
                                "name": "lab_start",
                                "handler": "scenario_engine/lab_start@v1",
                                "depends_on": ["lab_resolve"],
                                "skip_when": "$session.skip_start == True",
                                "retry": {"attempts": 3, "backoff_seconds": 5},
                                "timeout": {"seconds": 120},
                                "inputs": {"worker_id": "$session.worker_id"},
                            }
                        ]
                    }
                }
            }
        )

    def test_empty_phases_fails(self, validator: PAv1Validator) -> None:
        with pytest.raises(PAv1ValidationError):
            validator.validate_lifecycle({"phases": {}})

    def test_step_missing_handler_fails(self, validator: PAv1Validator) -> None:
        with pytest.raises(PAv1ValidationError):
            validator.validate_lifecycle({"phases": {"instantiate": {"steps": [{"name": "lab_resolve"}]}}})


class TestScenarioSchema:
    def test_minimal_scenario_passes(self, validator: PAv1Validator) -> None:
        validator.validate_scenario(
            {
                "name": "lab_resolve",
                "version": "v1",
                "do": [{"resolve": {"call": "cml.lab.resolve@v1"}}],
            }
        )

    def test_scenario_with_complex_tasks_passes(self, validator: PAv1Validator) -> None:
        validator.validate_scenario(
            {
                "name": "lab_provision",
                "version": "v1",
                "do": [
                    {
                        "init": {
                            "set": {"lab_id": ""},
                            "export": {"as": ". + {lab_id}"},
                        }
                    },
                    {
                        "resolve": {
                            "call": "cml.lab.resolve@v1",
                            "with": {"topology": "$context.topology"},
                            "output": {"as": "{lab_id: .id}"},
                            "timeout": {"seconds": 60},
                            "retry": {"attempts": 2, "backoff_seconds": 5},
                        }
                    },
                ],
            }
        )

    def test_scenario_missing_do_fails(self, validator: PAv1Validator) -> None:
        with pytest.raises(PAv1ValidationError):
            validator.validate_scenario({"name": "x", "version": "v1"})

    def test_scenario_task_without_known_key_fails(self, validator: PAv1Validator) -> None:
        with pytest.raises(PAv1ValidationError):
            validator.validate_scenario({"name": "x", "version": "v1", "do": [{"step": {"unknown_key": True}}]})
