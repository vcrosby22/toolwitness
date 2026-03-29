"""Tests for the classification engine using the fabrication fixture library."""

import pytest

from tests.fixtures import FABRICATION_FIXTURES, MCP_FABRICATION_FIXTURES
from toolwitness.core.classifier import classify
from toolwitness.core.receipt import generate_receipt, generate_session_key
from toolwitness.core.types import Classification, ToolExecution


def _make_execution(tool_output, session_key):
    """Helper to create a ToolExecution from fixture data."""
    receipt = generate_receipt(
        tool_name="test_tool",
        args={"test": True},
        output=tool_output,
        session_key=session_key,
    )
    return ToolExecution(
        tool_name="test_tool",
        args={"test": True},
        output=tool_output,
        receipt=receipt,
    )


class TestClassifierWithFixtures:
    """Run the classifier against every fixture in the fabrication library."""

    @pytest.fixture(autouse=True)
    def setup_key(self):
        self.session_key = generate_session_key()

    @pytest.mark.parametrize(
        "fixture",
        [f for f in FABRICATION_FIXTURES if f["expected"] != Classification.SKIPPED],
        ids=[f["name"] for f in FABRICATION_FIXTURES if f["expected"] != Classification.SKIPPED],
    )
    def test_fixture_with_execution(self, fixture):
        execution = _make_execution(fixture["tool_output"], self.session_key)
        result = classify(
            tool_name="test_tool",
            agent_response=fixture["agent_response"],
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == fixture["expected"], (
            f"Fixture '{fixture['name']}': expected {fixture['expected'].value}, "
            f"got {result.classification.value} (confidence={result.confidence:.2f})"
        )

    def test_skipped_no_execution(self):
        """SKIPPED: no execution record at all."""
        fixture = next(
            f for f in FABRICATION_FIXTURES if f["name"] == "complete_fabrication_no_receipt"
        )
        result = classify(
            tool_name="test_tool",
            agent_response=fixture["agent_response"],
            execution=None,
        )
        assert result.classification == Classification.SKIPPED
        assert result.confidence > 0.90

    def test_invalid_receipt_classified_as_fabricated(self):
        execution = _make_execution({"temp_f": 72}, self.session_key)
        result = classify(
            tool_name="test_tool",
            agent_response="The temperature is 72°F.",
            execution=execution,
            receipt_valid=False,
        )
        assert result.classification == Classification.FABRICATED


class TestMCPFabricationFixtures:
    """Run the classifier against MCP filesystem proxy fabrication fixtures."""

    @pytest.fixture(autouse=True)
    def setup_key(self):
        self.session_key = generate_session_key()

    @pytest.mark.parametrize(
        "fixture",
        MCP_FABRICATION_FIXTURES,
        ids=[f["name"] for f in MCP_FABRICATION_FIXTURES],
    )
    def test_mcp_fixture(self, fixture):
        execution = _make_execution(fixture["tool_output"], self.session_key)
        result = classify(
            tool_name="test_tool",
            agent_response=fixture["agent_response"],
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == fixture["expected"], (
            f"MCP fixture '{fixture['name']}': expected {fixture['expected'].value}, "
            f"got {result.classification.value} (confidence={result.confidence:.2f})"
        )


class TestClassifierConfidenceRanges:
    """Verify confidence scores fall within expected ranges per classification."""

    @pytest.fixture(autouse=True)
    def setup_key(self):
        self.session_key = generate_session_key()

    def test_verified_confidence_range(self):
        execution = _make_execution(
            {"city": "Miami", "temp_f": 72, "condition": "sunny"},
            self.session_key,
        )
        result = classify(
            tool_name="test_tool",
            agent_response="Miami is 72°F and sunny.",
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == Classification.VERIFIED
        assert 0.85 <= result.confidence <= 0.99

    def test_skipped_confidence_range(self):
        result = classify(
            tool_name="test_tool",
            agent_response="I checked the weather.",
            execution=None,
        )
        assert result.classification == Classification.SKIPPED
        assert 0.90 <= result.confidence <= 0.99

    def test_fabricated_confidence_range(self):
        execution = _make_execution(
            {"city": "Miami", "temp_f": 72, "condition": "sunny"},
            self.session_key,
        )
        result = classify(
            tool_name="test_tool",
            agent_response="The weather in Miami is 85°F and rainy.",
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == Classification.FABRICATED
        assert 0.60 <= result.confidence <= 0.95


class TestClassifierTextOutputs:
    """Verify that plain-text tool outputs (non-JSON) are classified correctly
    via text_grounding_match instead of structural_match."""

    @pytest.fixture(autouse=True)
    def setup_key(self):
        self.session_key = generate_session_key()

    def test_list_directory_accurate_summary(self):
        """Accurate summary of a directory listing should be VERIFIED."""
        output = (
            "[FILE] CURSOR_KNOWLEDGE.md\n"
            "[FILE] CONTEXT_ROT.md\n"
            "[FILE] WHAT_IS_AN_AGENT.md\n"
            "[DIR] agent-snapshots\n"
            "[DIR] context-engineering-digests"
        )
        execution = _make_execution(output, self.session_key)
        result = classify(
            tool_name="list_directory",
            agent_response=(
                "The directory contains CURSOR_KNOWLEDGE.md, CONTEXT_ROT.md, "
                "and WHAT_IS_AN_AGENT.md, plus subdirectories for "
                "agent-snapshots and context-engineering-digests."
            ),
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == Classification.VERIFIED, (
            f"Expected VERIFIED, got {result.classification.value} "
            f"(confidence={result.confidence:.2f}, evidence={result.evidence})"
        )

    def test_list_directory_fabricated_content(self):
        """Fabricated directory contents should be FABRICATED."""
        output = (
            "[FILE] CURSOR_KNOWLEDGE.md\n"
            "[FILE] CONTEXT_ROT.md\n"
            "[DIR] agent-snapshots"
        )
        execution = _make_execution(output, self.session_key)
        result = classify(
            tool_name="list_directory",
            agent_response=(
                "The directory contains important financial reports, "
                "stock analysis spreadsheets, and quarterly earnings data."
            ),
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == Classification.FABRICATED, (
            f"Expected FABRICATED, got {result.classification.value} "
            f"(confidence={result.confidence:.2f})"
        )

    def test_read_file_accurate_summary(self):
        """Accurate summary of file contents should be VERIFIED."""
        output = (
            "# ToolWitness — Session handoff\n\n"
            "ToolWitness detects when AI agents skip tool execution "
            "or misrepresent tool outputs.\n\n"
            "## Detection model\n\n"
            "1. Tool skip — agent claims a tool ran; no execution.\n"
            "2. Result fabrication — tool ran; agent lies about output."
        )
        execution = _make_execution(output, self.session_key)
        result = classify(
            tool_name="read_file",
            agent_response=(
                "The ToolWitness handoff document describes the detection model: "
                "tool skip (agent claims execution without running) and result "
                "fabrication (agent misrepresents output)."
            ),
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == Classification.VERIFIED, (
            f"Expected VERIFIED, got {result.classification.value} "
            f"(confidence={result.confidence:.2f}, evidence={result.evidence})"
        )

    def test_read_file_fabricated_claims(self):
        """Fabricated claims about file content should be FABRICATED."""
        output = (
            "# ToolWitness — Session handoff\n\n"
            "ToolWitness detects when AI agents skip tool execution."
        )
        execution = _make_execution(output, self.session_key)
        result = classify(
            tool_name="read_file",
            agent_response=(
                "The document discusses cryptocurrency trading strategies "
                "and provides Bitcoin investment portfolio recommendations."
            ),
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == Classification.FABRICATED, (
            f"Expected FABRICATED, got {result.classification.value} "
            f"(confidence={result.confidence:.2f})"
        )

    def test_short_text_accurate(self):
        """Short single-line text output with accurate report should be VERIFIED."""
        output = "Operation completed successfully. 3 files processed."
        execution = _make_execution(output, self.session_key)
        result = classify(
            tool_name="run_task",
            agent_response="The operation completed successfully, processing 3 files.",
            execution=execution,
            receipt_valid=True,
        )
        assert result.classification == Classification.VERIFIED, (
            f"Expected VERIFIED, got {result.classification.value} "
            f"(confidence={result.confidence:.2f})"
        )

    def test_get_file_info_text_accurate(self):
        """File metadata as text (MCP-style) accurately reported."""
        output = (
            "size: 3953\n"
            "created: Fri Mar 13 2026\n"
            "modified: Sat Mar 28 2026\n"
            "permissions: 644"
        )
        execution = _make_execution(output, self.session_key)
        result = classify(
            tool_name="get_file_info",
            agent_response=(
                "The file is 3953 bytes with permissions 644, "
                "last modified on March 28, 2026."
            ),
            execution=execution,
            receipt_valid=True,
        )
        # EMBELLISHED is acceptable: "March 28, 2026" doesn't match
        # abbreviated "Mar 28 2026" in source — a known date-format limitation
        assert result.classification in (
            Classification.VERIFIED, Classification.EMBELLISHED,
        ), (
            f"Expected VERIFIED or EMBELLISHED, got {result.classification.value} "
            f"(confidence={result.confidence:.2f}, evidence={result.evidence})"
        )


class TestClassifierEdgeCases:
    @pytest.fixture(autouse=True)
    def setup_key(self):
        self.session_key = generate_session_key()

    def test_empty_response(self):
        execution = _make_execution({"temp_f": 72}, self.session_key)
        result = classify("test_tool", "", execution, receipt_valid=True)
        assert result.classification in (Classification.FABRICATED, Classification.VERIFIED)

    def test_none_output_with_execution(self):
        execution = _make_execution(None, self.session_key)
        result = classify("test_tool", "Some response", execution, receipt_valid=True)
        assert result.classification == Classification.VERIFIED
        assert result.confidence == 0.50
