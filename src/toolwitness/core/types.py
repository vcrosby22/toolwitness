"""Core data structures for ToolWitness."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Classification(Enum):
    """Result of verifying an agent's claim about a tool call."""

    VERIFIED = "verified"
    EMBELLISHED = "embellished"
    FABRICATED = "fabricated"
    SKIPPED = "skipped"
    UNMONITORED = "unmonitored"


@dataclass(frozen=True)
class ExecutionReceipt:
    """Cryptographic proof that a tool was actually called.

    The signature is an HMAC-SHA256 over the receipt fields using a session key
    held only by the SDK. The model cannot forge this.
    """

    receipt_id: str
    tool_name: str
    args_hash: str
    output_hash: str
    timestamp: float
    duration_ms: float
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "tool_name": self.tool_name,
            "args_hash": self.args_hash,
            "output_hash": self.output_hash,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionReceipt:
        return cls(
            receipt_id=data["receipt_id"],
            tool_name=data["tool_name"],
            args_hash=data["args_hash"],
            output_hash=data["output_hash"],
            timestamp=data["timestamp"],
            duration_ms=data["duration_ms"],
            signature=data["signature"],
        )


@dataclass
class VerificationResult:
    """Outcome of verifying an agent's response against recorded tool executions."""

    tool_name: str
    classification: Classification
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)
    receipt: ExecutionReceipt | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "classification": self.classification.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "receipt": self.receipt.to_dict() if self.receipt else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class ToolExecution:
    """Record of a single tool execution (input + output + receipt)."""

    tool_name: str
    args: dict[str, Any]
    output: Any
    receipt: ExecutionReceipt
    error: str | None = None


@dataclass
class Handoff:
    """Record of data crossing an agent boundary.

    When an orchestrator passes tool output to a child agent, the handoff
    links the source receipts to the target session so cross-agent
    verification can trace corruption back to its origin.
    """

    handoff_id: str
    source_session_id: str
    target_session_id: str
    data_summary: str
    source_receipt_ids: list[str] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "source_session_id": self.source_session_id,
            "target_session_id": self.target_session_id,
            "data_summary": self.data_summary,
            "source_receipt_ids": self.source_receipt_ids,
            "timestamp": self.timestamp,
        }


@dataclass
class HandoffVerificationResult:
    """Outcome of verifying an agent's response against handoff source data."""

    tool_name: str
    classification: Classification
    confidence: float
    source_session_id: str
    handoff_id: str
    corruption_chain: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "classification": self.classification.value,
            "confidence": self.confidence,
            "source_session_id": self.source_session_id,
            "handoff_id": self.handoff_id,
            "corruption_chain": self.corruption_chain,
            "evidence": self.evidence,
        }
