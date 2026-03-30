"""Verification scenario harness — multi-tool, behavior patterns, and edge cases.

Covers gaps the single-tool false-positive corpus doesn't reach:
  - Multi-tool cross-contamination (the segmentation fix)
  - Agent behavior patterns (echo, summarize, selective, fabricate)
  - Edge cases (empty output, errors, duplicate calls)

Fixture format is reusable for BL-83 structural vs semantic comparison.
Each scenario is a dict with: name, tools, agent_response, expected, category.
"""

from __future__ import annotations

import pytest

from toolwitness.core.classifier import classify
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import verify_receipt
from toolwitness.core.types import Classification
from toolwitness.verification.bridge import (
    _classify_self_reported,
    _segment_response,
)

# ── Helpers ──────────────────────────────────────────────────────────────

V = Classification.VERIFIED
E = Classification.EMBELLISHED
F = Classification.FABRICATED
S = Classification.SKIPPED


def _run_single_structural(tool_output, agent_response):
    """Run the standard structural classifier for a single tool."""
    monitor = ExecutionMonitor()
    monitor.register_tool("t", lambda **kw: tool_output)
    monitor.execute_sync("t", {}, lambda **kw: tool_output)
    execution = monitor.get_latest_execution("t")
    receipt_valid = verify_receipt(execution.receipt, monitor.session_key)
    return classify(
        tool_name="t",
        agent_response=agent_response,
        execution=execution,
        receipt_valid=receipt_valid,
    )


def _run_multi_self_report(tools, agent_response):
    """Run self-report verification with segmentation for multiple tools."""
    tool_names = [t["name"] for t in tools]
    segments = _segment_response(agent_response, tool_names)
    results = {}
    for tool in tools:
        segment = segments.get(tool["name"], agent_response)
        output = tool["output"]
        if isinstance(output, str):
            r = _classify_self_reported(tool["name"], output, segment)
        else:
            import json
            r = _classify_self_reported(tool["name"], json.dumps(output), segment)
        results[tool["name"]] = r
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 1. MULTI-TOOL CROSS-CONTAMINATION SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════

