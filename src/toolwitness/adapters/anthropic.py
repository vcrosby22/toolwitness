"""Anthropic adapter — wraps an Anthropic client to monitor tool calls.

Usage::

    from anthropic import Anthropic
    from toolwitness.adapters.anthropic import wrap

    client = wrap(Anthropic())
    # Use client normally — ToolWitness intercepts tool calls transparently

Hooks between `tool_use` content blocks and `tool_result` blocks.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from toolwitness.core.classifier import classify
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import verify_receipt
from toolwitness.core.types import Classification, VerificationResult
from toolwitness.storage.base import StorageBackend

logger = logging.getLogger("toolwitness")


class ToolUseRecord:
    """Record of a single Anthropic tool_use block."""

    def __init__(
        self,
        tool_use_id: str,
        name: str,
        input_data: dict[str, Any],
    ):
        self.tool_use_id = tool_use_id
        self.name = name
        self.input_data = input_data


class AnthropicMonitor:
    """Monitors tool calls in Anthropic message responses.

    Sits between the assistant's tool_use blocks and the user's
    tool_result blocks, recording receipts and enabling verification.
    """

    def __init__(
        self,
        storage: StorageBackend | None = None,
        session_id: str | None = None,
        agent_name: str | None = None,
        parent_session_id: str | None = None,
    ) -> None:
        self._monitor = ExecutionMonitor()
        self._pending_tool_uses: list[ToolUseRecord] = []
        self._tool_functions: dict[str, Callable[..., Any]] = {}
        self._storage = storage
        self._session_id = session_id or uuid.uuid4().hex[:16]
        self._agent_name = agent_name
        self._parent_session_id = parent_session_id

        if self._storage:
            self._storage.save_session(
                self._session_id,
                {"adapter": "anthropic"},
                agent_name=agent_name,
                parent_session_id=parent_session_id,
            )

    @property
    def monitor(self) -> ExecutionMonitor:
        return self._monitor

    def register_tool(
        self, name: str, fn: Callable[..., Any]
    ) -> None:
        """Register a tool function for automatic execution."""
        self._tool_functions[name] = fn
        self._monitor.register_tool(name, fn)

    def extract_tool_uses(self, response: Any) -> list[ToolUseRecord]:
        """Extract tool_use blocks from an Anthropic Message response.

        Works with both object and dict representations.
        """
        records = []
        content = _get_content(response)

        for block in content:
            block_type = _get_attr_or_key(block, "type", "")
            if block_type != "tool_use":
                continue

            record = ToolUseRecord(
                tool_use_id=_get_attr_or_key(block, "id", ""),
                name=_get_attr_or_key(block, "name", ""),
                input_data=_get_attr_or_key(block, "input", {}),
            )
            records.append(record)

        self._pending_tool_uses = records
        return records

    def execute_tool_uses(
        self,
        tool_uses: list[ToolUseRecord] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute pending tool uses and return Anthropic-format tool_result blocks.

        Returns a list of content blocks ready for a user message::

            [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]
        """
        uses = tool_uses or self._pending_tool_uses
        result_blocks: list[dict[str, Any]] = []

        for tu in uses:
            fn = self._tool_functions.get(tu.name)
            if fn is None:
                logger.warning(
                    "Tool '%s' not registered — skipping monitoring",
                    tu.name,
                )
                continue

            output, _receipt = self._monitor.execute_sync(
                tu.name, tu.input_data, fn
            )

            content = (
                json.dumps(output, default=str)
                if not isinstance(output, str) else output
            )
            result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tu.tool_use_id,
                "content": content,
            })
            self._persist_execution(tu.name)

        self._pending_tool_uses = []
        return result_blocks

    def record_tool_result(
        self,
        tool_name: str,
        args: dict[str, Any],
        output: Any,
    ) -> None:
        """Manually record a tool execution."""
        self._monitor.register_tool(tool_name, lambda **kw: output)
        self._monitor.execute_sync(
            tool_name, args, lambda **kw: output
        )

    def verify(self, agent_response: str) -> list[VerificationResult]:
        """Verify the agent's response against recorded tool executions."""
        results: list[VerificationResult] = []

        for tool_name, executions in self._monitor.executions.items():
            if not executions:
                continue

            execution = executions[-1]
            receipt_valid = verify_receipt(
                execution.receipt, self._monitor.session_key
            )

            result = classify(
                tool_name=tool_name,
                agent_response=agent_response,
                execution=execution,
                receipt_valid=receipt_valid,
            )
            results.append(result)
            self._persist_verification(result)

        return results

    def _persist_execution(self, tool_name: str) -> None:
        if not self._storage:
            return
        execution = self._monitor.get_latest_execution(tool_name)
        if execution:
            try:
                self._storage.save_execution(self._session_id, execution)
            except Exception:
                logger.exception("Failed to persist execution")

    def _persist_verification(self, result: VerificationResult) -> None:
        if not self._storage:
            return
        try:
            self._storage.save_verification(self._session_id, result)
        except Exception:
            logger.exception("Failed to persist verification")

    def get_failures(
        self, agent_response: str
    ) -> list[VerificationResult]:
        """Verify and return only non-VERIFIED results."""
        return [
            r for r in self.verify(agent_response)
            if r.classification != Classification.VERIFIED
        ]


def wrap(
    client: Any,
    storage: StorageBackend | None = None,
    session_id: str | None = None,
    agent_name: str | None = None,
    parent_session_id: str | None = None,
) -> Any:
    """Wrap an Anthropic client with ToolWitness monitoring.

    Returns the same client with a `.toolwitness` attribute attached.

    Args:
        client: An Anthropic client instance.
        storage: Optional storage backend for persistence.
        session_id: Optional session identifier.
        agent_name: Optional name for this agent in a multi-agent system.
        parent_session_id: Optional parent session for hierarchy tracking.
    """
    monitor = AnthropicMonitor(
        storage=storage,
        session_id=session_id,
        agent_name=agent_name,
        parent_session_id=parent_session_id,
    )
    client.toolwitness = monitor  # type: ignore[attr-defined]
    return client


def _get_attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_content(response: Any) -> list[Any]:
    """Extract content blocks from an Anthropic Message response."""
    if isinstance(response, dict):
        return response.get("content", [])
    return getattr(response, "content", []) or []
