"""Tests for the OpenAI adapter — mocked, no real API keys."""

from toolwitness.adapters.openai import OpenAIMonitor, wrap
from toolwitness.core.types import Classification


def _mock_response(tool_calls: list[dict]) -> dict:
    """Build a dict that looks like an OpenAI ChatCompletion response."""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.get("id", f"call_{i}"),
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc.get("arguments", "{}"),
                        },
                    }
                    for i, tc in enumerate(tool_calls)
                ],
            }
        }],
    }


class TestOpenAIMonitor:
    def test_extract_tool_calls_from_dict(self):
        monitor = OpenAIMonitor()
        response = _mock_response([
            {"name": "get_weather", "arguments": '{"city": "Miami"}'},
        ])
        calls = monitor.extract_tool_calls(response)
        assert len(calls) == 1
        assert calls[0].function_name == "get_weather"
        assert calls[0].arguments == {"city": "Miami"}

    def test_extract_multiple_tool_calls(self):
        monitor = OpenAIMonitor()
        response = _mock_response([
            {"name": "get_weather", "arguments": '{"city": "Miami"}'},
            {"name": "get_time", "arguments": '{"timezone": "EST"}'},
        ])
        calls = monitor.extract_tool_calls(response)
        assert len(calls) == 2
        assert calls[0].function_name == "get_weather"
        assert calls[1].function_name == "get_time"

    def test_execute_tool_calls(self):
        monitor = OpenAIMonitor()

        def get_weather(city: str) -> dict:
            return {"city": city, "temp_f": 72, "condition": "sunny"}

        monitor.register_tool("get_weather", get_weather)

        response = _mock_response([
            {"id": "call_1", "name": "get_weather",
             "arguments": '{"city": "Miami"}'},
        ])
        monitor.extract_tool_calls(response)
        messages = monitor.execute_tool_calls()

        assert len(messages) == 1
        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "call_1"
        assert '"Miami"' in messages[0]["content"]

    def test_verify_accurate_response(self):
        monitor = OpenAIMonitor()
        monitor.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72, "condition": "sunny"},
        )

        response = _mock_response([
            {"id": "call_1", "name": "get_weather",
             "arguments": '{"city": "Miami"}'},
        ])
        monitor.extract_tool_calls(response)
        monitor.execute_tool_calls()

        results = monitor.verify("The weather in Miami is 72°F and sunny.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_verify_fabricated_response(self):
        monitor = OpenAIMonitor()
        monitor.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72, "condition": "sunny"},
        )

        response = _mock_response([
            {"id": "call_1", "name": "get_weather",
             "arguments": '{"city": "Miami"}'},
        ])
        monitor.extract_tool_calls(response)
        monitor.execute_tool_calls()

        results = monitor.verify("The weather in Miami is 95°F and rainy.")
        assert len(results) == 1
        assert results[0].classification == Classification.FABRICATED

    def test_get_failures(self):
        monitor = OpenAIMonitor()
        monitor.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72},
        )

        response = _mock_response([
            {"id": "c1", "name": "get_weather",
             "arguments": '{"city": "Miami"}'},
        ])
        monitor.extract_tool_calls(response)
        monitor.execute_tool_calls()

        failures = monitor.get_failures("Miami is 72°F.")
        assert len(failures) == 0

    def test_record_tool_result_manually(self):
        monitor = OpenAIMonitor()
        monitor.record_tool_result(
            "get_weather",
            {"city": "Miami"},
            {"city": "Miami", "temp_f": 72},
        )
        results = monitor.verify("Miami is 72°F.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_empty_response(self):
        monitor = OpenAIMonitor()
        calls = monitor.extract_tool_calls({"choices": []})
        assert calls == []

    def test_malformed_arguments(self):
        monitor = OpenAIMonitor()
        response = _mock_response([
            {"name": "test", "arguments": "not valid json"},
        ])
        calls = monitor.extract_tool_calls(response)
        assert calls[0].arguments == {"_raw": "not valid json"}


class TestOpenAIWrap:
    def test_wrap_attaches_monitor(self):
        class FakeClient:
            pass

        client = wrap(FakeClient())
        assert hasattr(client, "toolwitness")
        assert isinstance(client.toolwitness, OpenAIMonitor)

    def test_wrap_returns_same_client(self):
        class FakeClient:
            pass

        original = FakeClient()
        wrapped = wrap(original)
        assert wrapped is original
