"""Tests for HMAC receipt generation and verification."""

from toolwitness.core.receipt import (
    _hash_data,
    generate_receipt,
    generate_session_key,
    verify_receipt,
)
from toolwitness.core.types import ExecutionReceipt


class TestReceiptGeneration:
    def test_generates_valid_receipt(self, session_key):
        receipt = generate_receipt(
            tool_name="get_weather",
            args={"city": "Miami"},
            output={"temp_f": 72},
            session_key=session_key,
        )
        assert isinstance(receipt, ExecutionReceipt)
        assert receipt.tool_name == "get_weather"
        assert receipt.receipt_id  # non-empty UUID
        assert receipt.signature  # non-empty HMAC

    def test_receipt_verifies_with_correct_key(self, session_key):
        receipt = generate_receipt(
            tool_name="get_weather",
            args={"city": "Miami"},
            output={"temp_f": 72},
            session_key=session_key,
        )
        assert verify_receipt(receipt, session_key) is True

    def test_receipt_fails_with_wrong_key(self, session_key):
        receipt = generate_receipt(
            tool_name="get_weather",
            args={"city": "Miami"},
            output={"temp_f": 72},
            session_key=session_key,
        )
        wrong_key = generate_session_key()
        assert verify_receipt(receipt, wrong_key) is False

    def test_tampered_receipt_fails_verification(self, session_key):
        receipt = generate_receipt(
            tool_name="get_weather",
            args={"city": "Miami"},
            output={"temp_f": 72},
            session_key=session_key,
        )
        tampered = ExecutionReceipt(
            receipt_id=receipt.receipt_id,
            tool_name="get_weather",
            args_hash=receipt.args_hash,
            output_hash=_hash_data({"temp_f": 99}),  # changed output
            timestamp=receipt.timestamp,
            duration_ms=receipt.duration_ms,
            signature=receipt.signature,  # old signature
        )
        assert verify_receipt(tampered, session_key) is False

    def test_different_args_produce_different_hashes(self, session_key):
        r1 = generate_receipt("t", {"a": 1}, "out", session_key)
        r2 = generate_receipt("t", {"a": 2}, "out", session_key)
        assert r1.args_hash != r2.args_hash

    def test_different_outputs_produce_different_hashes(self, session_key):
        r1 = generate_receipt("t", {"a": 1}, "out1", session_key)
        r2 = generate_receipt("t", {"a": 1}, "out2", session_key)
        assert r1.output_hash != r2.output_hash

    def test_receipt_ids_are_unique(self, session_key):
        r1 = generate_receipt("t", {}, "out", session_key)
        r2 = generate_receipt("t", {}, "out", session_key)
        assert r1.receipt_id != r2.receipt_id

    def test_receipt_round_trip_dict(self, session_key):
        receipt = generate_receipt("t", {"x": 1}, {"y": 2}, session_key)
        data = receipt.to_dict()
        restored = ExecutionReceipt.from_dict(data)
        assert restored == receipt
        assert verify_receipt(restored, session_key) is True

    def test_custom_timing(self, session_key):
        receipt = generate_receipt(
            "t", {}, "out", session_key,
            start_time=1000.0, end_time=1000.5,
        )
        assert receipt.timestamp == 1000.0
        assert abs(receipt.duration_ms - 500.0) < 0.01


class TestSessionKey:
    def test_key_is_32_bytes(self):
        key = generate_session_key()
        assert len(key) == 32

    def test_keys_are_unique(self):
        k1 = generate_session_key()
        k2 = generate_session_key()
        assert k1 != k2
