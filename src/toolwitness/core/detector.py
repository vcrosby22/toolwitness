"""ToolWitnessDetector — main orchestrator.

Public API entry point. Wraps tool registration, execution monitoring,
and response verification into a single coherent interface.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from toolwitness.core.classifier import classify
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import verify_receipt
from toolwitness.core.types import ToolExecution, VerificationResult

logger = logging.getLogger("toolwitness")

F = TypeVar("F", bound=Callable[..., Any])


class ToolWitnessDetector:
    """Main entry point for ToolWitness.

    Usage::

        detector = ToolWitnessDetector()

        @detector.tool()
        def get_weather(city: str) -> dict:
            return {"city": city, "temp_f": 72}

        result = detector.execute("get_weather", {"city": "Miami"})
        verification = detector.verify("The weather in Miami is 72°F.")
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._monitor = ExecutionMonitor()
        self._tool_schemas: dict[str, dict[str, Any] | None] = {}

    @property
    def monitor(self) -> ExecutionMonitor:
        return self._monitor

    def tool(
        self,
        name: str | None = None,
        schema: dict[str, Any] | None = None,
    ) -> Callable[[F], F]:
        """Decorator to register and wrap a tool for monitoring.

        Args:
            name: Override tool name (defaults to function name).
            schema: Optional output schema for conformance checking.
        """
        def decorator(fn: F) -> F:
            tool_name = name or fn.__name__
            self._monitor.register_tool(tool_name, fn)
            self._tool_schemas[tool_name] = schema

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return fn(*args, **kwargs)

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await fn(*args, **kwargs)

            if asyncio.iscoroutinefunction(fn):
                return async_wrapper  # type: ignore[return-value]
            return sync_wrapper  # type: ignore[return-value]

        return decorator

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_fn: Callable[..., Any] | None = None,
    ) -> Any:
        """Execute a monitored tool and return its output.

        The execution receipt is generated and stored internally.
        """
        output, _receipt = await self._monitor.execute(tool_name, args, tool_fn)
        return output

    def execute_sync(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_fn: Callable[..., Any] | None = None,
    ) -> Any:
        """Synchronous version of execute()."""
        output, _receipt = self._monitor.execute_sync(tool_name, args, tool_fn)
        return output

    async def verify(self, agent_response: str) -> list[VerificationResult]:
        """Verify an agent's response against all recorded tool executions.

        Returns a list of VerificationResults, one per tool that was
        referenced or expected.
        """
        return self._do_verify(agent_response)

    def verify_sync(self, agent_response: str) -> list[VerificationResult]:
        """Synchronous version of verify()."""
        return self._do_verify(agent_response)

    def _do_verify(self, agent_response: str) -> list[VerificationResult]:
        """Core verification logic (sync — structural match is CPU-bound)."""
        results: list[VerificationResult] = []

        for tool_name, executions in self._monitor.executions.items():
            if not executions:
                continue

            execution = executions[-1]
            receipt_valid = verify_receipt(execution.receipt, self._monitor.session_key)

            result = classify(
                tool_name=tool_name,
                agent_response=agent_response,
                execution=execution,
                receipt_valid=receipt_valid,
            )
            results.append(result)

        return results

    def get_execution(self, tool_name: str) -> ToolExecution | None:
        """Get the latest execution for a tool."""
        return self._monitor.get_latest_execution(tool_name)

    def get_all_executions(self) -> dict[str, list[ToolExecution]]:
        """Get all recorded executions."""
        return self._monitor.executions

    @property
    def tool_names(self) -> list[str]:
        """List of registered tool names."""
        return list(self._monitor._tools.keys())

    def summary(self) -> dict[str, Any]:
        """Quick summary of all verifications from the last verify() call."""
        return {
            "tools_registered": len(self._monitor._tools),
            "tools_executed": len(self._monitor.executions),
            "session_key_set": self._monitor.session_key is not None,
        }
