"""Transparent stdio proxy for MCP servers.

Spawns the real MCP server as a subprocess, forwards all JSON-RPC
messages bidirectionally, and records ``tools/call`` interactions
via :class:`~toolwitness.adapters.mcp.MCPMonitor` for later
inspection through the CLI and dashboard.

The proxy never modifies message content — it is a pure observer.
If ToolWitness recording fails, the message still passes through
(fail-open design).

Resilience features:
- **Heartbeat**: writes a periodic heartbeat to SQLite so
  ``tw_health`` can distinguish "alive but idle" from "dead."
- **Child auto-restart**: if the wrapped MCP server crashes while
  the host pipe is still open, restarts it with exponential backoff
  (configurable via ``max_child_restarts``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from typing import Any

from toolwitness.adapters.mcp import MCPMonitor
from toolwitness.storage.sqlite import SQLiteStorage

logger = logging.getLogger("toolwitness")

HEARTBEAT_INTERVAL_SECONDS = 30
DEFAULT_MAX_CHILD_RESTARTS = 3


async def _read_jsonrpc_lines(
    stream: asyncio.StreamReader,
) -> AsyncIterator[dict[str, Any]]:
    """Yield parsed JSON-RPC objects from a newline-delimited stream."""
    while True:
        line = await stream.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Non-JSON line from MCP stream: %r", line[:200])


async def _write_jsonrpc(
    writer: asyncio.StreamWriter | Any,
    message: dict[str, Any],
) -> None:
    """Write a JSON-RPC message as a single newline-terminated line."""
    raw = json.dumps(message, separators=(",", ":")) + "\n"
    writer.write(raw.encode())
    await writer.drain()


async def _pipe_stderr(stream: asyncio.StreamReader) -> None:
    """Forward subprocess stderr to our stderr."""
    while True:
        line = await stream.readline()
        if not line:
            break
        sys.stderr.buffer.write(line)
        sys.stderr.buffer.flush()


async def _heartbeat_loop(
    storage: SQLiteStorage,
    session_id: str,
    stop_event: asyncio.Event,
) -> None:
    """Write a heartbeat row every HEARTBEAT_INTERVAL_SECONDS until stopped."""
    pid = os.getpid()
    while not stop_event.is_set():
        try:
            storage.save_heartbeat(session_id, pid, status="alive")
        except Exception:
            logger.debug("Heartbeat write failed", exc_info=True)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)


async def _spawn_child(
    server_command: list[str],
) -> asyncio.subprocess.Process:
    """Spawn the wrapped MCP server subprocess."""
    proc = await asyncio.create_subprocess_exec(
        *server_command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None
    return proc


async def _kill_child(proc: asyncio.subprocess.Process) -> None:
    """Terminate a child process gracefully, then force-kill on timeout."""
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        proc.kill()


async def run_proxy(
    server_command: list[str],
    db_path: str | None = None,
    session_id: str | None = None,
    max_child_restarts: int = DEFAULT_MAX_CHILD_RESTARTS,
) -> int:
    """Run the MCP stdio proxy until the subprocess exits or stdin closes.

    The proxy writes a heartbeat to SQLite every 30 seconds so that
    ``tw_health`` can report accurate proxy liveness even during idle
    periods with no tool calls.

    If the child MCP server crashes while the host pipe is still open,
    the proxy restarts it up to *max_child_restarts* times with
    exponential backoff.  Each restart is logged to the
    ``proxy_events`` table.

    Returns the subprocess exit code.
    """
    storage = SQLiteStorage(db_path) if db_path else SQLiteStorage()
    monitor = MCPMonitor(
        storage=storage,
        session_id=session_id,
        metadata={"server_command": " ".join(server_command)},
    )
    effective_session_id = monitor._session_id

    storage.save_proxy_event(effective_session_id, "proxy_start", " ".join(server_command))

    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(storage, effective_session_id, stop_heartbeat),
    )

    stdin_reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(stdin_reader)
    loop = asyncio.get_event_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    stdout_writer_transport, _ = (
        await loop.connect_write_pipe(asyncio.BaseProtocol, sys.stdout.buffer)
    )

    class _StdoutWriter:
        """Thin wrapper so _write_jsonrpc can use writer.write/drain."""

        def write(self, data: bytes) -> None:
            stdout_writer_transport.write(data)

        async def drain(self) -> None:
            pass

    stdout_writer = _StdoutWriter()

    host_stdin_closed = False
    child_restarts = 0
    last_exit_code = 0

    try:
        while True:
            proc = await _spawn_child(server_command)
            stderr_task = asyncio.create_task(_pipe_stderr(proc.stderr))

            if child_restarts > 0:
                storage.save_proxy_event(
                    effective_session_id,
                    "child_restart",
                    f"Restart #{child_restarts} of {' '.join(server_command)}",
                )
                logger.info("Child restarted (attempt %d/%d)", child_restarts, max_child_restarts)

            async def host_to_server(child: asyncio.subprocess.Process) -> None:
                nonlocal host_stdin_closed
                assert child.stdin is not None
                async for msg in _read_jsonrpc_lines(stdin_reader):
                    try:
                        monitor.on_jsonrpc_message(msg)
                    except Exception:
                        logger.debug("Monitor error on host→server", exc_info=True)
                    try:
                        raw = json.dumps(msg, separators=(",", ":")) + "\n"
                        child.stdin.write(raw.encode())
                        await child.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        break
                host_stdin_closed = True
                if child.stdin.can_write_eof():
                    child.stdin.write_eof()

            async def server_to_host(child: asyncio.subprocess.Process) -> None:
                assert child.stdout is not None
                async for msg in _read_jsonrpc_lines(child.stdout):
                    try:
                        monitor.on_jsonrpc_message(msg)
                    except Exception:
                        logger.debug("Monitor error on server→host", exc_info=True)
                    try:
                        await _write_jsonrpc(stdout_writer, msg)
                    except (BrokenPipeError, ConnectionResetError):
                        break

            try:
                await asyncio.gather(host_to_server(proc), server_to_host(proc))
            except asyncio.CancelledError:
                pass
            finally:
                await _kill_child(proc)
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task

            last_exit_code = proc.returncode or 0

            if host_stdin_closed:
                break

            if last_exit_code != 0 and child_restarts < max_child_restarts:
                child_restarts += 1
                backoff = min(2 ** child_restarts, 30)
                storage.save_proxy_event(
                    effective_session_id,
                    "child_crash",
                    f"Exit code {last_exit_code}, restarting in {backoff}s",
                )
                logger.warning(
                    "Child exited with code %d, restarting in %ds (attempt %d/%d)",
                    last_exit_code, backoff, child_restarts, max_child_restarts,
                )
                await asyncio.sleep(backoff)
            else:
                if last_exit_code != 0 and child_restarts >= max_child_restarts:
                    storage.save_proxy_event(
                        effective_session_id,
                        "child_restart_exhausted",
                        f"Exit code {last_exit_code}, max restarts ({max_child_restarts}) reached",
                    )
                    logger.error(
                        "Child exited with code %d and max restarts exhausted", last_exit_code,
                    )
                break
    finally:
        stop_heartbeat.set()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        storage.save_heartbeat(effective_session_id, os.getpid(), status="stopped")
        storage.save_proxy_event(effective_session_id, "proxy_stop")
        storage.close()

    return last_exit_code
