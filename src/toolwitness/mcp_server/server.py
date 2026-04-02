"""ToolWitness MCP verification server.

Exposes verification tools via the Model Context Protocol so that AI
agents can self-check their responses against recently recorded tool
executions from the ToolWitness proxy.

Usage (stdio transport — Cursor-managed)::

    toolwitness serve

Usage (SSE transport — independent HTTP lifecycle)::

    toolwitness serve --transport sse --port 8322

Configure in Cursor's ``mcp.json`` (stdio)::

    {
      "mcpServers": {
        "toolwitness": {
          "command": "/path/to/toolwitness",
          "args": ["serve"]
        }
      }
    }

Or with SSE (survives Cursor restarts)::

    {
      "mcpServers": {
        "toolwitness": { "url": "http://localhost:8322/sse" }
      }
    }
"""

from __future__ import annotations

import logging
import threading
import time
from http.server import HTTPServer
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from toolwitness.config import ToolWitnessConfig
from toolwitness.storage.sqlite import SQLiteStorage
from toolwitness.verification.bridge import (
    BridgeVerificationResult,
    verify_agent_response,
)

logger = logging.getLogger("toolwitness")

_DESCRIPTION = (
    "ToolWitness verification server. Compares agent responses against "
    "proxy-recorded tool executions to detect fabrication, embellishment, "
    "and tool skipping."
)

mcp = FastMCP("toolwitness", instructions=_DESCRIPTION)

_db_path: str | None = None
_alert_engine: Any = None
_semantic_verifier: Any = None


def _get_storage() -> SQLiteStorage:
    """Open the shared ToolWitness database."""
    if _db_path:
        return SQLiteStorage(_db_path)
    return SQLiteStorage()


def _get_alert_engine() -> Any:
    return _alert_engine


def _get_semantic_verifier() -> Any:
    return _semantic_verifier


def configure(db_path: str | None = None) -> None:
    """Set the database path and build the alert engine from config."""
    global _db_path, _alert_engine, _semantic_verifier
    _db_path = db_path

    config = ToolWitnessConfig.load()
    if config.alerting_config:
        from toolwitness.alerting.rules import AlertEngine
        _alert_engine = AlertEngine.from_config(config.alerting_config)
    else:
        _alert_engine = None

    if config.semantic_enabled and config.semantic_api_key:
        from toolwitness.verification.semantic import create_verifier
        _semantic_verifier = create_verifier(
            provider=config.semantic_provider,
            model=config.semantic_model,
            api_key=config.semantic_api_key,
        )
        logging.getLogger("toolwitness").info(
            "Semantic verification enabled (provider=%s, model=%s)",
            config.semantic_provider, config.semantic_model,
        )
    else:
        _semantic_verifier = None


def _check_proxy_status(storage: SQLiteStorage) -> dict[str, Any]:
    """Query the heartbeat table and return proxy liveness info."""
    try:
        heartbeat = storage.get_latest_heartbeat()
    except Exception:
        return {"proxy_status": "unknown", "proxy_pid": None, "heartbeat_age_seconds": None}

    if not heartbeat:
        return {"proxy_status": "unknown", "proxy_pid": None, "heartbeat_age_seconds": None}

    age = time.time() - heartbeat.get("timestamp", 0)
    status_field = heartbeat.get("status", "alive")
    pid = heartbeat.get("pid")

    if status_field == "stopped":
        proxy_status = "stopped"
    elif age < 60:
        proxy_status = "alive"
    elif age < 300:
        proxy_status = "stale"
    else:
        proxy_status = "dead"

    return {
        "proxy_status": proxy_status,
        "proxy_pid": pid,
        "last_heartbeat": heartbeat.get("timestamp"),
        "heartbeat_age_seconds": round(age, 1),
        "heartbeat_reported_status": status_field,
    }


