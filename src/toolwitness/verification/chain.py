"""Multi-turn chain verification — verify tool-input chains across sequential calls.

When tool B is called, verify its inputs match prior tool A's outputs.
Structured-to-structured comparison for highest ROI, fewest false positives.

Chain breaks are recorded for session timeline visualization.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from toolwitness.core.types import ToolExecution

logger = logging.getLogger("toolwitness")


@dataclass
class ChainLink:
    """A single link in a tool execution chain."""

    tool_name: str
    args: dict[str, Any]
    output: Any
    order: int


@dataclass
class ChainBreak:
    """A detected break in the tool chain — inputs don't match prior outputs."""

    source_tool: str
    target_tool: str
    field: str
    expected: Any
    actual: Any
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_tool": self.source_tool,
            "target_tool": self.target_tool,
            "field": self.field,
            "expected": str(self.expected),
            "actual": str(self.actual),
            "severity": self.severity,
        }


@dataclass
class ChainVerificationResult:
    """Result of verifying a tool execution chain."""

    chain_length: int
    breaks: list[ChainBreak] = field(default_factory=list)
    is_intact: bool = True

    @property
    def break_count(self) -> int:
        return len(self.breaks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_length": self.chain_length,
            "is_intact": self.is_intact,
            "break_count": self.break_count,
            "breaks": [b.to_dict() for b in self.breaks],
        }


def verify_chain(
    executions: list[ToolExecution],
    *,
    strict: bool = False,
) -> ChainVerificationResult:
    """Verify that sequential tool calls form a valid data chain.

    For each pair of consecutive executions (A, B), checks whether B's
    input arguments contain values that appeared in A's output.

    Args:
        executions: Ordered list of tool executions.
        strict: If True, any non-matching input field is a break.
                If False (default), only fields whose values appear in
                prior outputs are checked.
    """
    if len(executions) < 2:
        return ChainVerificationResult(
            chain_length=len(executions), is_intact=True,
        )

    breaks: list[ChainBreak] = []

    for i in range(1, len(executions)):
        prev = executions[i - 1]
        curr = executions[i]

        prev_values = _extract_values(prev.output)
        curr_arg_values = _extract_field_values(curr.args)

        for arg_field, arg_value in curr_arg_values.items():
            matched_source = _find_value_in_output(
                arg_value, prev_values,
            )

            if matched_source is not None:
                continue

            if strict or _value_looks_like_output(arg_value, prev.output):
                breaks.append(ChainBreak(
                    source_tool=prev.tool_name,
                    target_tool=curr.tool_name,
                    field=arg_field,
                    expected=_describe_expected(arg_field, prev.output),
                    actual=arg_value,
                    severity="error" if strict else "warning",
                ))

    return ChainVerificationResult(
        chain_length=len(executions),
        breaks=breaks,
        is_intact=len(breaks) == 0,
    )


def _extract_values(output: Any) -> set[str]:
    """Extract all leaf string and numeric values from a tool output."""
    values: set[str] = set()
    _walk_values(output, values)
    return values


def _walk_values(obj: Any, acc: set[str]) -> None:
    if obj is None:
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _walk_values(v, acc)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _walk_values(item, acc)
    elif isinstance(obj, (int, float)):
        acc.add(str(obj))
        if isinstance(obj, float) and obj == int(obj):
            acc.add(str(int(obj)))
    elif isinstance(obj, str):
        acc.add(obj)
        if obj.strip():
            acc.add(obj.strip())


def _extract_field_values(args: dict[str, Any]) -> dict[str, Any]:
    """Extract field:value pairs from tool arguments, flattening one level."""
    result: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
        elif isinstance(value, dict):
            for k2, v2 in value.items():
                result[f"{key}.{k2}"] = v2
    return result


def _find_value_in_output(
    value: Any, output_values: set[str],
) -> str | None:
    """Check if a value appears in the set of output values."""
    str_val = str(value).strip()
    if str_val in output_values:
        return str_val

    if isinstance(value, (int, float)):
        for ov in output_values:
            try:
                if abs(float(ov) - float(value)) < 0.01:
                    return ov
            except (ValueError, TypeError):
                continue

    return None


def _value_looks_like_output(value: Any, prev_output: Any) -> bool:
    """Heuristic: does this value look like it should come from prior output?

    Returns True if the value is a non-trivial string or number that
    could plausibly be a reference to prior tool data.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str) and len(value) > 3:
        output_str = json.dumps(prev_output, default=str).lower()
        return value.lower() in output_str
    return False


def _describe_expected(field: str, prev_output: Any) -> str:
    """Describe what we expected to find in the prior output for this field."""
    if isinstance(prev_output, dict):
        if field in prev_output:
            return str(prev_output[field])
        for key, val in prev_output.items():
            if field.lower() in key.lower():
                return str(val)
    return f"(value from prior tool output for '{field}')"
