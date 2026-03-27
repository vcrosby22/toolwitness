"""ExecutionMonitor — wraps tool execution, records receipts.

Fail-open: if receipt generation or monitoring throws, the tool call still
proceeds normally. The result is classified as UNMONITORED and an internal
error is logged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from toolwitness.core.receipt import generate_receipt, generate_session_key
from toolwitness.core.types import ExecutionReceipt, ToolExecution

logger = logging.getLogger("toolwitness")

INTERNAL_ERROR_CODE = "TOOLWITNESS_INTERNAL_ERROR"


class ExecutionMonitor:
    """Monitors tool executions and generates cryptographic receipts.

    Each monitor instance holds a session key that lives only in-process.
    """

    def __init__(self, session_key: bytes | None = None):
        self._session_key = session_key or generate_session_key()
        self._executions: dict[str, list[ToolExecution]] = {}
        self._tools: dict[str, Callable[..., Any]] = {}

    @property
    def session_key(self) -> bytes:
        return self._session_key

    @property
    def executions(self) -> dict[str, list[ToolExecution]]:
        return dict(self._executions)

    def register_tool(self, name: str, fn: Callable[..., Any]) -> None:
        """Register a tool function for monitoring."""
        self._tools[name] = fn

    def get_executions(self, tool_name: str) -> list[ToolExecution]:
        """Get all recorded executions for a tool."""
        return list(self._executions.get(tool_name, []))

    def get_latest_execution(self, tool_name: str) -> ToolExecution | None:
        """Get the most recent execution for a tool, or None."""
        execs = self._executions.get(tool_name, [])
        return execs[-1] if execs else None

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_fn: Callable[..., Any] | None = None,
    ) -> tuple[Any, ExecutionReceipt | None]:
        """Execute a tool and record a receipt. Async-first.

        Returns (tool_output, receipt). If monitoring fails internally,
        the tool output is still returned and receipt is None.
        """
        fn = tool_fn or self._tools.get(tool_name)
        if fn is None:
            raise ValueError(f"Unknown tool: {tool_name}. Register it first or pass tool_fn.")

        start_time = time.time()
        output = None
        error_msg = None

        try:
            if asyncio.iscoroutinefunction(fn):
                output = await fn(**args)
            else:
                output = fn(**args)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            raise
        finally:
            end_time = time.time()
            receipt = self._try_generate_receipt(
                tool_name, args, output, start_time, end_time, error_msg
            )

        return output, receipt

    def execute_sync(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_fn: Callable[..., Any] | None = None,
    ) -> tuple[Any, ExecutionReceipt | None]:
        """Synchronous wrapper around execute()."""
        fn = tool_fn or self._tools.get(tool_name)
        if fn is None:
            raise ValueError(f"Unknown tool: {tool_name}. Register it first or pass tool_fn.")

        start_time = time.time()
        output = None
        error_msg = None

        try:
            output = fn(**args)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            raise
        finally:
            end_time = time.time()
            receipt = self._try_generate_receipt(
                tool_name, args, output, start_time, end_time, error_msg
            )

        return output, receipt

    def _try_generate_receipt(
        self,
        tool_name: str,
        args: dict[str, Any],
        output: Any,
        start_time: float,
        end_time: float,
        error_msg: str | None,
    ) -> ExecutionReceipt | None:
        """Generate a receipt, swallowing any internal errors (fail-open)."""
        try:
            receipt = generate_receipt(
                tool_name=tool_name,
                args=args,
                output=output,
                session_key=self._session_key,
                start_time=start_time,
                end_time=end_time,
            )
            execution = ToolExecution(
                tool_name=tool_name,
                args=args,
                output=output,
                receipt=receipt,
                error=error_msg,
            )
            self._executions.setdefault(tool_name, []).append(execution)
            return receipt
        except Exception:
            logger.exception(INTERNAL_ERROR_CODE)
            return None
