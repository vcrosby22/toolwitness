"""Classification engine — combines receipt verification and structural matching
into a final Classification with confidence score.
"""

from __future__ import annotations

from typing import Any

from toolwitness.core.types import (
    Classification,
    ToolExecution,
    VerificationResult,
)
from toolwitness.verification.structural import MatchResult, structural_match


def classify(
    tool_name: str,
    agent_response: str,
    execution: ToolExecution | None,
    *,
    receipt_valid: bool | None = None,
) -> VerificationResult:
    """Classify an agent's claim about a tool call.

    Decision tree:
      1. No execution at all → SKIPPED (agent claims tool ran, but no receipt)
      2. Execution exists, receipt invalid → treat as FABRICATED (tampered)
      3. Execution exists, receipt valid → run structural match:
         a. High match ratio, no contradictions → VERIFIED
         b. Partial match + extra claims → EMBELLISHED
         c. Low match / contradictions → FABRICATED

    Args:
        tool_name: Name of the tool the agent claims to have called.
        agent_response: The agent's text response referencing the tool.
        execution: Recorded ToolExecution, or None if tool was never called.
        receipt_valid: Override for receipt validation (if already checked).

    Returns:
        VerificationResult with classification and confidence.
    """
    if execution is None:
        return VerificationResult(
            tool_name=tool_name,
            classification=Classification.SKIPPED,
            confidence=0.97,
            evidence={"reason": "no_execution_receipt"},
            receipt=None,
        )

    if receipt_valid is False:
        return VerificationResult(
            tool_name=tool_name,
            classification=Classification.FABRICATED,
            confidence=0.90,
            evidence={"reason": "invalid_receipt_signature"},
            receipt=execution.receipt,
        )

    match_result = structural_match(execution.output, agent_response)
    evidence = _build_evidence(match_result)

    classification, confidence = _score(match_result)

    return VerificationResult(
        tool_name=tool_name,
        classification=classification,
        confidence=confidence,
        evidence=evidence,
        receipt=execution.receipt,
    )


def _score(match: MatchResult) -> tuple[Classification, float]:
    """Map structural match results to classification + confidence.

    Key distinction: "not found in response" (omission) is different from
    "found with wrong value" (contradiction). Selective reporting — mentioning
    2 of 5 results — is legitimate, not fabrication.

    Missing string values (e.g. city="Miami" not in response) are treated as
    a substitution signal when matched count is low relative to output size.
    """
    matched = len(match.matched_values)
    mismatched = len(match.mismatched_values)
    missing_strings = len(match.missing_values)
    has_extras = match.has_extra_claims
    total = matched + mismatched

    if total == 0 and missing_strings == 0:
        return Classification.VERIFIED, 0.50

    if total == 0 and missing_strings > 0:
        confidence = 0.60 + min(missing_strings * 0.10, 0.30)
        return Classification.FABRICATED, min(confidence, 0.85)

    ratio = matched / total if total > 0 else 0.0

    # Missing strings (key identifiers like city names not found in response)
    # may indicate value substitution (said "NYC" instead of "Miami").
    # Weight against total fields from the output, not just matched count.
    total_output_fields = matched + mismatched + missing_strings
    if missing_strings > 0 and total_output_fields > 0:
        missing_ratio = missing_strings / total_output_fields
        # High missing ratio → likely fabrication (substituted identifiers)
        # But only when match_ratio is imperfect — if everything mentioned
        # was correct, missing strings are just selective omission.
        if missing_ratio >= 0.3 and mismatched == 0 and ratio < 1.0:
            confidence = 0.65 + missing_ratio * 0.25
            return Classification.FABRICATED, min(confidence, 0.90)
        # Missing + mismatches together → stronger fabrication signal
        if missing_strings > 0 and mismatched > 0:
            confidence = 0.65 + missing_ratio * 0.25
            return Classification.FABRICATED, min(confidence, 0.90)

    # Active contradictions (values found but wrong) are strong fabrication signals
    if mismatched > 0 and ratio < 0.5:
        confidence = 0.75 + (1 - ratio) * 0.20
        return Classification.FABRICATED, min(confidence, 0.95)

    if mismatched > 0 and ratio < 0.8:
        confidence = 0.60 + (1 - ratio) * 0.25
        return Classification.FABRICATED, min(confidence, 0.90)

    # Omission with no contradictions: selective reporting is okay
    # (e.g. mentioned 2 of 5 results, but the 2 are accurate)
    if mismatched > 0 and ratio >= 0.8:
        confidence = 0.65 + ratio * 0.15
        return Classification.EMBELLISHED, min(confidence, 0.80)

    # Extra claims beyond tool output
    if has_extras and not mismatched:
        confidence = 0.65 + ratio * 0.15
        return Classification.EMBELLISHED, min(confidence, 0.85)

    if has_extras and ratio >= 0.7:
        confidence = 0.60 + ratio * 0.20
        return Classification.EMBELLISHED, min(confidence, 0.85)

    # Good match, no contradictions, no extras
    if matched > 0 and mismatched == 0:
        confidence = 0.85 + ratio * 0.14
        return Classification.VERIFIED, min(confidence, 0.99)

    confidence = 0.60 + (1 - ratio) * 0.25
    return Classification.FABRICATED, min(confidence, 0.90)


def _build_evidence(match: MatchResult) -> dict[str, Any]:
    """Build a structured evidence dict from match results."""
    return {
        "match_ratio": match.match_ratio,
        "matched_count": len(match.matched_values),
        "mismatched_count": len(match.mismatched_values),
        "extra_claims_count": len(match.extra_claims),
        "missing_count": len(match.missing_values),
        "matched": match.matched_values[:5],
        "mismatched": match.mismatched_values[:5],
        "extra_claims": match.extra_claims[:5],
    }