@mcp.tool()
def tw_verify_response(
    response_text: str,
    time_window_minutes: int = 5,
    tool_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify an agent's response against tool executions.

    Checks both proxy-recorded tool calls (from the last
    ``time_window_minutes``) and self-reported ``tool_outputs``
    provided by the agent. Proxy data takes precedence when both
    sources exist for the same tool.

    Self-reported outputs are compared in memory and discarded —
    only the verdict is stored. No raw tool content is persisted.

    Classifications:
      - VERIFIED — response accurately reflects tool output
      - EMBELLISHED — accurate data plus unsupported extra claims
      - FABRICATED — response contradicts what the tool returned
      - SKIPPED — agent references a tool that was never called

    Call this after using tools to ensure your response faithfully
    represents what the tools returned.

    Args:
        response_text: Your complete response text to verify.
        time_window_minutes: How far back to look for proxy executions (default 5).
        tool_outputs: Self-reported tool outputs from native tools. Each entry
            should be a dict with "tool" (name), "output" (raw text), and
            optionally "args_summary". Write/StrReplace tools are skipped
            automatically.

    Returns:
        Dict with verification results, classifications, and evidence.
    """
    storage = _get_storage()
    try:
        proxy_info = _check_proxy_status(storage)
        result = verify_agent_response(
            storage,
            response_text,
            since_minutes=float(time_window_minutes),
            persist=True,
            alert_engine=_get_alert_engine(),
            tool_outputs=tool_outputs,
            semantic_verifier=_get_semantic_verifier(),
        )
        formatted = _format_result(result)

        if proxy_info["proxy_status"] in ("stale", "dead", "stopped"):
            formatted["warning"] = (
                f"Proxy appears {proxy_info['proxy_status']} "
                f"(last heartbeat {proxy_info['heartbeat_age_seconds']}s ago, "
                f"PID {proxy_info['proxy_pid']}). "
                "Verification may be against stale data. "
                "Restart filesystem-monitored in Cursor Settings > MCP."
            )
            formatted["proxy_status"] = proxy_info["proxy_status"]

        return formatted
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
        response: dict[str, Any] = {
            "count": len(executions),
            "executions": executions,
        }
        if not executions:
            response["hint"] = (
                "No proxy executions found. The proxy MCP server may not be "
                "running. Call tw_health for a full diagnosis, or run "
                "`toolwitness doctor` from the terminal."
            )
        return response
    finally:
        storage.close()


@mcp.tool()
def tw_health() -> dict[str, Any]:
    """Check ToolWitness system health.

    Returns status of database connectivity, recent proxy activity,
    proxy heartbeat status, and whether the proxy is actively
    recording executions.  Use this when verification returns 0
    executions to diagnose why.

    Returns:
        Dict with health status, proxy activity, heartbeat info,
        and diagnosis message.
    """
    result: dict[str, Any] = {
        "db_exists": False,
        "db_writable": False,
        "total_executions": 0,
        "recent_executions": 0,
        "proxy_active": False,
        "proxy_status": "unknown",
        "proxy_pid": None,
        "last_heartbeat_ago": None,
        "last_execution_ago": None,
        "diagnosis": "",
    }

    db_file = Path(_db_path) if _db_path else Path.home() / ".toolwitness" / "toolwitness.db"

    if not db_file.exists():
        result["diagnosis"] = (
            f"Database not found at {db_file}. The proxy has never run. "
            "Make sure filesystem-monitored is configured and running in "
            "Cursor Settings > MCP, then use a monitored tool to generate data."
        )
        return result

    result["db_exists"] = True

    try:
        storage = SQLiteStorage(str(db_file))
    except Exception as exc:
        result["diagnosis"] = f"Cannot open database: {exc}"
        return result

    try:
        storage.close()
        storage = SQLiteStorage(str(db_file))
        result["db_writable"] = True
    except Exception:
        result["diagnosis"] = (
            f"Database at {db_file} is not writable. Check file permissions."
        )
        return result

    try:
        proxy_info = _check_proxy_status(storage)
        result["proxy_status"] = proxy_info["proxy_status"]
        result["proxy_pid"] = proxy_info.get("proxy_pid")
        if proxy_info.get("heartbeat_age_seconds") is not None:
            result["last_heartbeat_ago"] = _time_ago(proxy_info.get("last_heartbeat", 0))
            result["heartbeat_age_seconds"] = proxy_info["heartbeat_age_seconds"]

        all_execs = storage.query_executions(limit=10000)
        result["total_executions"] = len(all_execs)

        since_5m = time.time() - 300
        recent = [e for e in all_execs if e.get("timestamp", 0) >= since_5m]
        result["recent_executions"] = len(recent)

        proxy_alive = proxy_info["proxy_status"] == "alive"
        has_recent_execs = len(recent) > 0
        result["proxy_active"] = proxy_alive or has_recent_execs

        if all_execs:
            last_ts = max(e.get("timestamp", 0) for e in all_execs)
            result["last_execution_ago"] = _time_ago(last_ts)

        if result["total_executions"] == 0 and not proxy_alive:
            result["diagnosis"] = (
                "Database exists but has 0 recorded executions. The proxy has "
                "never successfully recorded a tool call. Check that "
                "filesystem-monitored is running in Cursor Settings > MCP and "
                "restart it if it shows an error. Then use a monitored tool "
                "and call tw_recent_executions to confirm data flows."
            )
        elif proxy_alive and has_recent_execs:
            result["diagnosis"] = (
                f"Healthy. Proxy alive (PID {proxy_info.get('proxy_pid')}, "
                f"heartbeat {proxy_info['heartbeat_age_seconds']}s ago). "
                f"{result['recent_executions']} execution(s) in the last 5 minutes, "
                f"{result['total_executions']} total."
            )
        elif proxy_alive and not has_recent_execs:
            result["diagnosis"] = (
                f"Proxy alive (PID {proxy_info.get('proxy_pid')}, "
                f"heartbeat {proxy_info['heartbeat_age_seconds']}s ago) "
                f"but no tool calls in the last 5 minutes. "
                f"{result['total_executions']} total execution(s). "
                "This is normal during idle periods."
            )
        elif proxy_info["proxy_status"] in ("stale", "dead", "stopped"):
            status = proxy_info["proxy_status"]
            result["diagnosis"] = (
                f"Proxy is {status} "
                f"(last heartbeat {result.get('last_heartbeat_ago', 'unknown')}). "
                f"Found {result['total_executions']} total execution(s). "
                "Restart filesystem-monitored in Cursor Settings > MCP."
            )
        elif not has_recent_execs:
            result["diagnosis"] = (
                f"Found {result['total_executions']} total execution(s), but "
                f"none in the last 5 minutes (last was {result['last_execution_ago']}). "
                "No heartbeat data available (proxy may predate heartbeat feature). "
                "Restart filesystem-monitored in Cursor Settings > MCP."
            )
        else:
            result["diagnosis"] = (
                f"Healthy. {result['recent_executions']} execution(s) in the "
                f"last 5 minutes, {result['total_executions']} total."
            )
    except Exception as exc:
        result["diagnosis"] = f"Error querying database: {exc}"
    finally:
        storage.close()

    return result


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

    response: dict[str, Any] = {
        "session_id": result.session_id,
        "executions_checked": result.executions_checked,
        "has_failures": result.has_failures,
        "verifications": verifications,
    }

    if result.executions_checked == 0:
        response["hint"] = (
            "No proxy executions found to verify against. The proxy MCP "
            "server may not be running or no monitored tools were called "
            "recently. Call tw_health for a full diagnosis, or run "
            "`toolwitness doctor` from the terminal."
        )

    return response


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


def _start_dashboard_thread(
    db_path: str | None,
    port: int = 8321,
    host: str = "127.0.0.1",
) -> None:
    """Start the dashboard HTTP server on a background daemon thread.

    If the port is already in use, logs a warning and skips — never
    crashes the MCP server.
    """
    from toolwitness.dashboard.server import DashboardHandler

    storage_path = db_path or str(
        Path.home() / ".toolwitness" / "toolwitness.db"
    )
    DashboardHandler.storage_path = storage_path

    try:
        server = HTTPServer((host, port), DashboardHandler)
    except OSError as exc:
        logger.warning(
            "Dashboard not started (port %d may be in use): %s", port, exc,
        )
        return

    thread = threading.Thread(
        target=server.serve_forever,
        name="toolwitness-dashboard",
        daemon=True,
    )
    thread.start()
    logger.info("Dashboard available at http://%s:%d", host, port)


def run_server(
    db_path: str | None = None,
    dashboard_port: int = 8321,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8322,
) -> None:
    """Start the MCP server with the chosen transport + embedded dashboard.

    Args:
        db_path: SQLite database path (None for default).
        dashboard_port: Port for the embedded dashboard (0 to disable).
        transport: MCP transport — ``"stdio"``, ``"sse"``, or
            ``"streamable-http"``.
        host: Bind address for HTTP transports (ignored for stdio).
        port: Port for HTTP transports (ignored for stdio).
    """
    configure(db_path)
    if dashboard_port:
        _start_dashboard_thread(db_path, port=dashboard_port)

    # FastMCP >= 1.0: bind address for HTTP transports is set on ``mcp.settings``,
    # not passed to ``run()`` (which only accepts ``transport`` and ``mount_path``).
    if transport in ("sse", "streamable-http"):
        mcp.settings.host = host
        mcp.settings.port = port

    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "sse":
        mcp.run(transport="sse")
    elif transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        raise ValueError(f"Unknown transport: {transport!r} (use stdio, sse, or streamable-http)")
