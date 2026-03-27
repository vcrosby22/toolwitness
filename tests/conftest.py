"""Shared test fixtures."""

import pytest

from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import generate_session_key


@pytest.fixture
def session_key():
    return generate_session_key()


@pytest.fixture
def monitor(session_key):
    return ExecutionMonitor(session_key=session_key)


@pytest.fixture
def sample_tool():
    def get_weather(city: str) -> dict:
        return {"city": city, "temp_f": 72, "condition": "sunny"}
    return get_weather


@pytest.fixture
def sample_tool_registered(monitor, sample_tool):
    monitor.register_tool("get_weather", sample_tool)
    return monitor
