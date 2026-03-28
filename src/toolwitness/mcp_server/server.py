"""ToolWitness MCP verification server.

Exposes verification tools via the Model Context Protocol so that AI
agents can self-check their responses against recently recorded tool
executions from the ToolWitness proxy.

Usage (stdio transport — standard for MCP hosts)::

    toolwitness serve

Configure in Cursor's ``mcp.json``::

    {
      "mcpServers": {
        "toolwitness": {
          "command": "/path/to/toolwitness",
          "args": ["serve"]
        }
      }
    }
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from toolwitness.config import ToolWitnessConfig
from toolwitness.storage.sqlite import SQLiteStorage
from toolwitness.verification.bridge import (
    BridgeVerificationResult,
    hydrate_execution,
    verify_agent_response,
)

_DESCRIPTION = (
    "ToolWitness verification server. Compares agent responses against "
    "proxy-recorded tool executions to detect fabrication, embellishment, "
    "and tool skipping."
)

mcp = FastMCP("toolwitness", instructions=_DESCRIPTION)

_db_path: str | None = None
_alert_engine: Any = None


def _get_storage() -> SQLiteStorage:
    """Open the shared ToolWitness database."""
    if _db_path:
        return SQLiteStorage(_db_path)
    return SQLiteStorage()


def _get_alert_engine() -> Any:
    return _alert_engine


def configure(db_path: str | None = None) -> None:
    """Set the database path and build the alert engine from config."""
    global _db_path, _alert_engine
    _db_path = db_path

    config = ToolWitnessConfig.load()
    if config.alerting_config:
        from toolwitness.alerting.rules import AlertEngine
        _alert_engine = AlertEngine.from_config(config.alerting_config)
    else:
        _alert_engine = None


@mcp.tool()
def tw_verify_response(
    response_text: str,
    time_window_minutes: int = 5,
) -> dict[str, Any]:
    """Verify an agent's response against recent tool executions.

    Reads proxy-recorded tool calls from the last ``time_window_minutes``,
    runs the ToolWitness classifier comparing ``response_text`` against
    each tool's actual output, and returns per-tool verdicts.

    Classifications:
      - VERIFIED — response accurately reflects tool output
      - EMBELLISHED — accurate data plus unsupported extra claims
      - FABRICATED — response contradicts what the tool returned
      - SKIPPED — agent references a tool that was never called

    Call this after using monitored tools to ensure your response
    faithfully represents what the tools returned.

    Args:
        response_text: Your complete response text to verify.
        time_window_minutes: How far back to look for executions (default 5).

    Returns:
        Dict with verification results, classifications, and evidence.
    """
    storage = _get_storage()
    try:
        result = verify_agent_response(
            storage,
            response_text,
            since_minutes=float(time_window_minutes),
            persist=True,
            alert_engine=_get_alert_engine(),
        )
        return _format_result(result)
    finally:
        storage.close()


@mcp.tool()
def tw_recent_executions(limit: int = 10) -> dict[str, Any]:
    """Show recently recorded tool executions.

    Returns the latest tool calls intercepted by the ToolWitness proxy,
    including tool name, arguments, output summary, and receipt ID.
    Use this to see what data is available for verification.

    Args:
        limit: Maximum number of executions to return (default 10).

    Returns:
        Dict with a list of recent execution summaries.
    """
    storage = _get_storage()
    try:
        rows = storage.query_executions(limit=min(limit, 50))
        executions = []
        for row in rows:
            output_raw = row.get("output", "")
            if isinstance(output_raw, str) and len(output_raw) > 500:
                output_raw = output_raw[:500] + "…"

            executions.append({
                "tool_name": row.get("tool_name", "unknown"),
                "receipt_id": row.get("receipt_id", ""),
                "timestamp": row.get("timestamp", 0),
                "time_ago": _time_ago(row.get("timestamp", 0)),
                "session_id": row.get("session_id", "")[:12],
                "output_preview": output_raw,
                "error": row.get("error"),
            })
        return {
            "count": len(executions),
            "executions": executions,
        }
    finally:
        storage.close()


@mcp.tool()
def tw_session_stats() -> dict[str, Any]:
    """Get verification statistics for the current session.

    Returns counts of verified, fabricated, embellished, and skipped
    classifications across all verification runs, plus per-tool
    failure rates.

    Returns:
        Dict with aggregate verification statistics.
    """
    storage = _get_storage()
    try:
        tool_stats = storage.get_tool_stats()
        exec_stats = storage.get_execution_stats()

        total_verifications = sum(t.get("total", 0) for t in tool_stats.values())
        total_executions = sum(t.get("total", 0) for t in exec_stats.values())
        total_failures = sum(
            t.get("fabricated", 0) + t.get("skipped", 0)
            for t in tool_stats.values()
        )

        return {
            "total_executions_recorded": total_executions,
            "total_verifications_run": total_verifications,
            "total_failures_detected": total_failures,
            "failure_rate": (
                total_failures / total_verifications
                if total_verifications > 0 else 0.0
            ),
            "by_tool": {
                name: {
                    "verified": data.get("verified", 0),
                    "fabricated": data.get("fabricated", 0),
                    "embellished": data.get("embellished", 0),
                    "skipped": data.get("skipped", 0),
                    "failure_rate": data.get("failure_rate", 0.0),
                }
                for name, data in tool_stats.items()
            },
        }
    finally:
        storage.close()


def _format_result(result: BridgeVerificationResult) -> dict[str, Any]:
    """Format bridge result for MCP tool response."""
    verifications = []
    for v in result.verifications:
        entry: dict[str, Any] = {
            "tool_name": v.tool_name,
            "classification": v.classification.value,
            "confidence": round(v.confidence, 2),
        }
        if v.evidence:
            entry["evidence"] = {
                "match_ratio": v.evidence.get("match_ratio"),
                "matched_count": v.evidence.get("matched_count"),
                "mismatched_count": v.evidence.get("mismatched_count"),
            }
            if v.evidence.get("mismatched"):
                entry["evidence"]["mismatched_details"] = v.evidence["mismatched"][:3]
        verifications.append(entry)

    return {
        "session_id": result.session_id,
        "executions_checked": result.executions_checked,
        "has_failures": result.has_failures,
        "verifications": verifications,
    }


def _time_ago(timestamp: float) -> str:
    """Human-readable time-ago string."""
    diff = time.time() - timestamp
    if diff < 60:
        return f"{int(diff)}s ago"
    if diff < 3600:
        return f"{int(diff / 60)}m ago"
    if diff < 86400:
        return f"{int(diff / 3600)}h ago"
    return f"{int(diff / 86400)}d ago"


def run_server(db_path: str | None = None) -> None:
    """Start the MCP server with stdio transport."""
    configure(db_path)
    mcp.run(transport="stdio")
