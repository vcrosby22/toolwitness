"""LangChain adapter — middleware that monitors tool calls in chains/agents.

Usage::

    from toolwitness.adapters.langchain import ToolWitnessMiddleware

    middleware = ToolWitnessMiddleware(
        on_fabrication="log",       # "log", "raise", or "callback"
        confidence_threshold=0.7,
    )

    # As a LangChain callback handler
    agent.invoke(input, config={"callbacks": [middleware]})

    # Get verification results after the run
    results = middleware.get_results()
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


class ToolWitnessMiddleware:
    """LangChain-compatible callback handler that monitors tool executions.

    Can be used as a callback handler with any LangChain agent or chain.
    Records tool inputs/outputs and verifies agent claims against them.
    """

    def __init__(
        self,
        *,
        on_fabrication: str = "log",
        confidence_threshold: float = 0.7,
        on_failure_callback: Callable[[VerificationResult], None] | None = None,
    ):
        """Initialize the middleware.

        Args:
            on_fabrication: Action on detection — "log", "raise", or "callback".
            confidence_threshold: Minimum confidence to trigger action.
            on_failure_callback: Custom callback for "callback" mode.
        """
        if on_fabrication not in ("log", "raise", "callback"):
            raise ValueError(
                f"on_fabrication must be 'log', 'raise', or 'callback', "
                f"got '{on_fabrication}'"
            )

        self._on_fabrication = on_fabrication
        self._confidence_threshold = confidence_threshold
        self._on_failure_callback = on_failure_callback
        self._monitor = ExecutionMonitor()
        self._results: list[VerificationResult] = []
        self._current_tool: str | None = None
        self._current_args: dict[str, Any] = {}

    @property
    def monitor(self) -> ExecutionMonitor:
        return self._monitor

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs: Any,
    ) -> None:
        """Called when a tool starts executing (LangChain callback)."""
        tool_name = serialized.get("name", "unknown_tool")
        self._current_tool = tool_name

        try:
            self._current_args = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            self._current_args = {"input": input_str}

    def on_tool_end(self, output: str, **kwargs: Any) -> None:
        """Called when a tool finishes executing (LangChain callback)."""
        if self._current_tool is None:
            return

        tool_name = self._current_tool
        args = self._current_args

        try:
            parsed_output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            parsed_output = output

        self._monitor.register_tool(
            tool_name, lambda **kw: parsed_output
        )
        self._monitor.execute_sync(
            tool_name, args, lambda **kw: parsed_output
        )

        self._current_tool = None
        self._current_args = {}

    def on_tool_error(
        self, error: BaseException, **kwargs: Any
    ) -> None:
        """Called when a tool errors (LangChain callback)."""
        self._current_tool = None
        self._current_args = {}

    def verify(self, agent_response: str) -> list[VerificationResult]:
        """Verify agent response and trigger configured actions."""
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

            if self._should_act(result):
                self._handle_failure(result)

        self._results = results
        return results

    def get_results(self) -> list[VerificationResult]:
        """Get the most recent verification results."""
        return list(self._results)

    def get_failures(self) -> list[VerificationResult]:
        """Get only non-VERIFIED results from the last verification."""
        return [
            r for r in self._results
            if r.classification != Classification.VERIFIED
        ]

    def _should_act(self, result: VerificationResult) -> bool:
        if result.classification == Classification.VERIFIED:
            return False
        if result.classification == Classification.UNMONITORED:
            return False
        return result.confidence >= self._confidence_threshold

    def _handle_failure(self, result: VerificationResult) -> None:
        msg = (
            f"ToolWitness: {result.tool_name} classified as "
            f"{result.classification.value} "
            f"(confidence={result.confidence:.2f})"
        )

        if self._on_fabrication == "log":
            logger.warning(msg)
        elif self._on_fabrication == "raise":
            raise ToolWitnessVerificationError(msg, result=result)
        elif (
            self._on_fabrication == "callback"
            and self._on_failure_callback
        ):
            self._on_failure_callback(result)


class ToolWitnessVerificationError(Exception):
    """Raised when on_fabrication='raise' and a failure is detected."""

    def __init__(self, message: str, result: VerificationResult):
        super().__init__(message)
        self.result = result
