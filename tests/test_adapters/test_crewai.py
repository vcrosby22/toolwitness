"""Tests for the CrewAI adapter — mocked, no real CrewAI dependency."""

import json

from toolwitness.adapters.crewai import CrewAIMonitor, monitored_tool
from toolwitness.core.types import Classification


class TestCrewAIMonitor:
    def test_record_and_verify(self):
        monitor = CrewAIMonitor()
        monitor.record(
            "get_weather",
            {"city": "Miami"},
            {"city": "Miami", "temp_f": 72, "condition": "sunny"},
        )
        results = monitor.verify("Miami is 72°F and sunny.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_fabrication_detected(self):
        monitor = CrewAIMonitor()
        monitor.record(
            "get_weather",
            {"city": "Miami"},
            {"city": "Miami", "temp_f": 72},
        )
        results = monitor.verify("Miami is 95°F.")
        assert results[0].classification == Classification.FABRICATED


class TestMonitoredToolDecorator:
    def test_bare_decorator(self):
        @monitored_tool
        def get_weather(city: str) -> str:
            return json.dumps({"city": city, "temp_f": 72})

        output = get_weather(city="Miami")
        assert "Miami" in output
        assert hasattr(get_weather, "toolwitness")

    def test_decorator_with_monitor(self):
        monitor = CrewAIMonitor()

        @monitored_tool(monitor=monitor)
        def get_weather(city: str) -> str:
            return json.dumps({"city": city, "temp_f": 72})

        get_weather(city="Miami")
        results = monitor.verify("Miami is 72°F.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_decorator_preserves_function_name(self):
        @monitored_tool
        def my_special_tool(x: int) -> str:
            """A special tool."""
            return str(x)

        assert my_special_tool.__name__ == "my_special_tool"
        assert "special" in (my_special_tool.__doc__ or "")
