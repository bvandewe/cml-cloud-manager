"""Pipeline Template Resolver — template merging for pipeline definitions.

ADR-038 Phase 3: Resolves ``extends`` references in pipeline definitions.
Templates are standard pipelines defined once; definitions customize via
``insert_after``, ``insert_before``, ``overrides``, and ``remove``.

Usage::

    resolver = PipelineTemplateResolver()
    resolved = resolver.resolve(pipeline_def)  # expands extends/insert/override

If ``extends`` is not present, the pipeline is returned as-is (backward compat).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Standard Pipeline Templates
# ---------------------------------------------------------------------------
# Templates are defined as Python dicts to avoid file I/O at startup.
# They follow the same schema as inline pipeline definitions in YAML.

_TEMPLATES: dict[str, dict[str, Any]] = {
    "standard-instantiate": {
        "description": "Standard lab instantiation pipeline — import/reuse lab, allocate ports, provision LDS, mark ready.",
        "trigger": "on_status:instantiating",
        "max_retries": 3,
        "retry_backoff": 30,
        "steps": [
            {
                "name": "lab_resolve",
                "handler": "lab_resolve",
                "description": "Import or reuse a CML lab on the assigned worker",
                "timeout_seconds": 120,
                "retry": {"max_attempts": 2, "delay_seconds": 10},
            },
            {
                "name": "ports_alloc",
                "handler": "ports_alloc",
                "description": "Allocate real ports from worker pool for console access",
                "needs": ["lab_resolve"],
                "skip_when": "not $DEFINITION.port_template",
                "timeout_seconds": 30,
            },
            {
                "name": "tags_sync",
                "handler": "tags_sync",
                "description": "Write protocol:port tags to CML nodes",
                "needs": ["ports_alloc"],
                "skip_when": "not $DEFINITION.port_template",
                "timeout_seconds": 30,
            },
            {
                "name": "lab_binding",
                "handler": "lab_binding",
                "description": "Bind LabRecord to session, create LabRunRecord",
                "needs": ["lab_resolve", "tags_sync"],
                "timeout_seconds": 30,
            },
            {
                "name": "lab_start",
                "handler": "lab_start",
                "description": "Start the CML lab and wait for convergence",
                "needs": ["lab_binding"],
                "timeout_seconds": 300,
                "retry": {"max_attempts": 5, "delay_seconds": 15},
            },
            {
                "name": "lds_provision",
                "handler": "lds_provision",
                "description": "Create LDS session, map devices, get launch URL",
                "needs": ["lab_start"],
                "skip_when": "not $DEFINITION.form_qualified_name",
                "timeout_seconds": 60,
            },
            {
                "name": "mark_ready",
                "handler": "mark_ready",
                "description": "Atomic transition to READY status",
                "needs": ["lab_start", "lds_provision"],
                "timeout_seconds": 10,
            },
        ],
        "outputs": {
            "cml_lab_id": "$STEPS.lab_resolve.cml_lab_id",
            "lab_record_id": "$STEPS.lab_resolve.lab_record_id",
            "user_session_id": "$STEPS.lds_provision.user_session_id",
            "launch_url": "$STEPS.lds_provision.launch_url",
        },
    },
    "standard-teardown": {
        "description": "Standard teardown pipeline — stop lab, deregister LDS, wipe, archive.",
        "trigger": "on_status:stopping",
        "steps": [
            {
                "name": "stop_lab",
                "handler": "stop_lab",
                "description": "Stop the CML lab (graceful shutdown)",
                "timeout_seconds": 120,
            },
            {
                "name": "deregister_lds",
                "handler": "deregister_lds",
                "description": "Close the LDS session and release license",
                "needs": ["stop_lab"],
                "skip_when": "not $SESSION.user_session_id",
                "optional": True,
                "timeout_seconds": 30,
            },
            {
                "name": "wipe_lab",
                "handler": "wipe_lab",
                "description": "Wipe lab state (reset to DEFINED_ON_CORE)",
                "needs": ["stop_lab"],
                "timeout_seconds": 120,
            },
            {
                "name": "archive",
                "handler": "archive",
                "description": "Archive session record and transition to ARCHIVED",
                "needs": ["wipe_lab", "deregister_lds"],
                "timeout_seconds": 10,
            },
        ],
        "outputs": {
            "archived_at": "$STEPS.archive.archived_at",
        },
    },
    "standard-collect-evidence": {
        "description": "Standard evidence collection pipeline.",
        "trigger": "on_status:collecting",
        "steps": [
            {
                "name": "capture_configs",
                "handler": "capture_configs",
                "description": "Export running-config from all managed devices",
                "timeout_seconds": 120,
            },
            {
                "name": "capture_screenshots",
                "handler": "capture_screenshots",
                "description": "Capture VNC screenshots of graphical nodes",
                "needs": ["capture_configs"],
                "optional": True,
                "timeout_seconds": 60,
            },
            {
                "name": "export_pcaps",
                "handler": "export_pcaps",
                "description": "Export packet capture files from bridge interfaces",
                "needs": ["capture_configs"],
                "optional": True,
                "timeout_seconds": 60,
            },
            {
                "name": "package_evidence",
                "handler": "package_evidence",
                "description": "Bundle all artifacts into a compressed evidence package",
                "needs": ["capture_configs"],
                "timeout_seconds": 30,
            },
        ],
        "outputs": {
            "evidence_uri": "$STEPS.package_evidence.evidence_uri",
        },
    },
    "standard-compute-grading": {
        "description": "Standard grading pipeline.",
        "trigger": "on_status:grading",
        "steps": [
            {
                "name": "load_rubric",
                "handler": "load_rubric",
                "description": "Load grading rules from definition (grade.xml)",
                "timeout_seconds": 30,
            },
            {
                "name": "evaluate",
                "handler": "evaluate",
                "description": "Run grading engine against evidence and rubric",
                "needs": ["load_rubric"],
                "timeout_seconds": 120,
            },
            {
                "name": "record_score",
                "handler": "record_score",
                "description": "Create ScoreReport aggregate and store results",
                "needs": ["evaluate"],
                "timeout_seconds": 10,
            },
        ],
        "outputs": {
            "score": "$STEPS.evaluate.score",
            "score_report_id": "$STEPS.record_score.score_report_id",
        },
    },
}


class PipelineTemplateError(Exception):
    """Raised when template resolution fails."""


class PipelineTemplateResolver:
    """Resolves pipeline template references to concrete pipeline definitions.

    Supports the following customization operators:

    - ``extends``: Name of the base template to start from
    - ``insert_after.<step>``: List of steps to inject after the named step
    - ``insert_before.<step>``: List of steps to inject before the named step
    - ``overrides.<step>``: Dict of fields to merge into the named step
    - ``remove``: List of step names to remove from the base

    If ``extends`` is not present, the pipeline definition is returned as-is
    (backward compatibility with current inline definitions).
    """

    def __init__(self, extra_templates: dict[str, dict[str, Any]] | None = None) -> None:
        """Initialize with optional additional templates.

        Args:
            extra_templates: Additional templates to register beyond the built-in ones.
        """
        self._templates = dict(_TEMPLATES)
        if extra_templates:
            self._templates.update(extra_templates)

    def resolve(self, pipeline_def: dict[str, Any]) -> dict[str, Any]:
        """Resolve a pipeline definition, expanding template references.

        Args:
            pipeline_def: Pipeline definition dict, potentially with ``extends``.

        Returns:
            Fully-resolved pipeline definition (same schema as inline).

        Raises:
            PipelineTemplateError: If the referenced template is unknown.
        """
        extends = pipeline_def.get("extends")
        if not extends:
            # No template reference — return as-is (backward compat)
            return pipeline_def

        # Load base template (deep copy to avoid mutation)
        base = self._load_template(extends)

        # Apply customization operators in order
        resolved = self._apply_removes(base, pipeline_def)
        resolved = self._apply_inserts_before(resolved, pipeline_def)
        resolved = self._apply_inserts_after(resolved, pipeline_def)
        resolved = self._apply_overrides(resolved, pipeline_def)

        # Copy over top-level fields from the customization (description, max_retries, etc.)
        for key in ("description", "trigger", "max_retries", "retry_backoff"):
            if key in pipeline_def:
                resolved[key] = pipeline_def[key]

        # Merge outputs (customization can add/override output expressions)
        if "outputs" in pipeline_def:
            resolved.setdefault("outputs", {})
            resolved["outputs"].update(pipeline_def["outputs"])

        return resolved

    def get_template_names(self) -> list[str]:
        """Return the names of all registered templates."""
        return list(self._templates.keys())

    def _load_template(self, name: str) -> dict[str, Any]:
        """Load a template by name (deep copy).

        Args:
            name: Template name (e.g. "standard-instantiate").

        Returns:
            Deep copy of the template definition.

        Raises:
            PipelineTemplateError: If the template name is unknown.
        """
        template = self._templates.get(name)
        if template is None:
            available = ", ".join(sorted(self._templates.keys()))
            raise PipelineTemplateError(f"Unknown pipeline template: '{name}'. Available: {available}")
        return copy.deepcopy(template)

    def _apply_removes(self, base: dict[str, Any], customization: dict[str, Any]) -> dict[str, Any]:
        """Remove steps listed in ``remove``.

        Args:
            base: Base pipeline definition (mutated).
            customization: Customization dict with optional ``remove`` list.

        Returns:
            Modified base.
        """
        removals = customization.get("remove", [])
        if not removals:
            return base

        steps = base.get("steps", [])
        base["steps"] = [s for s in steps if s["name"] not in removals]

        removed_set = set(removals)
        logger.debug("Template: removed steps %s", removed_set)
        return base

    def _apply_inserts_after(self, base: dict[str, Any], customization: dict[str, Any]) -> dict[str, Any]:
        """Insert steps after named anchor steps.

        ``insert_after`` is a dict mapping anchor step name → list of new steps.

        Args:
            base: Base pipeline definition (mutated).
            customization: Customization dict with optional ``insert_after``.

        Returns:
            Modified base.
        """
        inserts = customization.get("insert_after", {})
        if not inserts:
            return base

        steps = base.get("steps", [])
        for anchor_name, new_steps in inserts.items():
            anchor_idx = self._find_step_index(steps, anchor_name)
            if anchor_idx is None:
                raise PipelineTemplateError(f"insert_after: anchor step '{anchor_name}' not found in template")
            # Insert after the anchor (reverse order to maintain list order)
            for i, new_step in enumerate(reversed(new_steps)):
                steps.insert(anchor_idx + 1, copy.deepcopy(new_step))
            logger.debug("Template: inserted %d steps after '%s'", len(new_steps), anchor_name)

        base["steps"] = steps
        return base

    def _apply_inserts_before(self, base: dict[str, Any], customization: dict[str, Any]) -> dict[str, Any]:
        """Insert steps before named anchor steps.

        ``insert_before`` is a dict mapping anchor step name → list of new steps.

        Args:
            base: Base pipeline definition (mutated).
            customization: Customization dict with optional ``insert_before``.

        Returns:
            Modified base.
        """
        inserts = customization.get("insert_before", {})
        if not inserts:
            return base

        steps = base.get("steps", [])
        for anchor_name, new_steps in inserts.items():
            anchor_idx = self._find_step_index(steps, anchor_name)
            if anchor_idx is None:
                raise PipelineTemplateError(f"insert_before: anchor step '{anchor_name}' not found in template")
            for i, new_step in enumerate(new_steps):
                steps.insert(anchor_idx + i, copy.deepcopy(new_step))
            logger.debug("Template: inserted %d steps before '%s'", len(new_steps), anchor_name)

        base["steps"] = steps
        return base

    def _apply_overrides(self, base: dict[str, Any], customization: dict[str, Any]) -> dict[str, Any]:
        """Override fields in existing steps.

        ``overrides`` is a dict mapping step name → dict of fields to merge.

        Args:
            base: Base pipeline definition (mutated).
            customization: Customization dict with optional ``overrides``.

        Returns:
            Modified base.
        """
        overrides = customization.get("overrides", {})
        if not overrides:
            return base

        steps = base.get("steps", [])
        for step_name, override_fields in overrides.items():
            step_idx = self._find_step_index(steps, step_name)
            if step_idx is None:
                raise PipelineTemplateError(f"overrides: step '{step_name}' not found in template")
            steps[step_idx].update(override_fields)
            logger.debug("Template: overrode fields %s on step '%s'", list(override_fields.keys()), step_name)

        base["steps"] = steps
        return base

    @staticmethod
    def _find_step_index(steps: list[dict[str, Any]], name: str) -> int | None:
        """Find the index of a step by name.

        Args:
            steps: List of step definitions.
            name: Step name to find.

        Returns:
            Index of the step, or None if not found.
        """
        for i, step in enumerate(steps):
            if step.get("name") == name:
                return i
        return None
