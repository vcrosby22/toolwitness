"""Tests for the ToolWitness MCP verification server."""

import json
import time

import pytest

from toolwitness.core.receipt import generate_receipt, generate_session_key
from toolwitness.core.types import ToolExecution
from toolwitness.storage.sqlite import SQLiteStorage


@pytest.fixture
def storage(tmp_path):
    db = tmp_path / "test.db"
    s = SQLiteStorage(db)
    yield s
    s.close()


@pytest.fixture
def seeded_db(tmp_path):
    """Create a seeded database and return its path."""
    db_path = tmp_path / "test_mcp.db"
    storage = SQLiteStorage(db_path)

    session_key = generate_session_key()
    storage.save_session("mcp-session-001", {"adapter": "mcp"}, source="mcp_proxy")

    receipt = generate_receipt(
        "get_weather",
        {"city": "Miami"},
        {"city": "Miami", "temp_f": 72, "conditions": "sunny"},
        session_key,
    )
    execution = ToolExecution(
        tool_name="get_weather",
        args={"city": "Miami"},
        output={"city": "Miami", "temp_f": 72, "conditions": "sunny"},
        receipt=receipt,
    )
    storage.save_execution("mcp-session-001", execution)
    storage.close()
    return str(db_path)


class TestMCPServerTools:
    """Test the MCP server tool functions directly (without MCP transport)."""

    def test_tw_verify_response_truthful(self, seeded_db):
        from toolwitness.mcp_server.server import configure, tw_verify_response

        configure(seeded_db)
        result = tw_verify_response(
            response_text="The weather in Miami is 72°F and sunny.",
            time_window_minutes=60,
        )
        assert result["executions_checked"] == 1
        assert not result["has_failures"]
        assert result["verifications"][0]["classification"] == "verified"

    def test_tw_verify_response_fabricated(self, seeded_db):
        from toolwitness.mcp_server.server import configure, tw_verify_response

        configure(seeded_db)
        result = tw_verify_response(
            response_text="The weather in New York is 45°F and rainy.",
            time_window_minutes=60,
        )
        assert result["executions_checked"] == 1
        assert result["has_failures"]
        assert result["verifications"][0]["classification"] == "fabricated"

    def test_tw_recent_executions(self, seeded_db):
        from toolwitness.mcp_server.server import configure, tw_recent_executions

        configure(seeded_db)
        result = tw_recent_executions(limit=10)
        assert result["count"] == 1
        assert result["executions"][0]["tool_name"] == "get_weather"
        assert "time_ago" in result["executions"][0]

    def test_tw_session_stats(self, seeded_db):
        from toolwitness.mcp_server.server import configure, tw_session_stats

        configure(seeded_db)
        result = tw_session_stats()
        assert "total_executions_recorded" in result
        assert result["total_executions_recorded"] >= 1

    def test_tw_verify_no_executions(self, tmp_path):
        from toolwitness.mcp_server.server import configure, tw_verify_response

        empty_db = str(tmp_path / "empty.db")
        SQLiteStorage(empty_db).close()
        configure(empty_db)

        result = tw_verify_response(
            response_text="Some response",
            time_window_minutes=5,
        )
        assert result["executions_checked"] == 0
        assert not result["has_failures"]


class TestMCPServerImport:
    """Verify the MCP server module structure."""

    def test_fastmcp_instance_exists(self):
        from toolwitness.mcp_server.server import mcp
        assert mcp is not None
        assert mcp.name == "toolwitness"

    def test_run_server_callable(self):
        from toolwitness.mcp_server.server import run_server
        assert callable(run_server)

    def test_configure_sets_path(self, tmp_path):
        from toolwitness.mcp_server import server
        server.configure(str(tmp_path / "custom.db"))
        assert server._db_path == str(tmp_path / "custom.db")
        server.configure(None)
