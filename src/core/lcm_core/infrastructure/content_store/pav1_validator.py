"""PAv1 JSON Schema validator.

Loads vendored schemas from :mod:`lcm_core.infrastructure.content_store.schemas`
(co-located so the runtime has no dependency on the documentation tree).

See :doc:`docs/architecture/content-format/PAv1.md` §5 for usage rules.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from lcm_core.infrastructure.content_store.pav1_errors import PAv1ValidationError

_SCHEMA_PACKAGE = "lcm_core.infrastructure.content_store.schemas"

_MANIFEST_SCHEMA = "manifest.schema.json"
_LIFECYCLE_SCHEMA = "lifecycle.schema.json"
_SCENARIO_SCHEMA = "scenario.schema.json"


@lru_cache(maxsize=8)
def _load_schema(filename: str) -> dict[str, Any]:
    """Load a vendored JSON schema by filename (cached)."""
    with resources.files(_SCHEMA_PACKAGE).joinpath(filename).open("r", encoding="utf-8") as fp:
        return json.load(fp)


@lru_cache(maxsize=8)
def _validator_for(filename: str) -> Draft202012Validator:
    schema = _load_schema(filename)
    return Draft202012Validator(schema)


def _format_errors(validator: Draft202012Validator, data: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
        messages.append(f"{loc}: {err.message}")
    return messages


class PAv1Validator:
    """Validate PAv1 documents against vendored JSON schemas.

    Each ``validate_*`` method raises :class:`PAv1ValidationError` with the
    full list of schema-validation messages on failure. Methods are stateless
    and safe to call concurrently.
    """

    def validate_manifest(self, data: dict[str, Any]) -> None:
        """Validate a ``manifest.yaml`` payload."""
        self._validate(data, _MANIFEST_SCHEMA, path="manifest.yaml")

    def validate_lifecycle(self, data: dict[str, Any]) -> None:
        """Validate a ``lifecycle.yaml`` payload."""
        self._validate(data, _LIFECYCLE_SCHEMA, path="lifecycle.yaml")

    def validate_scenario(self, data: dict[str, Any]) -> None:
        """Validate a ``scenarios/<name>.<version>.yaml`` payload."""
        self._validate(data, _SCENARIO_SCHEMA, path="scenarios/*.yaml")

    @staticmethod
    def _validate(data: Any, schema_filename: str, *, path: str) -> None:
        if not isinstance(data, dict):
            raise PAv1ValidationError(path, [f"<root>: expected an object, got {type(data).__name__}"])
        validator = _validator_for(schema_filename)
        errors = _format_errors(validator, data)
        if errors:
            raise PAv1ValidationError(path, errors)
