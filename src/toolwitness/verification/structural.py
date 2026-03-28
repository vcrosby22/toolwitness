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


_LONG_TEXT_THRESHOLD = 500


def text_grounding_match(
    source_text: str,
    agent_response: str,
) -> MatchResult:
    """Check if claims in *agent_response* are grounded in *source_text*.

    Reverses the comparison direction of ``structural_match``: instead of
    asking "are tool output values present in the response?", this asks
    "are the response's specific claims supported by the source text?"

    Used for large text outputs (file contents, long descriptions) where
    agents summarise rather than echo the full output.
    """
    result = MatchResult()
    source_lower = source_text.lower()

    # --- 1. Quoted phrases: strongest signal of a specific claim ---
    quoted = re.findall(
        r"""['"\u2018\u2019\u201c\u201d]"""
        r"""([^'"\u2018\u2019\u201c\u201d]{3,}?)"""
        r"""['"\u2018\u2019\u201c\u201d]""",
        agent_response,
    )
    for phrase in quoted:
        phrase_clean = phrase.strip().lower()
        if len(phrase_clean) < 3:
            continue
        if phrase_clean in source_lower:
            result.matched_values.append(
                {"key": "quoted", "expected": phrase.strip(), "found": True}
            )
        else:
            result.mismatched_values.append(
                {"key": "quoted", "expected": phrase.strip(), "found_in_response": False}
            )

    # --- 2. Dates: YYYY-MM-DD, "Month DD YYYY", or "Month YYYY" ---
    date_patterns = re.findall(
        r"\d{4}-\d{2}-\d{2}|"
        r"(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"(?:\s+\d{1,2}[\s,]+\d{4}|\s+\d{4})",
        agent_response,
        re.IGNORECASE,
    )
    for date_str in date_patterns:
        if date_str.lower() in source_lower:
            result.matched_values.append(
                {"key": "date", "expected": date_str, "found": True}
            )
        else:
            result.mismatched_values.append(
                {"key": "date", "expected": date_str, "found_in_response": False}
            )

    # --- 3. Numbers: exact match for large ints (dates, counts) ---
    response_numbers = _extract_numbers(agent_response)
    source_number_set = set(_extract_numbers(source_text))
    for num in response_numbers:
        if abs(num) < 2:
            continue
        if num >= 100:
            if num in source_number_set:
                result.matched_values.append(
                    {"key": "number", "expected": num, "found": True}
                )
            else:
                result.mismatched_values.append(
                    {"key": "number", "expected": num, "found_in_response": False}
                )
        else:
            if any(_numeric_close(num, sn) for sn in source_number_set):
                result.matched_values.append(
                    {"key": "number", "expected": num, "found": True}
                )

    # --- 4. Acronyms (2-5 uppercase letters) ---
    acronyms = set(re.findall(r"\b[A-Z]{2,5}\b", agent_response))
    _COMMON_ACRONYMS = {"THE", "AND", "NOT", "FOR", "BUT", "ARE", "WAS"}
    for acr in acronyms - _COMMON_ACRONYMS:
        if acr.lower() in source_lower or acr in source_text:
            result.matched_values.append(
                {"key": "acronym", "expected": acr, "found": True}
            )
        else:
            result.mismatched_values.append(
                {"key": "acronym", "expected": acr, "found_in_response": False}
            )

    # --- 5. Distinctive content words ---
    response_lower_text = agent_response.lower()
    response_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", response_lower_text))
    source_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", source_lower))
    _STOP = {
        "that", "this", "with", "from", "they", "were", "been", "have",
        "will", "would", "could", "should", "about", "which", "their",
        "there", "when", "what", "some", "also", "each", "into", "more",
        "than", "then", "them", "does", "just", "very", "only", "said",
        "file", "read", "true", "false", "last", "first", "created",
        "contains", "document", "emphasizes", "focuses", "primarily",
        "guiding", "principles",
    }
    content_words = response_words - _STOP
    grounded = content_words & source_words
    ungrounded = content_words - source_words
    if content_words:
        grounding_ratio = len(grounded) / len(content_words)
        if grounding_ratio < 0.5 and len(ungrounded) >= 3:
            for word in sorted(ungrounded)[:5]:
                result.missing_values.append(word)

    return result


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
