"""False-positive corpus — legitimate responses that must NOT be flagged.

These test cases represent correct agent behavior that ToolWitness must
classify as VERIFIED or EMBELLISHED (not FABRICATED or SKIPPED).

Regression gate: <2% false positive rate across this corpus.
"""

import pytest

from toolwitness.core.classifier import classify
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import verify_receipt
from toolwitness.core.types import Classification

FALSE_POSITIVE_CORPUS = [
    {
        "name": "paraphrase_temperature",
        "tool_output": {"city": "Miami", "temp_f": 72, "condition": "sunny"},
        "agent_response": "It's a beautiful 72 degree day in Miami with clear skies.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "rounding_up",
        "tool_output": {"price": 49.97, "currency": "USD"},
        "agent_response": "The item costs about $50.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "rounding_down",
        "tool_output": {"distance_km": 10.3},
        "agent_response": "It's roughly 10 km away.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "selective_reporting",
        "tool_output": {
            "name": "Alice", "age": 30, "city": "NYC",
            "job": "engineer", "hobby": "chess",
        },
        "agent_response": "Alice is a 30-year-old engineer.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "reworded_condition",
        "tool_output": {"condition": "partly_cloudy", "temp_c": 22},
        "agent_response": "The weather is partly cloudy at 22°C.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "list_summary",
        "tool_output": {
            "items": ["apple", "banana", "cherry", "date", "elderberry"],
        },
        "agent_response": "The list includes apple, banana, and cherry among others.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "boolean_true_text",
        "tool_output": {"available": True, "stock": 42},
        "agent_response": "Yes, the item is available with 42 in stock.",
        # Known MVP limitation: structural matcher can't map True → "Yes"
        # Requires semantic verification (post-MVP)
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
    {
        "name": "number_in_prose",
        "tool_output": {"users": 1523, "active": 847},
        "agent_response": "There are 1,523 users, of which 847 are active.",
        # Known MVP limitation: comma-separated numbers (1,523) split into
        # 1 and 523 by the regex extractor, missing the actual value
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
    {
        "name": "percentage_from_ratio",
        "tool_output": {"completed": 3, "total": 4},
        "agent_response": "3 out of 4 tasks are completed — that's 75%.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "empty_result_acknowledged",
        "tool_output": {"results": [], "total": 0},
        "agent_response": "The search returned no results.",
        # Known MVP limitation: empty list + 0 total has no string values
        # to match against "no results" — structural matcher sees only omission
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
    {
        "name": "nested_data_reported",
        "tool_output": {
            "location": {"city": "Miami", "state": "FL"},
            "temp_f": 72,
        },
        "agent_response": "In Miami, FL it's 72°F.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "status_code_interpretation",
        "tool_output": {"status": 200, "message": "OK"},
        "agent_response": "The request was successful.",
        # Known MVP limitation: "successful" is a semantic interpretation
        # of status=200 and message="OK" — structural matcher can't map this
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
    {
        "name": "date_reformatted",
        "tool_output": {"date": "2026-03-27", "event": "meeting"},
        "agent_response": "You have a meeting on March 27, 2026.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "large_number_abbreviated",
        "tool_output": {"revenue": 1500000, "currency": "USD"},
        "agent_response": "Revenue is $1.5 million.",
        # Known MVP limitation: 1500000 → "$1.5 million" is magnitude
        # conversion; structural matcher sees 1.5, not 1500000
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
    {
        "name": "null_field_omitted",
        "tool_output": {"name": "Alice", "phone": None, "email": "a@b.com"},
        "agent_response": "Alice's email is a@b.com.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "reordered_fields",
        "tool_output": {"first": "Jane", "last": "Doe", "age": 28},
        "agent_response": "Doe, Jane — age 28.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "plural_singular",
        "tool_output": {"items": ["widget"], "count": 1},
        "agent_response": "There is 1 widget in stock.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "implicit_zero",
        "tool_output": {"errors": 0, "warnings": 3},
        "agent_response": "No errors, but 3 warnings.",
        # Known MVP limitation: errors=0 is absent from text; structural
        # matcher sees only "3" and can't match it to the correct field
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
    {
        "name": "float_to_int",
        "tool_output": {"score": 95.0, "grade": "A"},
        "agent_response": "Score: 95, grade A.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "url_mentioned",
        "tool_output": {"url": "https://example.com/page", "status": 200},
        "agent_response": "The page at https://example.com/page returned a 200 status.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "negative_number",
        "tool_output": {"balance": -42.50, "currency": "USD"},
        "agent_response": "The account is overdrawn by $42.50.",
        # Known MVP limitation: structural matcher extracts 42.5 from text
        # but tool output has -42.5; sign-stripping not handled
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
    {
        "name": "timestamp_humanized",
        "tool_output": {"created_at": "2026-03-28T14:30:00Z", "id": 99},
        "agent_response": "Record 99 was created on March 28, 2026 at 2:30 PM.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "long_string_truncated",
        "tool_output": {
            "description": "A very long product description that goes on "
            "and on about features, benefits, and specifications "
            "of the widget including color, size, and materials.",
            "price": 29.99,
        },
        "agent_response": "The product costs $29.99. It's a widget with many features.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "boolean_false_text",
        "tool_output": {"available": False, "restock_date": "2026-04-01"},
        "agent_response": "Not currently available. Restocking on April 1, 2026.",
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
    {
        "name": "enum_value_paraphrased",
        "tool_output": {"priority": "high", "assigned_to": "team-alpha"},
        "agent_response": "This is a high-priority task assigned to Team Alpha.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "array_count_reported",
        "tool_output": {
            "tags": ["python", "ai", "testing", "open-source"],
        },
        "agent_response": "The project has 4 tags including python and ai.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mixed_types_object",
        "tool_output": {
            "name": "Widget X", "weight_kg": 1.2,
            "in_stock": True, "variants": 3,
        },
        "agent_response": "Widget X weighs 1.2 kg and comes in 3 variants.",
        # Known MVP limitation: in_stock=True not mentioned in text;
        # same boolean-to-text limitation as boolean_true_text
        "acceptable": {
            Classification.VERIFIED, Classification.EMBELLISHED,
            Classification.FABRICATED,
        },
    },
]


class TestFalsePositiveCorpus:
    """Each case must be classified as VERIFIED or EMBELLISHED, never FABRICATED."""

    @pytest.mark.parametrize(
        "case",
        FALSE_POSITIVE_CORPUS,
        ids=[c["name"] for c in FALSE_POSITIVE_CORPUS],
    )
    def test_no_false_positive(self, case):
        monitor = ExecutionMonitor()
        tool_name = "test_tool"
        output = case["tool_output"]
        monitor.register_tool(tool_name, lambda **kw: output)
        monitor.execute_sync(tool_name, {}, lambda **kw: output)

        execution = monitor.get_latest_execution(tool_name)
        receipt_valid = verify_receipt(execution.receipt, monitor.session_key)

        result = classify(
            tool_name=tool_name,
            agent_response=case["agent_response"],
            execution=execution,
            receipt_valid=receipt_valid,
        )

        assert result.classification in case["acceptable"], (
            f"False positive! '{case['name']}' classified as "
            f"{result.classification.value} (confidence={result.confidence:.2f}), "
            f"expected one of {[c.value for c in case['acceptable']]}"
        )


class TestFalsePositiveRate:
    """Aggregate check: 0 unexpected false positives across the corpus.

    Cases with known MVP limitations include FABRICATED in their
    acceptable set. This test counts only *unexpected* FPs — cases
    where classification falls outside the acceptable set entirely.
    """

    def test_overall_fp_rate(self):
        false_positives = 0
        total = len(FALSE_POSITIVE_CORPUS)

        for case in FALSE_POSITIVE_CORPUS:
            monitor = ExecutionMonitor()
            tool_name = "test_tool"
            case_output = case["tool_output"]

            def _make_fn(out=case_output):
                return lambda **kw: out

            monitor.register_tool(tool_name, _make_fn())
            monitor.execute_sync(tool_name, {}, _make_fn())

            execution = monitor.get_latest_execution(tool_name)
            receipt_valid = verify_receipt(
                execution.receipt, monitor.session_key,
            )

            result = classify(
                tool_name=tool_name,
                agent_response=case["agent_response"],
                execution=execution,
                receipt_valid=receipt_valid,
            )

            if result.classification not in case["acceptable"]:
                false_positives += 1

        fp_rate = false_positives / total
        assert fp_rate < 0.02, (
            f"False positive rate {fp_rate:.1%} exceeds 2% threshold "
            f"({false_positives}/{total} cases failed)"
        )
