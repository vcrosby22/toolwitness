"""Verification bridge — closes the gap between proxy-recorded executions
and agent response text.

Both the MCP verification server and the CLI ``verify`` command call
:func:`verify_agent_response` which:

1. Reads recent executions from storage
2. Hydrates them into :class:`ToolExecution` objects
3. Runs the classifier against the agent's response text
4. Optionally persists the verification results

This module exists so the verification logic lives in one place regardless
of entry point.
"""

from __future__ import annotations

import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from toolwitness.core.classifier import classify
from toolwitness.core.types import (
    Classification,
    ExecutionReceipt,
    ToolExecution,
    VerificationResult,
)
from toolwitness.storage.sqlite import SQLiteStorage


@dataclass
class BridgeVerificationResult:
    """Aggregate result from verifying a response against multiple executions."""

    verifications: list[VerificationResult] = field(default_factory=list)
    session_id: str = ""
    executions_checked: int = 0

    @property
    def has_failures(self) -> bool:
        return any(
            v.classification in (Classification.FABRICATED, Classification.SKIPPED)
            for v in self.verifications
        )

    @property
    def summary(self) -> dict[str, Any]:
        by_class: dict[str, int] = {}
        for v in self.verifications:
            key = v.classification.value
            by_class[key] = by_class.get(key, 0) + 1
        return {
            "session_id": self.session_id,
            "executions_checked": self.executions_checked,
            "total_verifications": len(self.verifications),
            "has_failures": self.has_failures,
            "by_classification": by_class,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary,
            "verifications": [v.to_dict() for v in self.verifications],
        }


def hydrate_execution(row: dict[str, Any]) -> ToolExecution | None:
    """Reconstruct a ToolExecution from a stored database row.

    Returns None if the row is missing required fields (receipt_json).
    """
    receipt_json_raw = row.get("receipt_json")
    if not receipt_json_raw:
        return None

    with contextlib.suppress(json.JSONDecodeError, TypeError, KeyError):
        receipt_data = json.loads(receipt_json_raw)
        receipt = ExecutionReceipt.from_dict(receipt_data)

        output = row.get("output")
        if isinstance(output, str):
            with contextlib.suppress(json.JSONDecodeError):
                output = json.loads(output)

        args = row.get("args", "{}")
        if isinstance(args, str):
            with contextlib.suppress(json.JSONDecodeError):
                args = json.loads(args)

        return ToolExecution(
            tool_name=row.get("tool_name", "unknown"),
            args=args if isinstance(args, dict) else {},
            output=output,
            receipt=receipt,
            error=row.get("error"),
        )

    return None


def verify_agent_response(
    storage: SQLiteStorage,
    response_text: str,
    *,
    since_minutes: float = 5.0,
    persist: bool = True,
    session_id: str | None = None,
) -> BridgeVerificationResult:
    """Verify an agent's response against recently recorded tool executions.

    Args:
        storage: Database connection with execution records.
        response_text: The agent's text response to verify.
        since_minutes: Look back window for executions (default 5 min).
        persist: Whether to save verification results to the database.
        session_id: Session ID for storing results. Auto-generated if None.

    Returns:
        BridgeVerificationResult with per-tool classifications.
    """
    since_ts = time.time() - (since_minutes * 60)
    raw_executions = storage.query_executions(since=since_ts, limit=200)

    if not raw_executions:
        return BridgeVerificationResult(
            session_id=session_id or "",
            executions_checked=0,
        )

    seen_tools: dict[str, ToolExecution] = {}
    for row in raw_executions:
        execution = hydrate_execution(row)
        if execution is None:
            continue
        if execution.tool_name not in seen_tools:
            seen_tools[execution.tool_name] = execution

    if not seen_tools:
        return BridgeVerificationResult(
            session_id=session_id or "",
            executions_checked=0,
        )

    verify_session_id = session_id or f"verify-{uuid.uuid4().hex[:12]}"

    if persist:
        storage.save_session(
            verify_session_id,
            {"source_type": "verification_bridge", "response_length": len(response_text)},
            source="verification",
        )

    result = BridgeVerificationResult(
        session_id=verify_session_id,
        executions_checked=len(seen_tools),
    )

    for tool_name, execution in seen_tools.items():
        # We don't have the proxy's session key, so we can't verify
        # the HMAC signature. Pass None to let the classifier treat
        # the receipt as present-but-unverifiable (structural match
        # still runs fully).
        receipt_valid = None

        verification = classify(
            tool_name=tool_name,
            agent_response=response_text,
            execution=execution,
            receipt_valid=receipt_valid,
        )
        result.verifications.append(verification)

        if persist:
            storage.save_verification(verify_session_id, verification)

    return result
