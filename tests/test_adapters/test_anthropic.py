"""Tests for the Anthropic adapter — mocked, no real API keys."""

from toolwitness.adapters.anthropic import AnthropicMonitor, wrap
from toolwitness.core.types import Classification


def _mock_response(tool_uses: list[dict]) -> dict:
    """Build a dict that looks like an Anthropic Message response."""
    content = []
    for tu in tool_uses:
        content.append({
            "type": "tool_use",
            "id": tu.get("id", "toolu_01"),
            "name": tu["name"],
            "input": tu.get("input", {}),
        })
    return {"content": content, "role": "assistant", "stop_reason": "tool_use"}


class TestAnthropicMonitor:
    def test_extract_tool_uses(self):
        monitor = AnthropicMonitor()
        response = _mock_response([
            {"name": "get_weather", "input": {"city": "Miami"}},
        ])
        uses = monitor.extract_tool_uses(response)
        assert len(uses) == 1
        assert uses[0].name == "get_weather"
        assert uses[0].input_data == {"city": "Miami"}

    def test_extract_multiple_tool_uses(self):
        monitor = AnthropicMonitor()
        response = _mock_response([
            {"name": "get_weather", "input": {"city": "Miami"}},
            {"name": "get_time", "input": {"tz": "EST"}},
        ])
        uses = monitor.extract_tool_uses(response)
        assert len(uses) == 2

    def test_execute_tool_uses(self):
        monitor = AnthropicMonitor()
        monitor.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72, "condition": "sunny"},
        )

        response = _mock_response([
            {"id": "toolu_1", "name": "get_weather",
             "input": {"city": "Miami"}},
        ])
        monitor.extract_tool_uses(response)
        results = monitor.execute_tool_uses()

        assert len(results) == 1
        assert results[0]["type"] == "tool_result"
        assert results[0]["tool_use_id"] == "toolu_1"
        assert '"Miami"' in results[0]["content"]

    def test_verify_accurate_response(self):
        monitor = AnthropicMonitor()
        monitor.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72, "condition": "sunny"},
        )

        response = _mock_response([
            {"id": "toolu_1", "name": "get_weather",
             "input": {"city": "Miami"}},
        ])
        monitor.extract_tool_uses(response)
        monitor.execute_tool_uses()

        results = monitor.verify("The weather in Miami is 72°F and sunny.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_verify_fabricated_response(self):
        monitor = AnthropicMonitor()
        monitor.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72, "condition": "sunny"},
        )

        response = _mock_response([
            {"id": "toolu_1", "name": "get_weather",
             "input": {"city": "Miami"}},
        ])
        monitor.extract_tool_uses(response)
        monitor.execute_tool_uses()

        results = monitor.verify("Miami is 95°F and rainy.")
        assert len(results) == 1
        assert results[0].classification == Classification.FABRICATED

    def test_get_failures_empty_on_accurate(self):
        monitor = AnthropicMonitor()
        monitor.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72},
        )

        response = _mock_response([
            {"id": "t1", "name": "get_weather",
             "input": {"city": "Miami"}},
        ])
        monitor.extract_tool_uses(response)
        monitor.execute_tool_uses()

        failures = monitor.get_failures("Miami is 72°F.")
        assert len(failures) == 0

    def test_skips_text_blocks(self):
        monitor = AnthropicMonitor()
        response = {
            "content": [
                {"type": "text", "text": "Let me check that for you."},
                {"type": "tool_use", "id": "t1",
                 "name": "get_weather", "input": {"city": "Miami"}},
            ],
        }
        uses = monitor.extract_tool_uses(response)
        assert len(uses) == 1
        assert uses[0].name == "get_weather"


class TestAnthropicWrap:
    def test_wrap_attaches_monitor(self):
        class FakeClient:
            pass

        client = wrap(FakeClient())
        assert hasattr(client, "toolwitness")
        assert isinstance(client.toolwitness, AnthropicMonitor)
