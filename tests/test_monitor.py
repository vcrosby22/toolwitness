"""Tests for ExecutionMonitor — execution wrapping + fail-open behavior."""

import pytest

from toolwitness.core.types import ToolExecution


class TestExecutionMonitor:
    def test_sync_execution_returns_output(self, sample_tool_registered):
        monitor = sample_tool_registered
        output, receipt = monitor.execute_sync("get_weather", {"city": "Miami"})
        assert output == {"city": "Miami", "temp_f": 72, "condition": "sunny"}
        assert receipt is not None
        assert receipt.tool_name == "get_weather"

    def test_sync_execution_records_receipt(self, sample_tool_registered):
        monitor = sample_tool_registered
        monitor.execute_sync("get_weather", {"city": "Miami"})
        execs = monitor.get_executions("get_weather")
        assert len(execs) == 1
        assert isinstance(execs[0], ToolExecution)
        assert execs[0].output == {"city": "Miami", "temp_f": 72, "condition": "sunny"}

    @pytest.mark.asyncio
    async def test_async_execution(self, monitor):
        async def async_weather(city: str) -> dict:
            return {"city": city, "temp_f": 72}

        monitor.register_tool("async_weather", async_weather)
        output, receipt = await monitor.execute("async_weather", {"city": "NYC"})
        assert output == {"city": "NYC", "temp_f": 72}
        assert receipt is not None

    def test_unknown_tool_raises(self, monitor):
        with pytest.raises(ValueError, match="Unknown tool"):
            monitor.execute_sync("nonexistent", {})

    def test_tool_exception_propagates(self, monitor):
        def bad_tool() -> None:
            raise RuntimeError("tool broke")

        monitor.register_tool("bad_tool", bad_tool)
        with pytest.raises(RuntimeError, match="tool broke"):
            monitor.execute_sync("bad_tool", {})

    def test_tool_exception_still_records(self, monitor):
        """Fail-open: even when the tool throws, we record what we can."""
        def bad_tool() -> None:
            raise RuntimeError("tool broke")

        import contextlib

        monitor.register_tool("bad_tool", bad_tool)
        with contextlib.suppress(RuntimeError):
            monitor.execute_sync("bad_tool", {})

        execs = monitor.get_executions("bad_tool")
        assert len(execs) == 1
        assert execs[0].error is not None
        assert "tool broke" in execs[0].error

    def test_multiple_executions_recorded(self, sample_tool_registered):
        monitor = sample_tool_registered
        monitor.execute_sync("get_weather", {"city": "Miami"})
        monitor.execute_sync("get_weather", {"city": "NYC"})
        assert len(monitor.get_executions("get_weather")) == 2

    def test_get_latest_execution(self, sample_tool_registered):
        monitor = sample_tool_registered
        monitor.execute_sync("get_weather", {"city": "Miami"})
        monitor.execute_sync("get_weather", {"city": "NYC"})
        latest = monitor.get_latest_execution("get_weather")
        assert latest is not None
        assert latest.args == {"city": "NYC"}

    def test_get_latest_execution_none(self, monitor):
        assert monitor.get_latest_execution("nonexistent") is None

    def test_pass_tool_fn_directly(self, monitor):
        def inline_tool(x: int) -> int:
            return x * 2

        output, receipt = monitor.execute_sync(
            "inline_tool", {"x": 5}, tool_fn=inline_tool
        )
        assert output == 10
        assert receipt is not None
