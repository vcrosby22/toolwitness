"""ToolWitnessDetector — main orchestrator.

Public API entry point. Wraps tool registration, execution monitoring,
and response verification into a single coherent interface.

Multi-agent support:
    Pass ``agent_name`` and ``parent_session_id`` to link detectors in a
    swarm.  Use ``register_handoff()`` to record data crossing agent
    boundaries and ``verify_with_handoffs()`` to catch corruption that
    compounds across agents.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from toolwitness.core.classifier import classify, classify_handoff
from toolwitness.core.monitor import ExecutionMonitor
from toolwitness.core.receipt import verify_receipt
from toolwitness.core.types import (
    Handoff,
    HandoffVerificationResult,
    ToolExecution,
    VerificationResult,
)
from toolwitness.storage.base import StorageBackend

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

    With persistence::

        from toolwitness.storage.sqlite import SQLiteStorage
        detector = ToolWitnessDetector(storage=SQLiteStorage())

    Multi-agent::

        orchestrator = ToolWitnessDetector(
            storage=storage, agent_name="orchestrator",
        )
        researcher = ToolWitnessDetector(
            storage=storage, agent_name="researcher",
            parent_session_id=orchestrator.session_id,
        )
        orchestrator.register_handoff(researcher, data="customer record")
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        storage: StorageBackend | None = None,
        session_id: str | None = None,
        agent_name: str | None = None,
        parent_session_id: str | None = None,
    ):
        self._config = config or {}
        self._monitor = ExecutionMonitor()
        self._tool_schemas: dict[str, dict[str, Any] | None] = {}
        self._storage = storage
        self._session_id = session_id or uuid.uuid4().hex[:16]
        self._agent_name = agent_name
        self._parent_session_id = parent_session_id

        if self._storage:
            self._storage.save_session(
                self._session_id,
                {},
                agent_name=agent_name,
                parent_session_id=parent_session_id,
            )

    @property
    def monitor(self) -> ExecutionMonitor:
        return self._monitor

    @property
    def agent_name(self) -> str | None:
        return self._agent_name

    @property
    def parent_session_id(self) -> str | None:
        return self._parent_session_id

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
        If storage is configured, the execution is persisted.
        """
        output, _receipt = await self._monitor.execute(
            tool_name, args, tool_fn,
        )
        self._persist_execution(tool_name)
        return output

    def execute_sync(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_fn: Callable[..., Any] | None = None,
    ) -> Any:
        """Synchronous version of execute()."""
        output, _receipt = self._monitor.execute_sync(
            tool_name, args, tool_fn,
        )
        self._persist_execution(tool_name)
        return output

    async def verify(
        self, agent_response: str,
    ) -> list[VerificationResult]:
        """Verify an agent's response against all recorded tool executions.

        Returns a list of VerificationResults, one per tool that was
        referenced or expected.
        """
        return self._do_verify(agent_response)

    def verify_sync(
        self, agent_response: str,
    ) -> list[VerificationResult]:
        """Synchronous version of verify()."""
        return self._do_verify(agent_response)

    # ------------------------------------------------------------------
    # Multi-agent: handoff registration
    # ------------------------------------------------------------------

    def register_handoff(
        self,
        target: ToolWitnessDetector,
        data: str = "",
    ) -> Handoff | None:
        """Record a data handoff from this agent to *target*.

        Captures all current receipt IDs so cross-agent verification can
        later trace corruption back to the originating tool output.

        Returns the Handoff object, or None if no storage is configured.
        """
        receipt_ids = [
            ex.receipt.receipt_id
            for execs in self._monitor.executions.values()
            for ex in execs
        ]
        handoff = Handoff(
            handoff_id=uuid.uuid4().hex[:16],
            source_session_id=self._session_id,
            target_session_id=target.session_id,
            data_summary=data,
            source_receipt_ids=receipt_ids,
            timestamp=time.time(),
        )
        if self._storage:
            try:
                self._storage.save_handoff(handoff)
            except Exception:
                logger.exception("Failed to persist handoff — continuing")
        return handoff

    # ------------------------------------------------------------------
    # Multi-agent: cross-agent verification
    # ------------------------------------------------------------------

    def verify_with_handoffs(
        self, agent_response: str,
    ) -> tuple[
        list[VerificationResult], list[HandoffVerificationResult],
    ]:
        """Verify response against own tools AND upstream handoff data.

        Returns (local_results, handoff_results).  local_results is
        identical to ``verify_sync()``.  handoff_results contains one
        entry per source tool whose output was passed to this agent via
        a handoff and whose data appears corrupted in *agent_response*.
        """
        local = self._do_verify(agent_response)
        handoff_results: list[HandoffVerificationResult] = []

        if not self._storage:
            return local, handoff_results

        try:
            inbound = self._storage.query_handoffs(
                session_id=self._session_id,
            )
        except Exception:
            logger.exception("Failed to query handoffs")
            return local, handoff_results

        for ho in inbound:
            if ho["target_session_id"] != self._session_id:
                continue
            receipt_ids = ho.get("source_receipt_ids", [])
            if isinstance(receipt_ids, str):
                receipt_ids = json.loads(receipt_ids)

            for rid in receipt_ids:
                exec_row = self._storage.get_execution_by_receipt_id(rid)
                if not exec_row:
                    continue
                original_output = exec_row.get("output")
                if original_output and isinstance(original_output, str):
                    try:
                        original_output = json.loads(original_output)
                    except (json.JSONDecodeError, TypeError):
                        pass

                result = classify_handoff(
                    tool_name=exec_row.get("tool_name", "unknown"),
                    agent_response=agent_response,
                    original_output=original_output,
                    source_session_id=ho["source_session_id"],
                    handoff_id=ho["handoff_id"],
                )
                if result:
                    handoff_results.append(result)

        return local, handoff_results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_verify(
        self, agent_response: str,
    ) -> list[VerificationResult]:
        """Core verification logic (sync — structural match is CPU-bound)."""
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

    def _persist_execution(self, tool_name: str) -> None:
        """Save the latest execution to storage if configured."""
        if not self._storage:
            return
        execution = self._monitor.get_latest_execution(tool_name)
        if execution:
            try:
                self._storage.save_execution(
                    self._session_id, execution,
                )
            except Exception:
                logger.exception(
                    "Failed to persist execution — continuing",
                )

    def _persist_verification(self, result: VerificationResult) -> None:
        """Save a verification result to storage if configured."""
        if not self._storage:
            return
        try:
            self._storage.save_verification(self._session_id, result)
        except Exception:
            logger.exception(
                "Failed to persist verification — continuing",
            )

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def storage(self) -> StorageBackend | None:
        return self._storage

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
            "agent_name": self._agent_name,
            "parent_session_id": self._parent_session_id,
        }
