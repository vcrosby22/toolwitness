"""Tests for the classification engine using the fabrication fixture library."""

import pytest

from tests.fixtures import FABRICATION_FIXTURES
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