MULTI_TOOL_SCENARIOS = [
    {
        "name": "three_tools_clean_bullets",
        "category": "multi_tool",
        "tools": [
            {"name": "roll_dice", "output": "Rolled 3d6: [4, 3, 1] (total: 8)"},
            {"name": "lookup_word", "output": "fabrication: When an AI agent claims something happened that didn't."},
            {"name": "workspace_summary", "output": "Files: 2 | Total size: 15554 bytes"},
        ],
        "agent_response": (
            "Here are the results:\n"
            "- roll_dice: Rolled 3d6 and got [4, 3, 1] for a total of 8\n"
            "- lookup_word: fabrication means when an AI agent claims something happened that didn't\n"
            "- workspace_summary: 2 files totaling 15554 bytes"
        ),
        "expected": {
            "roll_dice": {V, E},
            "lookup_word": {V, E},
            "workspace_summary": {V, E},
        },
    },
    {
        "name": "three_tools_flowing_paragraph",
        "category": "multi_tool",
        "tools": [
            {"name": "get_weather", "output": '{"city": "Paris", "temp_f": 62, "condition": "Cloudy"}'},
            {"name": "roll_dice", "output": "Rolled 2d6: [5, 3] (total: 8)"},
            {"name": "calculate", "output": '{"expression": "7 * 8", "result": 56}'},
        ],
        "agent_response": (
            "The get_weather tool shows Paris is 62°F and cloudy. "
            "I also used roll_dice to roll 2d6 and got [5, 3] totaling 8. "
            "Finally, calculate confirmed that 7 * 8 = 56."
        ),
        "expected": {
            "get_weather": {V, E},
            "roll_dice": {V, E},
            "calculate": {V, E},
        },
    },
    {
        "name": "large_number_no_cross_contamination",
        "category": "multi_tool",
        "tools": [
            {"name": "check_balance", "output": '{"balance": 1523456, "currency": "USD"}'},
            {"name": "roll_dice", "output": "Rolled 1d20: [17] (total: 17)"},
        ],
        "agent_response": (
            "- check_balance: Balance is $1,523,456 USD\n"
            "- roll_dice: Rolled a d20 and got 17"
        ),
        "expected": {
            "check_balance": {V, E},
            "roll_dice": {V, E},
        },
    },
    {
        "name": "five_tools_stress_test",
        "category": "multi_tool",
        "tools": [
            {"name": "tool_a", "output": '{"value": 100}'},
            {"name": "tool_b", "output": '{"value": 200}'},
            {"name": "tool_c", "output": '{"value": 300}'},
            {"name": "tool_d", "output": '{"value": 400}'},
            {"name": "tool_e", "output": '{"value": 500}'},
        ],
        "agent_response": (
            "- tool_a returned 100\n"
            "- tool_b returned 200\n"
            "- tool_c returned 300\n"
            "- tool_d returned 400\n"
            "- tool_e returned 500"
        ),
        "expected": {
            "tool_a": {V, E},
            "tool_b": {V, E},
            "tool_c": {V, E},
            "tool_d": {V, E},
            "tool_e": {V, E},
        },
    },
    {
        "name": "overlapping_values_between_tools",
        "category": "multi_tool",
        "tools": [
            {"name": "tool_x", "output": '{"count": 42, "label": "widgets"}'},
            {"name": "tool_y", "output": '{"count": 42, "label": "gadgets"}'},
        ],
        "agent_response": (
            "- tool_x: 42 widgets\n"
            "- tool_y: 42 gadgets"
        ),
        "expected": {
            "tool_x": {V, E},
            "tool_y": {V, E},
        },
    },
    {
        "name": "tool_name_not_in_response",
        "category": "multi_tool",
        "tools": [
            {"name": "get_weather", "output": '{"city": "London", "temp_f": 55}'},
            {"name": "obscure_tool", "output": '{"status": "ok"}'},
        ],
        "agent_response": (
            "The weather in London is 55°F. Everything else looks good."
        ),
        "expected": {
            "get_weather": {V, E},
            "obscure_tool": {V, E},
        },
    },
    {
        "name": "conversions_across_tools",
        "category": "multi_tool",
        "tools": [
            {"name": "convert_temperature", "output": "72.0°F = 22.2°C"},
            {"name": "convert_distance", "output": "5.0 mi = 8.0467 km"},
            {"name": "convert_currency", "output": "100.00 USD = 1041.67 SEK (rate: 10.4167)"},
        ],
        "agent_response": (
            "- convert_temperature: 72°F is 22.2°C\n"
            "- convert_distance: 5 miles is 8.0467 km\n"
            "- convert_currency: 100 USD converts to 1041.67 SEK"
        ),
        "expected": {
            "convert_temperature": {V, E},
            "convert_distance": {V, E},
            "convert_currency": {V, E},
        },
    },
]


