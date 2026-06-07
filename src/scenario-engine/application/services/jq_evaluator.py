"""jq Expression Evaluator — resolves ${ expr } expressions in DSL documents.

Supports the LCM DSL strict mode: only strings wrapped in ${ } are evaluated.
All other values are passed through as literals.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import jq

logger = logging.getLogger(__name__)

# Pattern to match DSL jq expressions: ${ ... }
_JQ_EXPR_PATTERN = re.compile(r"^\$\{\s*(.+?)\s*\}$", re.DOTALL)


class JqEvaluationError(Exception):
    """Raised when a jq expression evaluation fails."""

    def __init__(self, expression: str, detail: str, instance: str = "") -> None:
        self.expression = expression
        self.detail = detail
        self.instance = instance
        super().__init__(f"jq evaluation failed: {detail} (expr: {expression})")


def is_expression(value: Any) -> bool:
    """Check if a value is a jq expression (string matching ${ ... })."""
    if not isinstance(value, str):
        return False
    return _JQ_EXPR_PATTERN.match(value) is not None


def extract_expression(value: str) -> str | None:
    """Extract the jq expression from a ${ ... } wrapper, or None."""
    match = _JQ_EXPR_PATTERN.match(value)
    return match.group(1) if match else None


def evaluate(expression: str, data: Any, variables: dict[str, Any] | None = None) -> Any:
    """Evaluate a jq expression against input data with optional variables.

    Args:
        expression: Raw jq expression (without ${ } wrapper).
        data: The input data (typically $output or $input).
        variables: Additional named variables (e.g. $context, $item, $index).

    Returns:
        The evaluation result (first match).

    Raises:
        JqEvaluationError: If the expression is invalid or evaluation fails.
    """
    try:
        # Build jq args dict for named variables
        args = {}
        if variables:
            for key, val in variables.items():
                # jq library uses kwargs for --argjson
                if isinstance(val, (dict, list, int, float, bool)) or val is None:
                    args[key] = val
                else:
                    # Convert non-JSON-native types to string
                    args[key] = str(val)

        # Compile and run
        program = jq.compile(expression, args=args)
        results = program.input(data).all()

        if not results:
            return None
        if len(results) == 1:
            return results[0]
        return results

    except ValueError as e:
        raise JqEvaluationError(expression=expression, detail=str(e)) from e
    except Exception as e:
        raise JqEvaluationError(expression=expression, detail=str(e)) from e


def resolve_value(value: Any, data: Any, variables: dict[str, Any] | None = None) -> Any:
    """Resolve a value — if it's a jq expression, evaluate it; otherwise return as-is.

    Args:
        value: The value to potentially resolve. Only strings matching ${ } are evaluated.
        data: Input data for expression evaluation.
        variables: Runtime variables ($context, $input, $output, etc.).

    Returns:
        Resolved value.
    """
    if not isinstance(value, str):
        return value

    expr = extract_expression(value)
    if expr is None:
        return value  # Literal string

    return evaluate(expr, data, variables)


def resolve_object(obj: dict[str, Any], data: Any, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve all values in an object (shallow — one level of ${ } evaluation).

    Args:
        obj: Dictionary with potentially expression values.
        data: Input data for expression evaluation.
        variables: Runtime variables.

    Returns:
        Dictionary with expressions resolved.
    """
    resolved = {}
    for key, value in obj.items():
        resolved[key] = resolve_value(value, data, variables)
    return resolved
