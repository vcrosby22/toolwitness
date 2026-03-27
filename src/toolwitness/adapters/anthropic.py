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
from collections.abc import Callable
from typing import Any

from toolwitness.core.classifier import classify
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import verify_receipt
from toolwitness.core.types import Classification, VerificationResult

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

    def __init__(self) -> None:
        self._monitor = ExecutionMonitor()
        self._pending_tool_uses: list[ToolUseRecord] = []
        self._tool_functions: dict[str, Callable[..., Any]] = {}

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

        return results

    def get_failures(
        self, agent_response: str
    ) -> list[VerificationResult]:
        """Verify and return only non-VERIFIED results."""
        return [
            r for r in self.verify(agent_response)
            if r.classification != Classification.VERIFIED
        ]


def wrap(client: Any) -> Any:
    """Wrap an Anthropic client with ToolWitness monitoring.

    Returns the same client with a `.toolwitness` attribute attached.

    Usage::

        from anthropic import Anthropic
        from toolwitness.adapters.anthropic import wrap

        client = wrap(Anthropic())

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            messages=messages,
            tools=tools,
        )

        # Extract and execute tool uses with monitoring
        tool_uses = client.toolwitness.extract_tool_uses(response)
        tool_results = client.toolwitness.execute_tool_uses()

        # After the next response, verify it
        results = client.toolwitness.verify(final_response_text)
    """
    monitor = AnthropicMonitor()
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
