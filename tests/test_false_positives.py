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
        # stock=42 matches; True is missing but ratio=1.0 with mismatched=0 → VERIFIED
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "number_in_prose",
        "tool_output": {"users": 1523, "active": 847},
        "agent_response": "There are 1,523 users, of which 847 are active.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
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
        # Empty output recognition: all values empty/zero + "no results" → matched
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
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
        # Status code semantic table: 200 → "successful" matched
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
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
        # Magnitude: 1500000 / 1_000_000 = 1.5 → matched
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
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
        # Implicit zero: "No errors" matches errors=0
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
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
        # abs(value) fallback: -42.5 matches 42.5 in response
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
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
        # Bool NL: False matched via \bnot\b; ISO date is missing not mismatched
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
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
        # 3 of 4 fields match; in_stock=True missing but ratio=1.0 → VERIFIED
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    # --- Text-based tool outputs (non-JSON) ---
    {
        "name": "text_list_directory",
        "tool_output": (
            "[FILE] README.md\n[FILE] setup.py\n"
            "[DIR] src\n[DIR] tests\n[FILE] LICENSE"
        ),
        "agent_response": (
            "The directory contains README.md, setup.py, LICENSE, "
            "and two subdirectories: src and tests."
        ),
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "text_read_file_summary",
        "tool_output": (
            "# Project README\n\n"
            "This project implements a verification system.\n\n"
            "## Installation\n\npip install toolwitness\n\n"
            "## Usage\n\nRun `toolwitness check` to verify."
        ),
        "agent_response": (
            "The README describes a verification system. "
            "Install with pip install toolwitness, "
            "then run toolwitness check."
        ),
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "text_short_status_message",
        "tool_output": "Build succeeded. 142 tests passed, 0 failed.",
        "agent_response": "The build succeeded with all 142 tests passing.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "text_file_info_metadata",
        "tool_output": (
            "size: 8192\ncreated: Mon Mar 10 2026\n"
            "modified: Fri Mar 28 2026\nisFile: true\npermissions: 644"
        ),
        "agent_response": (
            "The file is 8192 bytes, last modified March 28 2026, "
            "with standard 644 permissions."
        ),
        # Month normalization: "Mar 28 2026" ↔ "March 28 2026"
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "text_error_message",
        "tool_output": "Error: ENOENT: no such file or directory, stat '/missing.txt'",
        "agent_response": "The file /missing.txt was not found (ENOENT error).",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    # --- MCP filesystem proxy realistic cases ---
    # These mirror what the proxy actually records and how agents respond.
    # After _parse_kv_text, get_file_info output becomes a dict; directory
    # listings and file contents stay as strings.
    {
        "name": "mcp_file_info_comma_size",
        "tool_output": {
            "size": 29931, "modified": "Mar 29 2026",
            "isFile": "true", "permissions": 644,
        },
        "agent_response": (
            "The file is 29,931 bytes with 644 permissions, "
            "last modified Mar 29 2026."
        ),
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_file_info_large_comma",
        "tool_output": {"size": 1523456, "permissions": 755},
        "agent_response": "The file is 1,523,456 bytes with 755 permissions.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_file_info_selective",
        "tool_output": {
            "size": 4096, "created": "Mar 13 2026",
            "modified": "Mar 28 2026", "isDirectory": "false",
            "isFile": "true", "permissions": 644,
        },
        "agent_response": "The file is 4,096 bytes, last modified Mar 28 2026.",
        # Two-pass: permissions=644 reclassified as omission since all
        # response numbers (4096, 28, 2026) are claimed by other tool values
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_file_info_date_expanded",
        "tool_output": {"size": 8192, "modified": "Mar 29 2026"},
        "agent_response": "The file is 8,192 bytes, modified on March 29, 2026.",
        # size=8192 matches; date missing but mismatched=0 → VERIFIED
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_file_info_natural_boolean",
        "tool_output": {
            "size": 2048, "isFile": "true", "isDirectory": "false",
        },
        "agent_response": "It's a 2,048-byte file.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_file_info_permissions_and_size",
        "tool_output": {
            "size": 6169, "permissions": 644, "isFile": "true",
        },
        "agent_response": "The file is 6,169 bytes with standard 644 permissions.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_file_info_size_round_kb",
        "tool_output": {"size": 8192, "permissions": 644},
        "agent_response": "The file is about 8 KB (644 permissions).",
        # Magnitude: 8192 / 1024 = 8.0 → matched
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_file_info_combined_report",
        "tool_output": {
            "size": 15360, "created": "Mar 10 2026",
            "modified": "Mar 28 2026", "permissions": 644,
        },
        "agent_response": (
            "The file is 15,360 bytes (644 permissions), "
            "created Mar 10 2026 and last modified Mar 28 2026."
        ),
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_dir_listing_summary",
        "tool_output": (
            "[FILE] README.md\n[FILE] setup.py\n[FILE] LICENSE\n"
            "[DIR] src\n[DIR] tests\n[FILE] pyproject.toml\n"
            "[FILE] Makefile\n[DIR] docs"
        ),
        "agent_response": (
            "The directory lists README.md, setup.py, LICENSE, "
            "pyproject.toml, Makefile, and directories src, tests, and docs."
        ),
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_dir_listing_count_only",
        "tool_output": (
            "[FILE] a.py\n[FILE] b.py\n[FILE] c.py\n"
            "[DIR] data\n[DIR] output"
        ),
        "agent_response": "The directory contains 3 files and 2 folders.",
        # Line-prefix counting: [FILE]×3 + [DIR]×2 matched to response numbers
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_read_file_paraphrase",
        "tool_output": (
            "# ToolWitness\n\n"
            "A verification system for AI agent tool use.\n\n"
            "## Installation\n\npip install toolwitness\n\n"
            "## Quick Start\n\nRun `toolwitness doctor` to check setup.\n"
            "Then configure your MCP servers and start verifying."
        ),
        "agent_response": (
            "The README describes ToolWitness as a verification system "
            "for AI agent tool use. You can install it with "
            "pip install toolwitness, then run toolwitness doctor "
            "to check setup."
        ),
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_search_results_subset",
        "tool_output": {
            "matches": [
                {"path": "/src/main.py", "line": 42},
                {"path": "/src/utils.py", "line": 10},
                {"path": "/tests/test_main.py", "line": 88},
            ],
        },
        "agent_response": (
            "Found 3 matches. The most relevant is /src/main.py at line 42."
        ),
        # BUG-02 list grouping: absent items (utils, test_main) → missing
        # not mismatched; 2 matched, 0 mismatched → VERIFIED
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_write_success",
        "tool_output": "Successfully wrote to /tmp/output.txt",
        "agent_response": "I've written the content to /tmp/output.txt.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
    },
    {
        "name": "mcp_file_info_six_digit_comma",
        "tool_output": {"size": 102400, "permissions": 644},
        "agent_response": "The file is 102,400 bytes with 644 permissions.",
        "acceptable": {Classification.VERIFIED, Classification.EMBELLISHED},
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
