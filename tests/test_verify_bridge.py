"""Tests for the verification bridge — the engine that closes the proxy gap."""

import json
import time

import pytest

from toolwitness.core.receipt import generate_receipt, generate_session_key
from toolwitness.core.types import ExecutionReceipt, ToolExecution
from toolwitness.storage.sqlite import SQLiteStorage
from toolwitness.verification.bridge import (
    BridgeVerificationResult,
    hydrate_execution,
    verify_agent_response,
)


@pytest.fixture
def storage(tmp_path):
    db = tmp_path / "test.db"
    s = SQLiteStorage(db)
    yield s
    s.close()


@pytest.fixture
def seeded_storage(storage):
    """Storage pre-loaded with a proxy-style execution."""
    session_key = generate_session_key()
    session_id = "proxy-session-001"
    storage.save_session(session_id, {"adapter": "mcp"}, source="mcp_proxy")

    receipt = generate_receipt(
        "get_weather",
        {"city": "Miami"},
        {"city": "Miami", "temp_f": 72, "conditions": "sunny", "humidity": 65},
        session_key,
    )
    execution = ToolExecution(
        tool_name="get_weather",
        args={"city": "Miami"},
        output={"city": "Miami", "temp_f": 72, "conditions": "sunny", "humidity": 65},
        receipt=receipt,
    )
    storage.save_execution(session_id, execution)

    receipt2 = generate_receipt(
        "get_file_info",
        {"path": "/test.md"},
        {"filename": "test.md", "size_bytes": 4096, "modified": "2026-03-27"},
        session_key,
    )
    execution2 = ToolExecution(
        tool_name="get_file_info",
        args={"path": "/test.md"},
        output={"filename": "test.md", "size_bytes": 4096, "modified": "2026-03-27"},
        receipt=receipt2,
    )
    storage.save_execution(session_id, execution2)

    return storage


class TestHydrateExecution:
    def test_hydrates_valid_row(self):
        receipt_data = {
            "receipt_id": "abc-123",
            "tool_name": "read_file",
            "args_hash": "h1",
            "output_hash": "h2",
            "timestamp": time.time(),
            "duration_ms": 42.0,
            "signature": "sig",
        }
        row = {
            "tool_name": "read_file",
            "args": json.dumps({"path": "/test"}),
            "output": json.dumps({"content": "hello"}),
            "receipt_json": json.dumps(receipt_data),
            "error": None,
        }
        result = hydrate_execution(row)
        assert result is not None
        assert result.tool_name == "read_file"
        assert result.output == {"content": "hello"}
        assert result.receipt.receipt_id == "abc-123"

    def test_returns_none_for_missing_receipt(self):
        row = {
            "tool_name": "read_file",
            "args": "{}",
            "output": "{}",
            "receipt_json": None,
        }
        assert hydrate_execution(row) is None

    def test_returns_none_for_invalid_json(self):
        row = {
            "tool_name": "read_file",
            "args": "{}",
            "output": "{}",
            "receipt_json": "not-valid-json",
        }
        assert hydrate_execution(row) is None

    def test_hydrates_string_output_as_string(self):
        receipt_data = {
            "receipt_id": "abc",
            "tool_name": "list_dir",
            "args_hash": "h1",
            "output_hash": "h2",
            "timestamp": time.time(),
            "duration_ms": 10.0,
            "signature": "sig",
        }
        row = {
            "tool_name": "list_dir",
            "args": "{}",
            "output": "file1.txt\nfile2.txt",
            "receipt_json": json.dumps(receipt_data),
        }
        result = hydrate_execution(row)
        assert result is not None
        assert result.output == "file1.txt\nfile2.txt"


class TestVerifyAgentResponse:
    def test_truthful_response_verified(self, seeded_storage):
        result = verify_agent_response(
            seeded_storage,
            "The weather in Miami is 72°F and sunny with 65% humidity. "
            "The file test.md is 4096 bytes, last modified 2026-03-27.",
            since_minutes=60,
            persist=False,
        )
        assert result.executions_checked == 2
        assert not result.has_failures
        for v in result.verifications:
            assert v.classification.value == "verified"

    def test_fabricated_response_detected(self, seeded_storage):
        result = verify_agent_response(
            seeded_storage,
            "The weather in New York is 45°F and rainy. "
            "The file test.md is 99999 bytes.",
            since_minutes=60,
            persist=False,
        )
        assert result.executions_checked == 2
        assert result.has_failures
        fabricated = [
            v for v in result.verifications
            if v.classification.value == "fabricated"
        ]
        assert len(fabricated) >= 1

    def test_no_executions_returns_empty(self, storage):
        result = verify_agent_response(
            storage,
            "Some text",
            since_minutes=5,
            persist=False,
        )
        assert result.executions_checked == 0
        assert not result.has_failures
        assert len(result.verifications) == 0

    def test_persist_saves_to_db(self, seeded_storage):
        result = verify_agent_response(
            seeded_storage,
            "Miami is 72°F sunny, 65% humidity. test.md is 4096 bytes.",
            since_minutes=60,
            persist=True,
        )
        assert result.session_id
        verifications = seeded_storage.query_verifications(
            session_id=result.session_id,
        )
        assert len(verifications) == 2

    def test_time_window_filters(self, storage):
        """Executions outside the time window are excluded."""
        session_key = generate_session_key()
        storage.save_session("old-session", {}, source="mcp_proxy")

        old_receipt = generate_receipt(
            "old_tool", {}, {"value": 42}, session_key,
            start_time=time.time() - 7200,
            end_time=time.time() - 7200,
        )
        old_exec = ToolExecution(
            tool_name="old_tool",
            args={},
            output={"value": 42},
            receipt=old_receipt,
        )
        storage.save_execution("old-session", old_exec)

        result = verify_agent_response(
            storage,
            "The value is 42",
            since_minutes=5,
            persist=False,
        )
        assert result.executions_checked == 0


class TestBridgeVerificationResult:
    def test_summary_counts(self):
        from toolwitness.core.types import Classification, VerificationResult

        result = BridgeVerificationResult(
            session_id="test",
            executions_checked=3,
            verifications=[
                VerificationResult("t1", Classification.VERIFIED, 0.99),
                VerificationResult("t2", Classification.FABRICATED, 0.85),
                VerificationResult("t3", Classification.VERIFIED, 0.95),
            ],
        )
        assert result.has_failures
        summary = result.summary
        assert summary["by_classification"]["verified"] == 2
        assert summary["by_classification"]["fabricated"] == 1

    def test_to_dict_serializable(self):
        from toolwitness.core.types import Classification, VerificationResult

        result = BridgeVerificationResult(
            session_id="test",
            executions_checked=1,
            verifications=[
                VerificationResult("t1", Classification.VERIFIED, 0.99),
            ],
        )
        d = result.to_dict()
        serialized = json.dumps(d)
        assert "verified" in serialized
