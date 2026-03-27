"""Tests for the MCP adapter — mocked, no real MCP server."""

from toolwitness.adapters.mcp import MCPMonitor
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
