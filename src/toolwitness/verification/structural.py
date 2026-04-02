"""JSON structural matching for response verification.

Extracts values from agent response text and checks them against actual tool
output. Handles nested JSON, fuzzy numeric comparison, and partial matches.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MatchResult:
    """Result of comparing agent claims against tool output."""

    matched_values: list[dict[str, Any]] = field(default_factory=list)
    mismatched_values: list[dict[str, Any]] = field(default_factory=list)
    extra_claims: list[dict[str, Any]] = field(default_factory=list)
    missing_values: list[str] = field(default_factory=list)
    substituted_values: list[dict[str, Any]] = field(default_factory=list)

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
            "substituted": self.substituted_values,
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
    """Check if two values are numerically close.

    Uses adaptive tolerance based on magnitude:
      - |value| >= 100: relative tolerance (default 5%) — rounding expected
      - 10 <= |value| < 100: absolute +/- 1 — small ints like temperatures
      - |value| < 10: absolute +/- 0.1 — counts, die rolls, small measures
    """
    try:
        fa, fb = float(a), float(b)
    except (ValueError, TypeError):
        return False
    if fb == 0:
        return fa == 0

    magnitude = max(abs(fa), abs(fb))
    if magnitude < 10:
        return abs(fa - fb) <= 0.1
    if magnitude < 100:
        return abs(fa - fb) <= 1.0
    return abs(fa - fb) / max(abs(fb), 1e-9) <= tolerance


_CONVERSIONS: list[tuple[str, Callable[[float], float]]] = [
    ("F_to_C", lambda x: (x - 32) * 5 / 9),
    ("C_to_F", lambda x: x * 9 / 5 + 32),
    ("mi_to_km", lambda x: x * 1.60934),
    ("km_to_mi", lambda x: x / 1.60934),
    ("lb_to_kg", lambda x: x * 0.453592),
    ("kg_to_lb", lambda x: x / 0.453592),
    ("in_to_cm", lambda x: x * 2.54),
    ("cm_to_in", lambda x: x / 2.54),
    ("ft_to_m", lambda x: x * 0.3048),
    ("m_to_ft", lambda x: x / 0.3048),
]


def _conversion_close(
    tool_val: float, response_val: float, tolerance: float = 0.05,
) -> bool:
    """Check if *response_val* is a common unit conversion of *tool_val*.

    Tries each conversion in both directions (the table stores both).
    Returns True if any conversion brings the values within *tolerance*.
    """
    for _name, convert in _CONVERSIONS:
        try:
            converted = convert(tool_val)
            denom = max(abs(response_val), 1e-9)
            if abs(converted - response_val) / denom <= tolerance:
                return True
        except (ValueError, ZeroDivisionError):
            continue
    return False


_MAGNITUDE_SCALES: list[tuple[float, frozenset[str]]] = [
    (1_000,         frozenset({"k", "thousand"})),
    (1_000_000,     frozenset({"m", "million", "mm"})),
    (1_000_000_000, frozenset({"b", "billion", "bn"})),
    (1024,          frozenset({"kb", "kib"})),
    (1024**2,       frozenset({"mb", "mib"})),
    (1024**3,       frozenset({"gb", "gib"})),
]

_ALL_MAGNITUDE_LABELS: frozenset[str] = frozenset().union(
    *(labels for _, labels in _MAGNITUDE_SCALES)
)


def _magnitude_close(
    tool_val: float,
    response_val: float,
    tolerance: float = 0.012,
    response_context: str = "",
) -> bool:
    """Check if *response_val* is a scaled version of *tool_val*.

    Handles human-readable abbreviations like 1500000 → "1.5 million"
    or 8192 → "8 KB" (base-1024).

    When *response_context* is provided (lowercase text surrounding the
    response number), the function verifies that any unit label present
    is consistent with the matching scale factor.  This prevents matching
    4096 → "4 MB" (4096/1024=4, but the response says MB not KB).
    """
    if tool_val == 0:
        return False
    ctx_lower = response_context.lower() if response_context else ""
    for scale, labels in _MAGNITUDE_SCALES:
        scaled = tool_val / scale
        denom = max(abs(response_val), 1e-9)
        if abs(scaled - response_val) / denom <= tolerance:
            if ctx_lower:
                ctx_labels = {
                    lbl for lbl in _ALL_MAGNITUDE_LABELS
                    if re.search(rf"\b{re.escape(lbl)}\b", ctx_lower)
                }
                if ctx_labels and not (ctx_labels & labels):
                    continue
            return True
    return False


def _extract_numbers(text: str) -> list[float]:
    """Extract all numeric values from text, handling comma-separated thousands.

    Matches numbers like ``29,931`` or ``1,234,567.89`` as single values
    by stripping commas before conversion.  Plain numbers (``42``,
    ``3.14``) are matched as before.
    """
    # First alternative: numbers with at least one comma-thousands group
    # Second alternative: plain numbers (integer or decimal)
    pattern = r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+\.?\d*"
    return [float(m.replace(",", "")) for m in re.findall(pattern, text)]


def _extract_strings(text: str, candidates: list[str]) -> list[str]:
    """Find which candidate strings appear in text (case-insensitive)."""
    text_lower = text.lower()
    return [c for c in candidates if str(c).lower() in text_lower]


_MONTH_ABBREV: dict[str, str] = {
    "jan": "january", "feb": "february", "mar": "march",
    "apr": "april", "jun": "june", "jul": "july",
    "aug": "august", "sep": "september", "oct": "october",
    "nov": "november", "dec": "december",
}
_MONTH_ABBREV_RE = re.compile(
    r"\b(" + "|".join(_MONTH_ABBREV) + r")\b", re.IGNORECASE,
)


def _normalize_months(text: str) -> str:
    """Expand 3-letter month abbreviations to full names (case-preserving)."""
    def _repl(m: re.Match[str]) -> str:
        abbr = m.group(1)
        full = _MONTH_ABBREV[abbr.lower()]
        return full.capitalize() if abbr[0].isupper() else full
    return _MONTH_ABBREV_RE.sub(_repl, text)


_STATUS_SEMANTICS: dict[int, list[str]] = {
    0: ["success", "succeeded", "passed", "ok", "no error"],
    1: ["fail", "error"],
    200: ["successful", "success", "ok", "succeeded"],
    201: ["created"],
    204: ["no content", "empty"],
    301: ["moved", "redirect"],
    400: ["bad request", "invalid"],
    401: ["unauthorized", "not authorized", "authentication"],
    403: ["forbidden", "access denied"],
    404: ["not found", "missing", "does not exist"],
    500: ["server error", "internal error"],
    502: ["bad gateway"],
    503: ["unavailable", "service unavailable"],
}


def _is_empty_output(flat: dict[str, Any]) -> bool:
    """True if every value in the flattened output is empty/zero/null."""
    for v in flat.values():
        if v is None:
            continue
        if isinstance(v, bool) and v is False:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0:
            continue
        if isinstance(v, str) and v == "":
            continue
        if isinstance(v, list) and len(v) == 0:
            continue
        return False
    return len(flat) > 0


_EMPTY_PATTERNS = re.compile(
    r"\bno\s+results?\b|\bempty\b|\bnothing\b|\bnone\b|\bzero\b|\bnot\s+found\b",
    re.IGNORECASE,
)


def _extract_json_from_text(text: str) -> list[dict[str, Any]]:
    """Attempt to extract JSON objects embedded in text."""
    results = []
    for match in re.finditer(r"\{[^{}]*\}", text):
        try:
            results.append(json.loads(match.group()))
        except json.JSONDecodeError:
            continue
    return results


def _count_line_prefixes(text: str) -> dict[str, int]:
    """Count repeated bracketed line prefixes like ``[FILE]``, ``[DIR]``."""
    counts: dict[str, int] = {}
    for m in re.findall(r"^\[([A-Z]+)\]", text, re.MULTILINE):
        counts[m] = counts.get(m, 0) + 1
    return counts


_LONG_TEXT_THRESHOLD = 500
_MAX_QUOTE_VERIFY_LEN = 100

_LIST_ITEM_RE = re.compile(r"(.+\[\d+\])(?:\..+)?$")


def _list_item_prefix(key: str) -> str | None:
    """Extract list-item group prefix, e.g. ``'results[0]'`` from ``'results[0].city'``."""
    m = _LIST_ITEM_RE.match(key)
    return m.group(1) if m else None


def _value_present(
    value: Any,
    response_lower: str,
    response_numbers: list[float],
    numeric_tolerance: float,
) -> bool:
    """Quick presence check — does *value* appear anywhere in the response?"""
    if isinstance(value, (int, float)):
        return (
            any(_numeric_close(value, n, numeric_tolerance) for n in response_numbers)
            or str(value) in response_lower
        )
    if isinstance(value, bool):
        return str(value).lower() in response_lower
    if isinstance(value, str):
        return value.lower() in response_lower
    return False


# Common sentence-starter words that should not be treated as proper nouns
_COMMON_TITLE: set[str] = {
    "The", "This", "That", "When", "Where", "What", "How", "Yes", "Not",
    "Also", "About", "After", "Before", "Because", "Between", "Both",
    "During", "Each", "Even", "From", "Have", "Into", "Just", "Most",
    "Only", "Over", "Such", "Than", "Then", "Through", "Under", "Very",
    "With", "Would", "Could", "Should", "Found", "Based", "Using",
}
_COMMON_UPPER: set[str] = {
    "THE", "AND", "NOT", "FOR", "BUT", "ARE", "WAS", "HAS", "HAD",
    "HIS", "HER", "ITS",
}


def _detect_substitution(
    missing_value: str,
    response: str,
    all_tool_str_values: set[str],
) -> str | None:
    """Detect if a missing string value was replaced by a different entity.

    Uses two strategies:
    - Multi-word values: token-swap detection (same surrounding tokens,
      different middle token).
    - Single-word proper nouns: check for capitalized words / acronyms in
      the response that are not among the tool output values.

    Returns the detected substitute string, or None.
    """
    if len(missing_value) > 50:
        return None

    missing_lower = missing_value.lower()
    response_lower = response.lower()
    tool_values_lower = {v.lower() for v in all_tool_str_values}

    # --- Strategy 1: multi-word token-swap ("Mar 28 2026" → "Mar 15 2026") ---
    tokens = missing_lower.split()
    if len(tokens) >= 2:
        for i, token in enumerate(tokens):
            others = tokens[:i] + tokens[i + 1:]
            if not all(t in response_lower for t in others):
                continue
            before = tokens[:i]
            after = tokens[i + 1:]
            if before and after:
                pat = (
                    re.escape(" ".join(before))
                    + r"\s+(\S+)\s+"
                    + re.escape(" ".join(after))
                )
            elif before:
                pat = re.escape(" ".join(before)) + r"\s+(\S+)"
            else:
                pat = r"(\S+)\s+" + re.escape(" ".join(after))
            m = re.search(pat, response_lower)
            if m and m.group(1) != token:
                full = m.group(0)
                if full not in tool_values_lower:
                    return full
        return None

    # --- Strategy 2: single-word proper-noun replacement ("Miami" → "NYC") ---
    if not any(c.isupper() for c in missing_value):
        return None

    # Skip technical format strings (timestamps, UUIDs, URLs) that happen
    # to contain uppercase letters (e.g. "2026-03-28T14:30:00Z").
    alpha_chars = sum(c.isalpha() for c in missing_value)
    if alpha_chars < max(len(missing_value) * 0.5, 2):
        return None

    title_words = set(re.findall(r"\b[A-Z][a-z]{2,}\b", response))
    acronyms = set(re.findall(r"\b[A-Z]{2,5}\b", response))

    # Short all-caps values (codes like "USD", "API") should only match
    # other acronyms, not regular title-case words.
    if missing_value.isupper() and len(missing_value) <= 5:
        candidates = acronyms - _COMMON_UPPER
    else:
        candidates = (title_words - _COMMON_TITLE) | (acronyms - _COMMON_UPPER)

    for v in all_tool_str_values:
        v_low = v.lower()
        candidates = {
            c for c in candidates
            if c.lower() not in v_low and v_low not in c.lower()
        }

    return sorted(candidates)[0] if candidates else None


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
    # Strip English contractions before matching so apostrophes in words
    # like "Here's", "don't", "we're" aren't treated as quote delimiters.
    _contraction_stripped = re.sub(
        r"(?<=[a-zA-Z])'(?:s|t|re|ve|ll|d|m)\b", "", agent_response,
    )
    quoted = re.findall(
        r"""['"\u2018\u2019\u201c\u201d]"""
        r"""([^'"\u2018\u2019\u201c\u201d]{3,}?)"""
        r"""['"\u2018\u2019\u201c\u201d]""",
        _contraction_stripped,
    )
    for phrase in quoted:
        phrase_clean = phrase.strip().lower()
        if len(phrase_clean) < 3:
            continue
        if len(phrase_clean) > _MAX_QUOTE_VERIFY_LEN:
            continue
        if phrase_clean in source_lower:
            result.matched_values.append(
                {"key": "quoted", "expected": phrase.strip(), "found": True}
            )
        else:
            result.mismatched_values.append(
                {"key": "quoted", "expected": phrase.strip(), "found_in_response": False}
            )

    # --- 1b. Backtick-quoted code terms (file names, identifiers) ---
    backtick_terms = re.findall(r"`([^`]{2,}?)`", agent_response)
    for term in backtick_terms:
        term_clean = term.strip().lower()
        if len(term_clean) < 2:
            continue
        if term_clean in source_lower:
            result.matched_values.append(
                {"key": "backtick", "expected": term.strip(), "found": True}
            )
        else:
            result.mismatched_values.append(
                {"key": "backtick", "expected": term.strip(), "found_in_response": False}
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
    source_months_normalized = _normalize_months(source_lower).replace(",", "")
    for date_str in date_patterns:
        date_lower = date_str.lower()
        date_norm = _normalize_months(date_lower).replace(",", "")
        if date_lower in source_lower or date_norm in source_months_normalized:
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

    # --- 4b. Derived counts from repeated line patterns ---
    prefix_counts = _count_line_prefixes(source_text)
    for prefix, count in prefix_counts.items():
        if count >= 2:
            for num in response_numbers:
                if _numeric_close(count, num, 0.01):
                    result.matched_values.append(
                        {"key": f"count({prefix})", "expected": count, "found": True},
                    )
                    break

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
        if grounding_ratio >= 0.7 and len(result.mismatched_values) == 0:
            result.matched_values.append({
                "key": "content_grounding",
                "expected": f"{len(grounded)}/{len(content_words)} words grounded",
                "found": True,
                "grounding_ratio": round(grounding_ratio, 2),
            })
        elif grounding_ratio < 0.5 and len(ungrounded) >= 3:
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

    # --- Empty output recognition ---
    # When all values are empty/zero/null and the response acknowledges
    # emptiness, synthesize a match rather than falling through to FABRICATED.
    if _is_empty_output(flat) and _EMPTY_PATTERNS.search(agent_response):
        result.matched_values.append({
            "key": "_empty_output",
            "expected": "empty/zero",
            "found": True,
        })
        return result

    response_lower = agent_response.lower()
    response_numbers = _extract_numbers(agent_response)

    # --- BUG-02 fix: partition list-item groups from non-list items ---
    # When a tool returns a list of objects (e.g. 5 cities), and the agent
    # mentions only 2, the 3 absent items are omissions not contradictions.
    list_groups: dict[str, list[tuple[str, Any]]] = {}
    non_list_items: list[tuple[str, Any]] = []

    for key, value in flat.items():
        prefix = _list_item_prefix(key)
        if prefix is not None:
            list_groups.setdefault(prefix, []).append((key, value))
        else:
            non_list_items.append((key, value))

    items_to_check: list[tuple[str, Any]] = list(non_list_items)
    for _prefix, group in list_groups.items():
        group_present = any(
            _value_present(v, response_lower, response_numbers, numeric_tolerance)
            for _k, v in group
            if v is not None
        )
        if group_present:
            items_to_check.extend(group)
        else:
            for k, _v in group:
                result.missing_values.append(k)

    # Collect all string values from tool output for substitution detection
    all_tool_str_values = {v for v in flat.values() if isinstance(v, str)}

    # --- Per-value matching ---
    # NOTE: bool check must come before (int, float) because Python's
    # bool is a subclass of int — isinstance(True, int) is True.
    for key, value in items_to_check:
        if isinstance(value, bool):
            bool_str = str(value).lower()
            if bool_str in response_lower or value is True and re.search(
                r"\byes\b|\bavailable\b|\benabled\b|\bactive\b", response_lower,
            ) or value is False and re.search(
                r"\bnot\b|\bunavailable\b|\bdisabled\b|\binactive\b", response_lower,
            ):
                result.matched_values.append({"key": key, "expected": value, "found": True})
            else:
                result.missing_values.append(key)

        elif isinstance(value, (int, float)):
            matched = any(
                _numeric_close(value, n, numeric_tolerance) for n in response_numbers
            )
            if not matched:
                matched = any(
                    _conversion_close(value, n, 0.012)
                    for n in response_numbers
                )
            if not matched and value < 0:
                matched = any(
                    _numeric_close(abs(value), n, numeric_tolerance)
                    for n in response_numbers
                )
            if not matched:
                matched = any(
                    _magnitude_close(value, n, response_context=response_lower)
                    for n in response_numbers
                )
            if not matched and value == 0:
                leaf = key.rsplit(".", 1)[-1].rsplit("[", 1)[0].lower()
                if re.search(
                    rf"\bno\s+{re.escape(leaf)}\b|\bzero\s+{re.escape(leaf)}\b"
                    rf"|\b0\s+{re.escape(leaf)}\b",
                    response_lower,
                ):
                    matched = True
            if not matched and isinstance(value, int):
                semantics = _STATUS_SEMANTICS.get(value)
                if semantics and any(s in response_lower for s in semantics):
                    matched = True
            if matched:
                result.matched_values.append({"key": key, "expected": value, "found": True})
            else:
                str_value = str(value)
                if str_value in agent_response:
                    result.matched_values.append({"key": key, "expected": value, "found": True})
                elif response_numbers:
                    result.mismatched_values.append({
                        "key": key,
                        "expected": value,
                        "found_in_response": False,
                        "response_numbers": response_numbers[:5],
                    })
                else:
                    result.missing_values.append(key)

        elif isinstance(value, str):
            if value.lower() in response_lower or (
                _normalize_months(value).lower().replace(",", "")
                in _normalize_months(response_lower).replace(",", "")
            ):
                result.matched_values.append({"key": key, "expected": value, "found": True})
            else:
                substitute = _detect_substitution(
                    value, agent_response, all_tool_str_values,
                )
                if substitute is not None:
                    result.substituted_values.append({
                        "key": key,
                        "expected": value,
                        "substitute": substitute,
                    })
                else:
                    result.missing_values.append(key)

        elif value is None:
            continue

    # --- Post-processing: reclassify numeric mismatches as omissions ---
    # If every response number is already "claimed" by a matched numeric
    # tool value, then an unmatched numeric tool value was simply omitted
    # by the agent, not contradicted.
    if result.mismatched_values and response_numbers:
        claimed: set[float] = set()
        for m in result.matched_values:
            v = m.get("expected")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                for rn in response_numbers:
                    if (
                        _numeric_close(v, rn, numeric_tolerance)
                        or _conversion_close(v, rn, 0.012)
                        or _magnitude_close(v, rn, response_context=response_lower)
                    ):
                        claimed.add(rn)
                if v < 0:
                    for rn in response_numbers:
                        if _numeric_close(abs(v), rn, numeric_tolerance):
                            claimed.add(rn)
            elif isinstance(v, str):
                for sn in _extract_numbers(v):
                    for rn in response_numbers:
                        if _numeric_close(sn, rn, numeric_tolerance):
                            claimed.add(rn)
        all_claimed = all(rn in claimed for rn in response_numbers)
        if all_claimed:
            still_mismatched = []
            for mm in result.mismatched_values:
                if isinstance(mm.get("expected"), (int, float)) and not isinstance(
                    mm.get("expected"), bool
                ):
                    result.missing_values.append(mm["key"])
                else:
                    still_mismatched.append(mm)
            result.mismatched_values = still_mismatched

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
