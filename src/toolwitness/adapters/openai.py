"""OpenAI adapter — wraps an OpenAI client to monitor tool calls.

Usage::

    from openai import OpenAI
    from toolwitness.adapters.openai import wrap

    client = wrap(OpenAI())
    # Use client normally — ToolWitness intercepts tool calls transparently

The wrapped client records execution receipts for every tool call and
verifies agent responses against actual tool outputs.
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


class ToolCallRecord:
    """Record of a single OpenAI tool call extracted from a response."""

    def __init__(
        self,
        tool_call_id: str,
        function_name: str,
        arguments: dict[str, Any],
    ):
        self.tool_call_id = tool_call_id
        self.function_name = function_name
        self.arguments = arguments


class OpenAIMonitor:
    """Monitors tool calls in OpenAI chat completions.

    Sits between the assistant's tool_calls and the user's tool-result
    messages, recording receipts and enabling verification.
    """

    def __init__(
        self,
        storage: StorageBackend | None = None,
        session_id: str | None = None,
        agent_name: str | None = None,
        parent_session_id: str | None = None,
    ) -> None:
        self._monitor = ExecutionMonitor()
        self._pending_tool_calls: list[ToolCallRecord] = []
        self._tool_functions: dict[str, Callable[..., Any]] = {}
        self._storage = storage
        self._session_id = session_id or uuid.uuid4().hex[:16]
        self._agent_name = agent_name
        self._parent_session_id = parent_session_id

        if self._storage:
            self._storage.save_session(
                self._session_id,
                {"adapter": "openai"},
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

    def extract_tool_calls(self, response: Any) -> list[ToolCallRecord]:
        """Extract tool calls from an OpenAI ChatCompletion response.

        Works with both the object and dict representations.
        """
        records = []
        message = _get_message(response)
        if message is None:
            return records

        tool_calls = _get_tool_calls(message)
        for tc in tool_calls:
            tc_id = _get_attr_or_key(tc, "id", "")
            function = _get_attr_or_key(tc, "function", {})
            fn_name = _get_attr_or_key(function, "name", "")
            fn_args_raw = _get_attr_or_key(function, "arguments", "{}")

            try:
                fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
            except json.JSONDecodeError:
                fn_args = {"_raw": fn_args_raw}

            record = ToolCallRecord(
                tool_call_id=tc_id,
                function_name=fn_name,
                arguments=fn_args,
            )
            records.append(record)

        self._pending_tool_calls = records
        return records

    def execute_tool_calls(
        self,
        tool_calls: list[ToolCallRecord] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute pending tool calls and return OpenAI-format tool messages.

        Returns a list of dicts ready to append to the messages array::

            [{"role": "tool", "tool_call_id": "...", "content": "..."}]
        """
        calls = tool_calls or self._pending_tool_calls
        tool_messages: list[dict[str, Any]] = []

        for tc in calls:
            fn = self._tool_functions.get(tc.function_name)
            if fn is None:
                logger.warning(
                    "Tool '%s' not registered — skipping monitoring",
                    tc.function_name,
                )
                continue

            output, _receipt = self._monitor.execute_sync(
                tc.function_name, tc.arguments, fn
            )

            content = json.dumps(output, default=str) if not isinstance(output, str) else output
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.tool_call_id,
                "content": content,
            })
            self._persist_execution(tc.function_name)

        self._pending_tool_calls = []
        return tool_messages

    def record_tool_result(
        self,
        tool_name: str,
        args: dict[str, Any],
        output: Any,
    ) -> None:
        """Manually record a tool execution (when you handle execution yourself)."""
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
    """Wrap an OpenAI client with ToolWitness monitoring.

    Returns the same client with a `.toolwitness` attribute attached
    for accessing monitoring features.

    Args:
        client: An OpenAI client instance.
        storage: Optional storage backend for persistence.
        session_id: Optional session identifier.
        agent_name: Optional name for this agent in a multi-agent system.
        parent_session_id: Optional parent session for hierarchy tracking.
    """
    monitor = OpenAIMonitor(
        storage=storage,
        session_id=session_id,
        agent_name=agent_name,
        parent_session_id=parent_session_id,
    )
    client.toolwitness = monitor  # type: ignore[attr-defined]
    return client


def _get_attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    """Get attribute or dict key, supporting both object and dict responses."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_message(response: Any) -> Any:
    """Extract the first message from a ChatCompletion response."""
    if isinstance(response, dict):
        choices = response.get("choices", [])
        if choices:
            return choices[0].get("message")
        return None

    choices = getattr(response, "choices", [])
    if choices:
        return getattr(choices[0], "message", None)
    return None


def _get_tool_calls(message: Any) -> list[Any]:
    """Extract tool_calls from a message."""
    if isinstance(message, dict):
        return message.get("tool_calls") or []
    return getattr(message, "tool_calls", None) or []
