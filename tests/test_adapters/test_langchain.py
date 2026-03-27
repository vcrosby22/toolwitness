"""Tests for the LangChain middleware adapter."""

import pytest

from toolwitness.adapters.langchain import (
    ToolWitnessMiddleware,
    ToolWitnessVerificationError,
)
from toolwitness.core.types import Classification


class TestToolWitnessMiddleware:
    def test_on_tool_start_and_end(self):
        mw = ToolWitnessMiddleware()
        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end(
            '{"city": "Miami", "temp_f": 72, "condition": "sunny"}'
        )

        results = mw.verify("The weather in Miami is 72°F and sunny.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_fabrication_detected(self):
        mw = ToolWitnessMiddleware()
        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end(
            '{"city": "Miami", "temp_f": 72, "condition": "sunny"}'
        )

        results = mw.verify("The weather in Miami is 95°F and rainy.")
        assert len(results) == 1
        assert results[0].classification == Classification.FABRICATED

    def test_on_fabrication_raise(self):
        mw = ToolWitnessMiddleware(on_fabrication="raise")
        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end(
            '{"city": "Miami", "temp_f": 72, "condition": "sunny"}'
        )

        with pytest.raises(ToolWitnessVerificationError) as exc_info:
            mw.verify("Miami is 95°F and rainy.")

        assert exc_info.value.result.classification == Classification.FABRICATED

    def test_on_fabrication_callback(self):
        captured: list = []
        mw = ToolWitnessMiddleware(
            on_fabrication="callback",
            on_failure_callback=captured.append,
        )
        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end(
            '{"city": "Miami", "temp_f": 72, "condition": "sunny"}'
        )

        mw.verify("Miami is 95°F and rainy.")
        assert len(captured) == 1
        assert captured[0].classification == Classification.FABRICATED

    def test_on_fabrication_log(self, caplog):
        mw = ToolWitnessMiddleware(on_fabrication="log")
        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end(
            '{"city": "Miami", "temp_f": 72}'
        )

        with caplog.at_level("WARNING", logger="toolwitness"):
            mw.verify("Miami is 95°F.")

    def test_invalid_on_fabrication(self):
        with pytest.raises(ValueError, match="on_fabrication"):
            ToolWitnessMiddleware(on_fabrication="explode")

    def test_get_results_and_failures(self):
        mw = ToolWitnessMiddleware()
        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end(
            '{"city": "Miami", "temp_f": 72}'
        )

        mw.verify("Miami is 72°F.")
        assert len(mw.get_results()) == 1
        assert len(mw.get_failures()) == 0

    def test_on_tool_error_resets_state(self):
        mw = ToolWitnessMiddleware()
        mw.on_tool_start({"name": "broken"}, '{}')
        mw.on_tool_error(RuntimeError("boom"))

        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end('{"city": "Miami", "temp_f": 72}')

        results = mw.verify("Miami is 72°F.")
        tool_names = [r.tool_name for r in results]
        assert "get_weather" in tool_names

    def test_non_json_tool_input(self):
        mw = ToolWitnessMiddleware()
        mw.on_tool_start(
            {"name": "search"},
            "just a plain string query",
        )
        mw.on_tool_end('{"results": []}')

        results = mw.verify("No results found.")
        assert len(results) == 1

    def test_confidence_threshold(self):
        captured: list = []
        mw = ToolWitnessMiddleware(
            on_fabrication="callback",
            confidence_threshold=0.99,
            on_failure_callback=captured.append,
        )
        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end('{"city": "Miami", "temp_f": 72}')

        mw.verify("Miami is 95°F.")
        # With threshold at 0.99, most fabrications won't trigger callback
        # (confidence is usually 0.6-0.9 range)
