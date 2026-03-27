"""HMAC-SHA256 receipt generation and verification.

Session keys are generated per-session and held only by the SDK.
The model cannot access or forge these receipts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

from toolwitness.core.types import ExecutionReceipt


def generate_session_key() -> bytes:
    """Generate a cryptographically random 32-byte session key."""
    return secrets.token_bytes(32)


def _canonical_json(obj: Any) -> bytes:
    """Deterministic JSON serialization for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _hash_data(data: Any) -> str:
    """SHA-256 hash of canonically serialized data."""
    return hashlib.sha256(_canonical_json(data)).hexdigest()


def _sign_receipt(
    receipt_id: str,
    tool_name: str,
    args_hash: str,
    output_hash: str,
    timestamp: float,
    duration_ms: float,
    session_key: bytes,
) -> str:
    """HMAC-SHA256 signature over receipt fields."""
    message = f"{receipt_id}:{tool_name}:{args_hash}:{output_hash}:{timestamp}:{duration_ms}"
    return hmac.new(session_key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_receipt(
    tool_name: str,
    args: Any,
    output: Any,
    session_key: bytes,
    *,
    start_time: float | None = None,
    end_time: float | None = None,
) -> ExecutionReceipt:
    """Create a signed execution receipt for a tool call.

    Args:
        tool_name: Name of the tool that was called.
        args: Arguments passed to the tool.
        output: Return value from the tool.
        session_key: HMAC signing key for this session.
        start_time: When tool execution started (defaults to now).
        end_time: When tool execution finished (defaults to now).

    Returns:
        A signed ExecutionReceipt.
    """
    now = time.time()
    start = start_time if start_time is not None else now
    end = end_time if end_time is not None else now

    receipt_id = str(uuid.uuid4())
    args_hash = _hash_data(args)
    output_hash = _hash_data(output)
    duration_ms = (end - start) * 1000

    signature = _sign_receipt(
        receipt_id, tool_name, args_hash, output_hash, start, duration_ms, session_key
    )

    return ExecutionReceipt(
        receipt_id=receipt_id,
        tool_name=tool_name,
        args_hash=args_hash,
        output_hash=output_hash,
        timestamp=start,
        duration_ms=duration_ms,
        signature=signature,
    )


def verify_receipt(receipt: ExecutionReceipt, session_key: bytes) -> bool:
    """Verify that a receipt's signature is valid.

    Returns True if the HMAC matches, False if the receipt has been tampered with.
    """
    expected = _sign_receipt(
        receipt.receipt_id,
        receipt.tool_name,
        receipt.args_hash,
        receipt.output_hash,
        receipt.timestamp,
        receipt.duration_ms,
        session_key,
    )
    return hmac.compare_digest(receipt.signature, expected)