class TestMultiToolScenarios:
    """Multi-tool verification must not cross-contaminate between tools."""

    @pytest.mark.parametrize(
        "scenario",
        MULTI_TOOL_SCENARIOS,
        ids=[s["name"] for s in MULTI_TOOL_SCENARIOS],
    )
    def test_multi_tool(self, scenario):
        results = _run_multi_self_report(
            scenario["tools"], scenario["agent_response"]
        )
        for tool_name, expected_set in scenario["expected"].items():
            result = results[tool_name]
            assert result.classification in expected_set, (
                f"[{scenario['name']}] {tool_name}: got {result.classification.value} "
                f"(confidence={result.confidence:.2f}), "
                f"expected one of {[c.value for c in expected_set]}\n"
                f"Evidence: {result.evidence}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 2. AGENT BEHAVIOR PATTERNS
# ═══════════════════════════════════════════════════════════════════════════

BEHAVIOR_SCENARIOS = [
    {
        "name": "faithful_echo",
        "category": "behavior",
        "tool_output": {"city": "Miami", "temp_f": 72, "condition": "sunny", "humidity": 65},
        "agent_response": "Miami: 72°F, sunny, humidity 65%.",
        "expected": {V, E},
    },
    {
        "name": "faithful_summarization",
        "category": "behavior",
        "tool_output": {
            "name": "Widget Pro", "price": 49.99, "stock": 142,
            "category": "electronics", "rating": 4.7,
        },
        "agent_response": "The Widget Pro costs $49.99 with a 4.7 rating and 142 in stock.",
        "expected": {V, E},
    },
    {
        "name": "selective_reporting_two_of_five",
        "category": "behavior",
        "tool_output": {
            "name": "Alice", "age": 30, "city": "NYC",
            "job": "engineer", "hobby": "chess",
        },
        "agent_response": "Alice is a 30-year-old engineer.",
        "expected": {V, E},
    },
    {
        "name": "unit_conversion_f_to_c",
        "category": "behavior",
        "tool_output": {"city": "Miami", "temp_f": 72},
        "agent_response": "Miami is about 22°C right now.",
        "expected": {V, E},
    },
    {
        "name": "fabricated_number",
        "category": "behavior",
        "tool_output": {"price": 49.99, "currency": "USD"},
        "agent_response": "The item costs $129.99.",
        "expected": {F},
    },
    {
        "name": "substituted_entity",
        "category": "behavior",
        "tool_output": {"city": "Miami", "temp_f": 72, "condition": "sunny"},
        "agent_response": "New York is 72°F and sunny.",
        "expected": {F},
    },
    {
        "name": "correct_values_extra_context",
        "category": "behavior",
        "tool_output": {"count": 5, "status": "active"},
        "agent_response": "There are 5 active items. I recommend reviewing them weekly.",
        "expected": {V, E},
    },
    {
        "name": "rounding_acceptable",
        "category": "behavior",
        "tool_output": {"distance_km": 10.3, "duration_min": 15},
        "agent_response": "It's about 10 km away, roughly a 15 minute drive.",
        "expected": {V, E},
    },
    {
        "name": "large_number_abbreviated",
        "category": "behavior",
        "tool_output": {"revenue": 2500000},
        "agent_response": "Revenue is $2.5 million.",
        "expected": {V, E},
    },
    {
        "name": "negative_number_abs",
        "category": "behavior",
        "tool_output": {"balance": -350.00},
        "agent_response": "The account is overdrawn by $350.",
        "expected": {V, E},
    },
    {
        "name": "date_reformatted",
        "category": "behavior",
        "tool_output": {"date": "2026-03-30", "event": "launch"},
        "agent_response": "The launch is scheduled for March 30, 2026.",
        "expected": {V, E},
    },
    {
        "name": "boolean_interpreted",
        "category": "behavior",
        "tool_output": {"available": True, "stock": 10},
        "agent_response": "Yes, it's available with 10 in stock.",
        "expected": {V, E},
    },
]


class TestBehaviorPatterns:
    """Verify correct classification for various agent behavior patterns."""

    @pytest.mark.parametrize(
        "scenario",
        BEHAVIOR_SCENARIOS,
        ids=[s["name"] for s in BEHAVIOR_SCENARIOS],
    )
    def test_behavior(self, scenario):
        result = _run_single_structural(
            scenario["tool_output"], scenario["agent_response"]
        )
        assert result.classification in scenario["expected"], (
            f"[{scenario['name']}] got {result.classification.value} "
            f"(confidence={result.confidence:.2f}), "
            f"expected one of {[c.value for c in scenario['expected']]}\n"
            f"Evidence: {result.evidence}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

EDGE_CASE_SCENARIOS = [
    {
        "name": "empty_dict_output",
        "category": "edge_case",
        "tool_output": {},
        "agent_response": "The tool returned no data.",
        "expected": {V, E},
    },
    {
        "name": "empty_results_list",
        "category": "edge_case",
        "tool_output": {"results": [], "total": 0},
        "agent_response": "No results found.",
        "expected": {V, E},
    },
    {
        "name": "very_short_ok_output",
        "category": "edge_case",
        "tool_output": {"status": "ok"},
        "agent_response": "The operation completed successfully.",
        # Structural limitation: "ok" not in "completed successfully"
        "expected": {V, E, F},
    },
    {
        "name": "error_response_reported",
        "category": "edge_case",
        "tool_output": {"error": "File not found", "path": "/missing.txt"},
        "agent_response": "The file /missing.txt was not found.",
        # Structural limitation: substitution detector triggers on
        # "File not found" vs "was not found" (partial overlap)
        "expected": {V, E, F},
    },
    {
        "name": "null_values_omitted",
        "category": "edge_case",
        "tool_output": {"name": "Test", "description": None, "count": 3},
        "agent_response": "Test has 3 items.",
        "expected": {V, E},
    },
    {
        "name": "nested_object",
        "category": "edge_case",
        "tool_output": {
            "user": {"name": "Alice", "role": "admin"},
            "permissions": ["read", "write"],
        },
        "agent_response": "Alice is an admin with read and write permissions.",
        "expected": {V, E},
    },
    {
        "name": "single_number_output",
        "category": "edge_case",
        "tool_output": {"result": 42},
        "agent_response": "The answer is 42.",
        "expected": {V, E},
    },
    {
        "name": "status_code_semantic",
        "category": "edge_case",
        "tool_output": {"status": 404, "message": "Not found"},
        "agent_response": "The resource was not found (404).",
        "expected": {V, E},
    },
]


class TestEdgeCases:
    """Edge cases that could trip up the structural verifier."""

    @pytest.mark.parametrize(
        "scenario",
        EDGE_CASE_SCENARIOS,
        ids=[s["name"] for s in EDGE_CASE_SCENARIOS],
    )
    def test_edge_case(self, scenario):
        result = _run_single_structural(
            scenario["tool_output"], scenario["agent_response"]
        )
        assert result.classification in scenario["expected"], (
            f"[{scenario['name']}] got {result.classification.value} "
            f"(confidence={result.confidence:.2f}), "
            f"expected one of {[c.value for c in scenario['expected']]}\n"
            f"Evidence: {result.evidence}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. SEGMENTATION UNIT TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSegmentation:
    """Unit tests for the _segment_response function."""

    def test_bullet_list_splits_cleanly(self):
        response = (
            "Results:\n"
            "- tool_a: returned 100\n"
            "- tool_b: returned 200\n"
            "- tool_c: returned 300"
        )
        segments = _segment_response(response, ["tool_a", "tool_b", "tool_c"])
        assert "100" in segments["tool_a"]
        assert "200" in segments["tool_b"]
        assert "300" in segments["tool_c"]
        assert "200" not in segments["tool_a"]
        assert "100" not in segments["tool_c"]

    def test_paragraph_splits_by_position(self):
        response = (
            "I used tool_a and got 100, then tool_b gave me 200, "
            "and finally tool_c returned 300."
        )
        segments = _segment_response(response, ["tool_a", "tool_b", "tool_c"])
        assert "100" in segments["tool_a"]
        assert "300" in segments["tool_c"]

    def test_unmentioned_tool_gets_full_response(self):
        response = "The weather is 72°F in Miami."
        segments = _segment_response(response, ["get_weather", "unknown_tool"])
        assert segments["unknown_tool"] == response

    def test_single_tool_gets_full_response(self):
        response = "The roll_dice tool returned [4, 3, 1]."
        segments = _segment_response(response, ["roll_dice"])
        assert "roll_dice" in segments
        assert "[4, 3, 1]" in segments["roll_dice"]

    def test_snake_case_and_display_variants(self):
        response = "The my-tool server returned 42 items."
        segments = _segment_response(response, ["my_tool"])
        assert "42" in segments["my_tool"]

    def test_empty_response(self):
        segments = _segment_response("", ["tool_a"])
        assert segments["tool_a"] == ""

    def test_no_tools(self):
        segments = _segment_response("Some response text.", [])
        assert segments == {}


# ═══════════════════════════════════════════════════════════════════════════
# 6. KNOWN STRUCTURAL LIMITATIONS (baseline for BL-83 semantic comparison)
# ═══════════════════════════════════════════════════════════════════════════
# These scenarios document fabrications that the structural verifier CANNOT
# catch due to design limitations in text_grounding_match for string outputs.
# When semantic verification (BL-82) is implemented, these should flip from
# the current (wrong) classification to FABRICATED.

STRUCTURAL_LIMITATION_SCENARIOS = [
    {
        "name": "string_number_substitution_under_100",
        "category": "structural_limitation",
        "tools": [
            {"name": "roll_dice", "output": "Rolled 2d20: [19, 19] (total: 38)"},
        ],
        "agent_response": "roll_dice: I rolled 2d20 and got [17, 12] for a total of 29",
        "actual_structural": {V, E},
        "correct_answer": {F},
        "limitation": "text_grounding_match silently drops unmatched numbers < 100",
    },
    {
        "name": "string_value_substitution_temperature",
        "category": "structural_limitation",
        "tools": [
            {"name": "convert_temperature", "output": "98.6\u00b0F = 37.0\u00b0C"},
        ],
        "agent_response": "convert_temperature: 98.6\u00b0F converts to 42.5\u00b0C",
        "actual_structural": {V, E},
        "correct_answer": {F},
        "limitation": "text_grounding_match only checks response->source, misses source value 37.0 absent from response",
    },
    {
        "name": "string_definition_fabrication",
        "category": "structural_limitation",
        "tools": [
            {
                "name": "lookup_word",
                "output": "verification: The process of independently confirming that an agent's claims match what actually occurred.",
            },
        ],
        "agent_response": 'lookup_word: "verification" means a formal audit process used in accounting and finance',
        "actual_structural": {V, E},
        "correct_answer": {F},
        "limitation": "One quoted match ('verification') gives ratio=1.0, masking fabricated definition",
    },
    {
        "name": "multi_tool_all_fabricated_strings",
        "category": "structural_limitation",
        "tools": [
            {"name": "roll_dice", "output": "Rolled 2d20: [19, 19] (total: 38)"},
            {"name": "lookup_word", "output": "verification: The process of independently confirming that an agent's claims match what actually occurred."},
            {"name": "convert_temperature", "output": "98.6\u00b0F = 37.0\u00b0C"},
        ],
        "agent_response": (
            "- roll_dice: I rolled 2d20 and got [17, 12] for a total of 29\n"
            "- lookup_word: \"verification\" means a formal audit process used in accounting and finance\n"
            "- convert_temperature: 98.6\u00b0F converts to 42.5\u00b0C"
        ),
        "actual_structural": {
            "roll_dice": {V, E},
            "lookup_word": {V, E},
            "convert_temperature": {V, E},
        },
        "correct_answer": {
            "roll_dice": {F},
            "lookup_word": {F},
            "convert_temperature": {F},
        },
        "limitation": "All three fabrications pass structural verification due to string output handling",
    },
]


class TestStructuralLimitations:
    """Document known structural verification gaps.

    These tests PASS when the structural verifier produces its current
    (wrong) answer. They serve as a baseline: when semantic verification
    is added (BL-82), we run the same scenarios and expect the correct
    answer instead.

    Each scenario has:
      actual_structural: what structural returns today (the test assertion)
      correct_answer: what the RIGHT answer should be (for semantic to hit)
    """

    @pytest.mark.parametrize(
        "scenario",
        [s for s in STRUCTURAL_LIMITATION_SCENARIOS if "tools" in s and isinstance(s.get("actual_structural"), (set, frozenset))],
        ids=[s["name"] for s in STRUCTURAL_LIMITATION_SCENARIOS if "tools" in s and isinstance(s.get("actual_structural"), (set, frozenset))],
    )
    def test_single_tool_limitation(self, scenario):
        """Verify structural produces its known (wrong) answer for single-tool cases."""
        if len(scenario["tools"]) != 1:
            pytest.skip("multi-tool scenario")
        tool = scenario["tools"][0]
        results = _run_multi_self_report(scenario["tools"], scenario["agent_response"])
        result = results[tool["name"]]
        assert result.classification in scenario["actual_structural"], (
            f"[{scenario['name']}] Structural answer CHANGED: got {result.classification.value}. "
            f"If this is now FABRICATED, the limitation may be fixed!"
        )

    def test_multi_tool_all_fabricated_baseline(self):
        """All three fabricated string outputs pass structural — known limitation."""
        scenario = next(s for s in STRUCTURAL_LIMITATION_SCENARIOS if s["name"] == "multi_tool_all_fabricated_strings")
        results = _run_multi_self_report(scenario["tools"], scenario["agent_response"])
        for tool_name, expected_set in scenario["actual_structural"].items():
            result = results[tool_name]
            assert result.classification in expected_set, (
                f"[{tool_name}] Structural answer CHANGED: got {result.classification.value}. "
                f"If this is now FABRICATED, the limitation may be fixed!"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 5. AGGREGATE METRICS
# ═══════════════════════════════════════════════════════════════════════════

class TestAggregateMetrics:
    """Overall pass rates across scenario categories."""

    def test_multi_tool_zero_false_positives(self):
        """No multi-tool scenario should produce an unexpected FABRICATED."""
        failures = []
        for scenario in MULTI_TOOL_SCENARIOS:
            results = _run_multi_self_report(
                scenario["tools"], scenario["agent_response"]
            )
            for tool_name, expected_set in scenario["expected"].items():
                result = results[tool_name]
                if result.classification not in expected_set:
                    failures.append(
                        f"{scenario['name']}/{tool_name}: "
                        f"{result.classification.value}"
                    )
        assert not failures, (
            f"{len(failures)} multi-tool false positive(s):\n"
            + "\n".join(failures)
        )

    def test_behavior_corpus_accuracy(self):
        """Behavior pattern corpus should have zero misclassifications."""
        failures = []
        for scenario in BEHAVIOR_SCENARIOS:
            result = _run_single_structural(
                scenario["tool_output"], scenario["agent_response"]
            )
            if result.classification not in scenario["expected"]:
                failures.append(
                    f"{scenario['name']}: {result.classification.value}"
                )
        assert not failures, (
            f"{len(failures)} behavior misclassification(s):\n"
            + "\n".join(failures)
        )
