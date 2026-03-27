"""Tests for multi-turn chain verification."""

from toolwitness.core.types import ExecutionReceipt, ToolExecution
from toolwitness.verification.chain import verify_chain


def _make_execution(
    tool_name: str,
    args: dict,
    output: dict,
) -> ToolExecution:
    receipt = ExecutionReceipt(
        receipt_id="r1",
        tool_name=tool_name,
        args_hash="abc",
        output_hash="def",
        timestamp=1.0,
        duration_ms=1.0,
        signature="sig",
    )
    return ToolExecution(
        tool_name=tool_name,
        args=args,
        output=output,
        receipt=receipt,
    )


class TestChainVerification:
    def test_intact_chain(self):
        """Tool B uses a value from Tool A's output."""
        exec_a = _make_execution(
            "get_user", {"id": 1},
            {"name": "Alice", "email": "alice@example.com"},
        )
        exec_b = _make_execution(
            "send_email",
            {"to": "alice@example.com", "subject": "Hello"},
            {"sent": True},
        )
        result = verify_chain([exec_a, exec_b])
        assert result.is_intact
        assert result.break_count == 0
        assert result.chain_length == 2

    def test_broken_chain_strict(self):
        """Tool B uses a value NOT from Tool A's output (strict mode)."""
        exec_a = _make_execution(
            "get_user", {"id": 1},
            {"name": "Alice", "email": "alice@example.com"},
        )
        exec_b = _make_execution(
            "send_email",
            {"to": "bob@example.com", "subject": "Hello"},
            {"sent": True},
        )
        result = verify_chain([exec_a, exec_b], strict=True)
        assert not result.is_intact
        assert result.break_count > 0

    def test_single_execution(self):
        exec_a = _make_execution("get_user", {"id": 1}, {"name": "Alice"})
        result = verify_chain([exec_a])
        assert result.is_intact
        assert result.chain_length == 1

    def test_empty_chain(self):
        result = verify_chain([])
        assert result.is_intact
        assert result.chain_length == 0

    def test_numeric_chain(self):
        """Numeric value from A appears in B's args."""
        exec_a = _make_execution(
            "calculate_price", {"item": "widget"},
            {"price": 49.99, "currency": "USD"},
        )
        exec_b = _make_execution(
            "charge_payment",
            {"amount": 49.99, "currency": "USD"},
            {"success": True},
        )
        result = verify_chain([exec_a, exec_b])
        assert result.is_intact

    def test_three_tool_chain(self):
        exec_a = _make_execution(
            "search", {"q": "flights"},
            {"flight_id": "UA123", "price": 299},
        )
        exec_b = _make_execution(
            "book_flight",
            {"flight_id": "UA123", "price": 299},
            {"booking_id": "BK-456", "total": 299},
        )
        exec_c = _make_execution(
            "send_confirmation",
            {"booking_id": "BK-456", "total": 299},
            {"sent": True},
        )
        result = verify_chain([exec_a, exec_b, exec_c])
        assert result.is_intact
        assert result.chain_length == 3

    def test_to_dict(self):
        result = verify_chain([])
        d = result.to_dict()
        assert d["chain_length"] == 0
        assert d["is_intact"] is True
        assert d["breaks"] == []
