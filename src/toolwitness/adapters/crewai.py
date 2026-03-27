"""CrewAI adapter — @monitored_tool decorator wrapping CrewAI's @tool.

Usage::

    from toolwitness.adapters.crewai import monitored_tool

    @monitored_tool
    def get_weather(city: str) -> str:
        \"\"\"Get weather for a city.\"\"\"
        return json.dumps({"city": city, "temp_f": 72})

    # Use in a CrewAI agent normally — ToolWitness records every call
    results = get_weather.toolwitness.verify("Miami is 72°F.")
"""

from __future__ import annotations

import functools
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


class CrewAIMonitor:
    """Monitors tool executions in a CrewAI context."""

    def __init__(
        self,
        storage: StorageBackend | None = None,
        session_id: str | None = None,
    ) -> None:
        self._monitor = ExecutionMonitor()
        self._storage = storage
        self._session_id = session_id or uuid.uuid4().hex[:16]

        if self._storage:
            self._storage.save_session(self._session_id, {"adapter": "crewai"})

    @property
    def monitor(self) -> ExecutionMonitor:
        return self._monitor

    def record(
        self,
        tool_name: str,
        args: dict[str, Any],
        output: Any,
    ) -> None:
        """Record a tool execution."""
        self._monitor.register_tool(tool_name, lambda **kw: output)
        self._monitor.execute_sync(tool_name, args, lambda **kw: output)
        self._persist_execution(tool_name)

    def verify(self, agent_response: str) -> list[VerificationResult]:
        results: list[VerificationResult] = []
        for tool_name, executions in self._monitor.executions.items():
            if not executions:
                continue
            execution = executions[-1]
            receipt_valid = verify_receipt(
                execution.receipt, self._monitor.session_key,
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


_default_monitor = CrewAIMonitor()


def monitored_tool(
    fn: Callable[..., Any] | None = None,
    *,
    monitor: CrewAIMonitor | None = None,
) -> Any:
    """Decorator that wraps a CrewAI tool function with ToolWitness monitoring.

    Can be used bare or with arguments::

        @monitored_tool
        def my_tool(arg: str) -> str:
            ...

        # Or with a custom monitor:
        my_monitor = CrewAIMonitor(storage=SQLiteStorage())

        @monitored_tool(monitor=my_monitor)
        def my_tool(arg: str) -> str:
            ...
    """
    effective_monitor = monitor or _default_monitor

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        tool_name = getattr(func, "name", func.__name__)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            output = func(*args, **kwargs)

            call_args = kwargs.copy()
            if args:
                call_args["_positional"] = list(args)

            parsed_output = output
            if isinstance(output, str):
                import contextlib
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    parsed_output = json.loads(output)

            effective_monitor.record(tool_name, call_args, parsed_output)
            return output

        wrapper.toolwitness = effective_monitor  # type: ignore[attr-defined]
        return wrapper

    if fn is not None:
        return decorator(fn)
    return decorator
