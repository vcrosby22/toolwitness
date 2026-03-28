"""Tests for the MCP adapter — mocked, no real MCP server."""

from toolwitness.adapters.mcp import MCPMonitor, _extract_content
from toolwitness.core.types import Classification


class TestMCPMonitor:
    def test_tool_call_and_result(self):
        monitor = MCPMonitor()
        monitor.on_tool_call(params={
            "name": "get_weather",
            "arguments": {"city": "Miami"},
        }, request_id="req-1")
        monitor.on_tool_result(
            result={"city": "Miami", "temp_f": 72, "condition": "sunny"},
            request_id="req-1",
        )
        results = monitor.verify("Miami is 72°F and sunny.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_fabrication_detected(self):
        monitor = MCPMonitor()
        monitor.on_tool_call(params={
            "name": "get_weather",
            "arguments": {"city": "Miami"},
        }, request_id="r1")
        monitor.on_tool_result(
            result={"city": "Miami", "temp_f": 72},
            request_id="r1",
        )
        results = monitor.verify("Miami is 95°F.")
        assert results[0].classification == Classification.FABRICATED

    def test_correlate_by_tool_name(self):
        monitor = MCPMonitor()
        monitor.on_tool_call(params={
            "name": "search", "arguments": {"q": "test"},
        })
        monitor.on_tool_result(
            tool_name="search",
            result={"results": ["a", "b"]},
        )
        results = monitor.verify("Found results: a, b.")
        assert len(results) == 1

    def test_jsonrpc_message_request(self):
        monitor = MCPMonitor()
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": "42",
            "method": "tools/call",
            "params": {
                "name": "get_weather",
                "arguments": {"city": "Miami"},
            },
        })
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": "42",
            "result": {
                "content": {"city": "Miami", "temp_f": 72},
            },
        })
        results = monitor.verify("Miami is 72°F.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_get_failures(self):
        monitor = MCPMonitor()
        monitor.on_tool_call(params={
            "name": "get_weather",
            "arguments": {"city": "Miami"},
        })
        monitor.on_tool_result(
            tool_name="get_weather",
            result={"city": "Miami", "temp_f": 72},
        )
        failures = monitor.get_failures("Miami is 72°F.")
        assert len(failures) == 0

    def test_uncorrelated_result_warns(self, caplog):
        monitor = MCPMonitor()
        import logging
        with caplog.at_level(logging.WARNING, logger="toolwitness"):
            monitor.on_tool_result(result={"data": 42})

    def test_jsonrpc_error_response(self):
        monitor = MCPMonitor()
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": "99",
            "method": "tools/call",
            "params": {
                "name": "broken_tool",
                "arguments": {"x": 1},
            },
        })
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": "99",
            "error": {"code": -32000, "message": "tool failed"},
        })
        results = monitor.verify("The tool returned x=1.")
        assert len(results) == 1

    def test_jsonrpc_content_as_list(self):
        monitor = MCPMonitor()
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "get_weather",
                "arguments": {"city": "Miami"},
            },
        })
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": 7,
            "result": {
                "content": [
                    {"type": "text", "text": '{"city":"Miami","temp_f":72}'},
                ],
            },
        })
        results = monitor.verify("Miami is 72°F.")
        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

    def test_jsonrpc_integer_id_normalised(self):
        monitor = MCPMonitor()
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "ping", "arguments": {}},
        })
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": 5,
            "result": {"content": {"status": "ok"}},
        })
        results = monitor.verify("Status is ok.")
        assert len(results) == 1

    def test_non_tool_messages_ignored(self):
        monitor = MCPMonitor()
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        monitor.on_jsonrpc_message({
            "jsonrpc": "2.0",
            "id": "abc",
            "result": {"tools": []},
        })
        results = monitor.verify("anything")
        assert len(results) == 0


class TestExtractContent:
    def test_plain_dict(self):
        assert _extract_content({"temp": 72}) == {"temp": 72}

    def test_dict_with_content_dict(self):
        assert _extract_content({"content": {"a": 1}}) == {"a": 1}

    def test_dict_with_content_list_text(self):
        result = _extract_content({
            "content": [
                {"type": "text", "text": '{"x": 1}'},
            ],
        })
        assert result == {"x": 1}

    def test_dict_with_content_list_plain_text(self):
        result = _extract_content({
            "content": [
                {"type": "text", "text": "hello world"},
            ],
        })
        assert result == "hello world"

    def test_primitive(self):
        assert _extract_content(42) == 42
        assert _extract_content("hi") == "hi"
