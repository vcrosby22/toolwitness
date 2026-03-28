"""MCP adapter — monitors tool calls in Model Context Protocol sessions.

Intercepts `tools/call` JSON-RPC messages between an MCP Client and Server.
Works as a pass-through proxy: the real tool execution still happens on the
MCP server; ToolWitness records the arguments and results for verification.

Usage::

    from toolwitness.adapters.mcp import MCPMonitor

    monitor = MCPMonitor()
    # Intercept outgoing tool call request
    monitor.on_tool_call(method="tools/call", params={
        "name": "get_weather",
        "arguments": {"city": "Miami"},
    })
    # Intercept the response
    monitor.on_tool_result(tool_name="get_weather", result={
        "city": "Miami", "temp_f": 72,
    })
    # Verify agent's use of the result
    results = monitor.verify("Miami is 72°F.")
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from typing import Any

from toolwitness.core.classifier import classify
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import verify_receipt
from toolwitness.core.types import Classification, VerificationResult
from toolwitness.storage.base import StorageBackend

logger = logging.getLogger("toolwitness")


def _extract_content(result_data: Any) -> Any:
    """Normalise an MCP result into a value suitable for verification.

    MCP servers may return ``content`` as:
    - a dict with a ``content`` key holding a list of parts
    - a dict with a ``content`` key holding a plain dict
    - a plain dict (no ``content`` key)
    - a primitive value

    When ``content`` is a list of text parts, merge their ``text``
    fields into a single string (or parse as JSON if possible).
    """
    if not isinstance(result_data, dict):
        return result_data

    content = result_data.get("content", result_data)

    if isinstance(content, list):
        texts = [
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        if not texts:
            return content
        merged = "\n".join(texts) if len(texts) > 1 else texts[0]
        try:
            return json.loads(merged)
        except (json.JSONDecodeError, TypeError):
            return merged

    return content


class MCPMonitor:
    """Monitors tool calls in MCP (Model Context Protocol) sessions.

    Designed as a pass-through observer: it does not execute tools itself
    (the MCP server does that), but records the call/result pairs for
    verification.
    """

    def __init__(
        self,
        storage: StorageBackend | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._monitor = ExecutionMonitor()
        self._storage = storage
        self._session_id = session_id or uuid.uuid4().hex[:16]
        self._pending_calls: dict[str, dict[str, Any]] = {}

        session_meta: dict[str, Any] = {"adapter": "mcp"}
        if metadata:
            session_meta.update(metadata)

        if self._storage:
            self._storage.save_session(self._session_id, session_meta)

    @property
    def monitor(self) -> ExecutionMonitor:
        return self._monitor

    def on_tool_call(
        self,
        *,
        method: str = "tools/call",
        params: dict[str, Any],
        request_id: str | None = None,
    ) -> None:
        """Record an outgoing tools/call request.

        Args:
            method: JSON-RPC method (should be "tools/call").
            params: Must contain "name" and "arguments" keys.
            request_id: JSON-RPC request ID for correlating with response.
        """
        tool_name = params.get("name", "unknown")
        arguments = params.get("arguments", {})
        req_id = request_id or uuid.uuid4().hex[:12]

        self._pending_calls[req_id] = {
            "tool_name": tool_name,
            "arguments": arguments,
        }

    def on_tool_result(
        self,
        *,
        tool_name: str | None = None,
        result: Any,
        request_id: str | None = None,
        is_error: bool = False,
    ) -> None:
        """Record a tool result from the MCP server.

        Can be correlated by request_id or tool_name. If both are given,
        request_id takes precedence.
        """
        call_info: dict[str, Any] | None = None

        if request_id and request_id in self._pending_calls:
            call_info = self._pending_calls.pop(request_id)
        elif tool_name:
            for rid, info in list(self._pending_calls.items()):
                if info["tool_name"] == tool_name:
                    call_info = self._pending_calls.pop(rid)
                    break

        if call_info is None:
            if tool_name:
                call_info = {"tool_name": tool_name, "arguments": {}}
            else:
                logger.warning(
                    "Cannot correlate MCP tool result — no matching call"
                )
                return

        name = call_info["tool_name"]
        args = call_info["arguments"]

        parsed_result = result
        if isinstance(result, str):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                parsed_result = json.loads(result)

        self._monitor.register_tool(name, lambda **kw: parsed_result)
        self._monitor.execute_sync(name, args, lambda **kw: parsed_result)

        self._persist_execution(name)

    def on_jsonrpc_message(self, message: dict[str, Any]) -> None:
        """Process a raw JSON-RPC message (request or response).

        Convenience method for intercepting all messages in a proxy.
        Handles both successful results and error responses, and
        normalises MCP ``content`` lists into a single merged dict.
        """
        method = message.get("method")
        if method == "tools/call":
            params = message.get("params", {})
            req_id = str(message.get("id", ""))
            self.on_tool_call(
                method=method, params=params, request_id=req_id,
            )
            return

        msg_id = message.get("id")
        if msg_id is None:
            return
        req_id = str(msg_id)

        if req_id not in self._pending_calls:
            return

        if "error" in message:
            error = message["error"]
            self.on_tool_result(
                result={"error": error},
                request_id=req_id,
                is_error=True,
            )
            return

        if "result" in message:
            result_data = message["result"]
            content = _extract_content(result_data)
            self.on_tool_result(
                result=content, request_id=req_id,
            )

    def verify(self, agent_response: str) -> list[VerificationResult]:
        """Verify the agent's response against recorded tool results."""
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

    def get_failures(
        self, agent_response: str,
    ) -> list[VerificationResult]:
        return [
            r for r in self.verify(agent_response)
            if r.classification != Classification.VERIFIED
        ]

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
