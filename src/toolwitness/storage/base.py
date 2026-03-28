"""Abstract storage interface for ToolWitness persistence backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from toolwitness.core.types import Handoff, ToolExecution, VerificationResult


class StorageBackend(ABC):
    """Base class for ToolWitness storage backends."""

    @abstractmethod
    def save_execution(self, session_id: str, execution: ToolExecution) -> None:
        """Persist a tool execution record."""

    @abstractmethod
    def save_verification(self, session_id: str, result: VerificationResult) -> None:
        """Persist a verification result."""

    @abstractmethod
    def save_session(
        self,
        session_id: str,
        metadata: dict[str, Any],
        *,
        agent_name: str | None = None,
        parent_session_id: str | None = None,
    ) -> None:
        """Persist session-level metadata."""

    @abstractmethod
    def query_sessions(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query stored sessions with pagination."""

    @abstractmethod
    def query_verifications(
        self,
        *,
        session_id: str | None = None,
        classification: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query stored verification results with optional filters."""

    @abstractmethod
    def get_tool_stats(self) -> dict[str, Any]:
        """Aggregate statistics per tool (call count, failure rate, etc.)."""

    def save_handoff(self, handoff: Handoff) -> None:  # noqa: B027
        """Persist a handoff record. Override in backends that support it."""

    def query_handoffs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query handoff records. Override in backends that support it."""
        return []

    def query_session_tree(
        self, root_session_id: str,
    ) -> list[dict[str, Any]]:
        """Get a session and all its descendants. Override in backends."""
        return []

    def get_execution_by_receipt_id(
        self, receipt_id: str,
    ) -> dict[str, Any] | None:
        """Look up an execution by its receipt ID. Override in backends."""
        return None

    def mark_false_positive(self, verification_id: int, reason: str = "") -> bool:
        """Mark a verification as a false positive. Override in backends that support it."""
        return False

    def close(self) -> None:  # noqa: B027
        """Clean up resources. Override if needed."""
