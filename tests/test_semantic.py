"""Tests for the semantic verification module.

Tests use a mock LLM judge to avoid API dependencies. The mock returns
structured JSON responses that the parser converts to MatchResult objects.

The structural limitation canary tests from test_verification_scenarios.py
are replayed here with semantic verification to confirm they flip from
VERIFIED to FABRICATED.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from toolwitness.core.classifier import classify
from toolwitness.core.types import ExecutionReceipt, ToolExecution
from toolwitness.verification.semantic import (
    LLMJudgeVerifier,
    MatchResult,
    SemanticVerifier,
    create_verifier,
)

# ═══════════════════════════════════════════════════════════════════════════
# Helper: build a mock verifier from a canned judge response
# ═══════════════════════════════════════════════════════════════════════════

def _mock_judge_response(verdict: str, matched=None, fabricated=None, missing=None) -> str:
    return json.dumps({
        "verdict": verdict,
        "matched": matched or [],
        "fabricated": fabricated or [],
        "missing": missing or [],
    })


def _make_execution(tool_name: str, output: Any) -> ToolExecution:
    return ToolExecution(
        tool_name=tool_name,
        args={},
        output=output,
        receipt=ExecutionReceipt(
            receipt_id=f"test-{tool_name}",
            tool_name=tool_name,
            args_hash="abc",
            output_hash="def",
            timestamp=1000.0,
            duration_ms=10.0,
            signature="test",
        ),
        error=None,
    )


class MockSemanticVerifier(SemanticVerifier):
    """Deterministic mock that returns preset verdicts per source_text."""

    def __init__(self, verdicts: dict[str, MatchResult]):
        self._verdicts = verdicts

    def verify(self, source_text: str, agent_response: str) -> MatchResult:
        for key, result in self._verdicts.items():
            if key in source_text:
                return result
        return MatchResult()


# ═══════════════════════════════════════════════════════════════════════════
# 1. LLMJudgeVerifier response parsing
# ═══════════════════════════════════════════════════════════════════════════

class TestResponseParsing:
    """Test that the LLM judge response parser produces correct MatchResults."""

    def test_faithful_verdict(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        raw = _mock_judge_response(
            "faithful",
            matched=[{"value": "37.0°C", "note": "correct conversion"}],
        )
        result = verifier._parse_response(raw)
        assert len(result.matched_values) == 1
        assert result.matched_values[0]["expected"] == "37.0°C"
        assert result.match_ratio == 1.0

    def test_fabricated_verdict(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        raw = _mock_judge_response(
            "fabricated",
            fabricated=[{"expected": "37.0°C", "got": "42.5°C", "note": "wrong temp"}],
        )
        result = verifier._parse_response(raw)
        assert len(result.mismatched_values) == 1
        assert result.mismatched_values[0]["expected"] == "37.0°C"
        assert result.mismatched_values[0]["got"] == "42.5°C"
        assert result.match_ratio == 0.0

    def test_embellished_with_fabricated(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        raw = _mock_judge_response(
            "embellished",
            matched=[{"value": "72°F", "note": "temp correct"}],
            fabricated=[{"expected": "sunny", "got": "partly cloudy", "note": "wrong"}],
        )
        result = verifier._parse_response(raw)
        assert len(result.matched_values) == 1
        assert len(result.mismatched_values) == 1
        assert result.match_ratio == 0.5

    def test_embellished_no_fabricated(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        raw = _mock_judge_response(
            "embellished",
            matched=[{"value": "72°F", "note": "correct"}],
        )
        result = verifier._parse_response(raw)
        assert len(result.extra_claims) == 1

    def test_missing_values_captured(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        raw = _mock_judge_response(
            "faithful",
            matched=[{"value": "72°F", "note": "ok"}],
            missing=["wind: 5mph"],
        )
        result = verifier._parse_response(raw)
        assert "wind: 5mph" in result.missing_values

    def test_non_json_falls_back(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        result = verifier._parse_response("I cannot evaluate this.")
        assert result.total_checked == 0

    def test_empty_verdict_with_fabricated(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        raw = _mock_judge_response(
            "fabricated",
            fabricated=[{"expected": "19", "got": "17", "note": "wrong die"}],
        )
        result = verifier._parse_response(raw)
        assert result.match_ratio == 0.0

    def test_json_embedded_in_markdown(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        raw = (
            "Here is the evaluation:\n"
            "```json\n"
            + _mock_judge_response("fabricated", fabricated=[{"expected": "A", "got": "B", "note": "wrong"}])
            + "\n```"
        )
        result = verifier._parse_response(raw)
        assert len(result.mismatched_values) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 2. Factory function
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateVerifier:
    def test_default_openai(self):
        v = create_verifier(api_key="test")
        assert isinstance(v, LLMJudgeVerifier)
        assert v.provider == "openai"
        assert v.model == "gpt-4o-mini"

    def test_anthropic(self):
        v = create_verifier(provider="anthropic", api_key="test")
        assert v.provider == "anthropic"
        assert "claude" in v.model

    def test_custom_model(self):
        v = create_verifier(provider="openai", model="gpt-4o", api_key="test")
        assert v.model == "gpt-4o"

    def test_unknown_provider_defers_to_runtime(self):
        v = create_verifier(provider="local", api_key="test")
        assert v.provider == "local"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Classifier routing: semantic path
# ═══════════════════════════════════════════════════════════════════════════

class TestClassifierRouting:
    """Verify the classify() function uses semantic for strings when available."""

    def test_string_output_uses_semantic_when_provided(self):
        fabricated_result = MatchResult()
        fabricated_result.mismatched_values.append({
            "key": "semantic",
            "expected": "37.0°C",
            "got": "42.5°C",
            "note": "wrong temperature",
        })

        mock_verifier = MockSemanticVerifier({"37.0": fabricated_result})
        execution = _make_execution("convert_temperature", "98.6°F = 37.0°C")
        result = classify(
            "convert_temperature",
            "convert_temperature: 98.6°F converts to 42.5°C",
            execution,
            semantic_verifier=mock_verifier,
        )
        assert result.classification.value == "fabricated"
        assert result.evidence.get("verification_method") == "semantic"

    def test_string_output_falls_back_to_structural_without_semantic(self):
        execution = _make_execution("convert_temperature", "98.6°F = 37.0°C")
        result = classify(
            "convert_temperature",
            "convert_temperature: 98.6°F converts to 42.5°C",
            execution,
        )
        assert result.evidence.get("verification_method") == "structural_grounding"

    def test_dict_output_always_uses_structural(self):
        execution = _make_execution("get_weather", {"temp": 72, "condition": "sunny"})
        mock_verifier = MockSemanticVerifier({})
        result = classify(
            "get_weather",
            "The weather in Miami is 72°F and sunny",
            execution,
            semantic_verifier=mock_verifier,
        )
        assert result.evidence.get("verification_method") == "structural"
        assert result.classification.value in ("verified", "embellished")

    def test_verification_method_tag_always_present(self):
        execution = _make_execution("tool_a", {"key": "value"})
        result = classify("tool_a", "tool_a returned value", execution)
        assert "verification_method" in result.evidence


# ═══════════════════════════════════════════════════════════════════════════
# 4. Canary tests: structural limitations flipped by semantic
# ═══════════════════════════════════════════════════════════════════════════

class TestCanaryFlips:
    """Replay the structural limitation canaries with a mock semantic verifier.

    These correspond to the 4 scenarios in TestStructuralLimitations from
    test_verification_scenarios.py. When those tests assert the structural
    verifier returns VERIFIED (the wrong answer), these tests confirm that
    the semantic path would return FABRICATED (the right answer).
    """

    def _build_mock_verifier(self, fabrication_details: list[dict]) -> MockSemanticVerifier:
        result = MatchResult()
        for detail in fabrication_details:
            result.mismatched_values.append({
                "key": "semantic",
                "expected": detail["expected"],
                "got": detail["got"],
                "note": detail.get("note", ""),
            })
        return MockSemanticVerifier({"": result})

    def test_dice_roll_fabrication_caught(self):
        """Canary: structural says VERIFIED, semantic says FABRICATED."""
        mock = self._build_mock_verifier([
            {"expected": "[19, 19] total 38", "got": "[17, 12] total 29", "note": "wrong dice values"},
        ])
        execution = _make_execution("roll_dice", "Rolled 2d20: [19, 19] (total: 38)")
        result = classify(
            "roll_dice",
            "roll_dice: I rolled 2d20 and got [17, 12] for a total of 29",
            execution,
            semantic_verifier=mock,
        )
        assert result.classification.value == "fabricated"

    def test_temperature_fabrication_caught(self):
        """Canary: structural says VERIFIED, semantic says FABRICATED."""
        mock = self._build_mock_verifier([
            {"expected": "37.0°C", "got": "42.5°C", "note": "wrong conversion"},
        ])
        execution = _make_execution("convert_temperature", "98.6°F = 37.0°C")
        result = classify(
            "convert_temperature",
            "convert_temperature: 98.6°F converts to 42.5°C",
            execution,
            semantic_verifier=mock,
        )
        assert result.classification.value == "fabricated"

    def test_definition_fabrication_caught(self):
        """Canary: structural says VERIFIED, semantic says FABRICATED."""
        real_def = (
            "verification: The process of independently confirming "
            "that an agent's claims match what actually occurred."
        )
        mock = self._build_mock_verifier([
            {"expected": "independently confirming claims match", "got": "formal audit in accounting", "note": "wrong definition"},
        ])
        execution = _make_execution("lookup_word", real_def)
        result = classify(
            "lookup_word",
            'lookup_word: "verification" means a formal audit process used in accounting and finance',
            execution,
            semantic_verifier=mock,
        )
        assert result.classification.value == "fabricated"

    def test_multi_tool_all_fabricated_caught(self):
        """Canary: all 3 string fabrications caught through semantic routing."""
        tools_and_responses = [
            ("roll_dice", "Rolled 2d20: [19, 19] (total: 38)",
             "I rolled 2d20 and got [17, 12] for a total of 29",
             [{"expected": "[19, 19]", "got": "[17, 12]", "note": "wrong dice"}]),
            ("convert_temperature", "98.6°F = 37.0°C",
             "98.6°F converts to 42.5°C",
             [{"expected": "37.0°C", "got": "42.5°C", "note": "wrong temp"}]),
            ("lookup_word",
             "verification: The process of independently confirming that an agent's claims match what actually occurred.",
             '"verification" means a formal audit process used in accounting and finance',
             [{"expected": "independently confirming", "got": "formal audit", "note": "wrong def"}]),
        ]

        for tool_name, output, response, fabrications in tools_and_responses:
            mock = self._build_mock_verifier(fabrications)
            execution = _make_execution(tool_name, output)
            result = classify(
                tool_name,
                f"{tool_name}: {response}",
                execution,
                semantic_verifier=mock,
            )
            assert result.classification.value == "fabricated", (
                f"{tool_name} should be FABRICATED with semantic, got {result.classification.value}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 5. Error handling and graceful degradation
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Semantic failures should degrade gracefully to empty MatchResult."""

    def test_llm_call_exception_returns_empty(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        with patch.object(verifier, "_call_llm", side_effect=RuntimeError("API error")):
            result = verifier.verify("source", "response")
        assert result.total_checked == 0

    def test_invalid_json_returns_empty(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        result = verifier._parse_response("not json at all")
        assert result.total_checked == 0

    def test_missing_openai_package(self):
        verifier = LLMJudgeVerifier(provider="openai", api_key="test")
        with (
            patch.dict("sys.modules", {"openai": None}),
            pytest.raises(ImportError, match="openai package required"),
        ):
            verifier._get_client()

    def test_missing_anthropic_package(self):
        verifier = LLMJudgeVerifier(provider="anthropic", api_key="test")
        with (
            patch.dict("sys.modules", {"anthropic": None}),
            pytest.raises(ImportError, match="anthropic package required"),
        ):
            verifier._get_client()

    def test_unknown_provider(self):
        verifier = LLMJudgeVerifier(provider="local_llm", api_key="test")
        with pytest.raises(ValueError, match="Unknown semantic provider"):
            verifier._get_client()


# ═══════════════════════════════════════════════════════════════════════════
# 6. Dict value substitution — structural matcher regression tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDictSubstitutionRegression:
    """Verify structural matching catches dict value substitutions.

    These tests target the adaptive numeric tolerance fix and the
    small-output missing-value sensitivity in the scorer.
    """

    def test_temperature_substitution_72_to_75(self):
        """72->75 must be a mismatch, not a fuzzy match."""
        execution = _make_execution(
            "get_weather",
            {"temperature": 72, "condition": "sunny", "city": "Miami"},
        )
        result = classify(
            "get_weather",
            "The weather in Miami is 75°F and cloudy.",
            execution,
        )
        assert result.classification.value == "fabricated", (
            f"Expected FABRICATED, got {result.classification.value}"
        )

    def test_honest_dict_still_verified(self):
        """Correct values must still pass verification."""
        execution = _make_execution(
            "get_weather",
            {"temperature": 72, "condition": "sunny", "city": "Miami"},
        )
        result = classify(
            "get_weather",
            "The weather in Miami is 72°F and sunny.",
            execution,
        )
        assert result.classification.value == "verified"

    def test_close_rounding_still_matches(self):
        """72.0 reported as 72 should still verify (within +/-1)."""
        execution = _make_execution(
            "get_weather",
            {"temperature": 72.2, "condition": "sunny", "city": "Miami"},
        )
        result = classify(
            "get_weather",
            "The weather in Miami is 72°F and sunny.",
            execution,
        )
        assert result.classification.value == "verified"

    def test_small_number_exact_match_required(self):
        """Die roll of 4 reported as 5 must be caught (small value, tight tolerance)."""
        execution = _make_execution("roll_result", {"roll": 4, "sides": 20})
        result = classify(
            "roll_result",
            "I rolled a 5 on a d20.",
            execution,
        )
        assert result.classification.value in ("fabricated", "embellished"), (
            f"Expected FABRICATED or EMBELLISHED for 4->5, got {result.classification.value}"
        )

    def test_large_number_tolerance_preserved(self):
        """Large numbers like 10000 vs 10200 should still match (2% diff, within 5%)."""
        execution = _make_execution(
            "get_stats",
            {"users": 10000, "revenue": 50000},
        )
        result = classify(
            "get_stats",
            "There are about 10,200 users and revenue is $50,000.",
            execution,
        )
        assert result.classification.value == "verified"

    def test_string_only_substitution_on_small_output(self):
        """sunny->cloudy with correct numeric: structural limitation.

        When the numeric value is correct and only a lowercase single-word
        string is substituted, structural matching can't distinguish omission
        from substitution. This is a known gap — the semantic verifier catches
        it. If structural substitution detection improves for lowercase values,
        this test should be tightened to assert EMBELLISHED or FABRICATED.
        """
        execution = _make_execution(
            "get_weather",
            {"temperature": 72, "condition": "sunny", "city": "Miami"},
        )
        result = classify(
            "get_weather",
            "The weather in Miami is 72°F and cloudy.",
            execution,
        )
        # Known limitation: structural sees this as selective omission
        assert result.classification.value in ("verified", "embellished"), (
            f"Expected VERIFIED or EMBELLISHED (structural limitation), got {result.classification.value}"
        )

    def test_numeric_and_string_both_substituted(self):
        """Both temperature and condition wrong: definitely FABRICATED."""
        execution = _make_execution(
            "get_weather",
            {"temperature": 72, "condition": "sunny", "city": "Miami"},
        )
        result = classify(
            "get_weather",
            "The weather in Miami is 85°F and rainy.",
            execution,
        )
        assert result.classification.value == "fabricated"

    def test_selective_reporting_large_output_ok(self):
        """Mentioning 2 of 6 fields from a large output is selective, not fabrication."""
        execution = _make_execution(
            "get_full_weather",
            {
                "temperature": 72,
                "condition": "sunny",
                "city": "Miami",
                "humidity": 65,
                "wind_speed": 12,
                "uv_index": 8,
            },
        )
        result = classify(
            "get_full_weather",
            "It's 72°F and sunny in Miami.",
            execution,
        )
        assert result.classification.value == "verified"
