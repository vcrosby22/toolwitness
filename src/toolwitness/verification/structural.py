"""JSON structural matching for response verification.

Extracts values from agent response text and checks them against actual tool
output. Handles nested JSON, fuzzy numeric comparison, and partial matches.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MatchResult:
    """Result of comparing agent claims against tool output."""

    matched_values: list[dict[str, Any]] = field(default_factory=list)
    mismatched_values: list[dict[str, Any]] = field(default_factory=list)
    extra_claims: list[dict[str, Any]] = field(default_factory=list)
    missing_values: list[str] = field(default_factory=list)

    @property
    def total_checked(self) -> int:
        return len(self.matched_values) + len(self.mismatched_values)

    @property
    def match_ratio(self) -> float:
        if self.total_checked == 0:
            return 0.0
        return len(self.matched_values) / self.total_checked

    @property
    def has_extra_claims(self) -> bool:
        return len(self.extra_claims) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched_values,
            "mismatched": self.mismatched_values,
            "extra_claims": self.extra_claims,
            "missing": self.missing_values,
            "match_ratio": self.match_ratio,
        }


def _flatten_dict(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict into dot-notation keys."""
    items: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.update(_flatten_dict(value, full_key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    items.update(_flatten_dict(item, f"{full_key}[{i}]"))
                else:
                    items[f"{full_key}[{i}]"] = item
        else:
            items[full_key] = value
    return items


def _numeric_close(a: Any, b: Any, tolerance: float = 0.05) -> bool:
    """Check if two values are numerically close (within tolerance ratio)."""
    try:
        fa, fb = float(a), float(b)
    except (ValueError, TypeError):
        return False
    if fb == 0:
        return fa == 0
    return abs(fa - fb) / max(abs(fb), 1e-9) <= tolerance


def _extract_numbers(text: str) -> list[float]:
    """Extract all numeric values from text."""
    pattern = r"-?\d+\.?\d*"
    return [float(m) for m in re.findall(pattern, text)]


def _extract_strings(text: str, candidates: list[str]) -> list[str]:
    """Find which candidate strings appear in text (case-insensitive)."""
    text_lower = text.lower()
    return [c for c in candidates if str(c).lower() in text_lower]


def _extract_json_from_text(text: str) -> list[dict[str, Any]]:
    """Attempt to extract JSON objects embedded in text."""
    results = []
    for match in re.finditer(r"\{[^{}]*\}", text):
        try:
            results.append(json.loads(match.group()))
        except json.JSONDecodeError:
            continue
    return results


def structural_match(
    tool_output: Any,
    agent_response: str,
    *,
    numeric_tolerance: float = 0.05,
) -> MatchResult:
    """Compare agent response text against actual tool output.

    Args:
        tool_output: The actual return value from the tool.
        agent_response: The agent's text response claiming to describe tool output.
        numeric_tolerance: Relative tolerance for numeric comparison (default 5%).

    Returns:
        MatchResult with matched, mismatched, extra claims, and missing values.
    """
    result = MatchResult()

    if tool_output is None:
        return result

    if isinstance(tool_output, dict):
        flat = _flatten_dict(tool_output)
    elif isinstance(tool_output, list):
        flat = {f"[{i}]": v for i, v in enumerate(tool_output)}
    else:
        flat = {"_value": tool_output}

    response_lower = agent_response.lower()
    response_numbers = _extract_numbers(agent_response)

    for key, value in flat.items():
        if isinstance(value, (int, float)):
            matched = any(_numeric_close(value, n, numeric_tolerance) for n in response_numbers)
            if matched:
                result.matched_values.append({"key": key, "expected": value, "found": True})
            else:
                str_value = str(value)
                if str_value in agent_response:
                    result.matched_values.append({"key": key, "expected": value, "found": True})
                elif response_numbers:
                    # Response has numbers but none match this value → contradiction
                    result.mismatched_values.append({
                        "key": key,
                        "expected": value,
                        "found_in_response": False,
                        "response_numbers": response_numbers[:5],
                    })
                else:
                    # No numbers in response at all → simple omission
                    result.missing_values.append(key)

        elif isinstance(value, bool):
            bool_str = str(value).lower()
            if bool_str in response_lower:
                result.matched_values.append({"key": key, "expected": value, "found": True})
            else:
                result.missing_values.append(key)

        elif isinstance(value, str):
            if value.lower() in response_lower:
                result.matched_values.append({"key": key, "expected": value, "found": True})
            else:
                result.missing_values.append(key)

        elif value is None:
            continue

    embedded_json = _extract_json_from_text(agent_response)
    if isinstance(tool_output, dict):
        tool_keys = set(_flatten_dict(tool_output).keys())
        for obj in embedded_json:
            for key in _flatten_dict(obj):
                if key not in tool_keys:
                    result.extra_claims.append({
                        "key": key,
                        "value": _flatten_dict(obj)[key],
                        "source": "json_in_response",
                    })

    return result
