"""Transparent stdio proxy for MCP servers.

Spawns the real MCP server as a subprocess, forwards all JSON-RPC
messages bidirectionally, and records ``tools/call`` interactions
via :class:`~toolwitness.adapters.mcp.MCPMonitor` for later
inspection through the CLI and dashboard.

The proxy never modifies message content — it is a pure observer.
If ToolWitness recording fails, the message still passes through
(fail-open design).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from typing import Any

from toolwitness.adapters.mcp import MCPMonitor
from toolwitness.storage.sqlite import SQLiteStorage

logger = logging.getLogger("toolwitness")


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


async def run_proxy(
    server_command: list[str],
    db_path: str | None = None,
    session_id: str | None = None,
) -> int:
    """Run the MCP stdio proxy until the subprocess exits or stdin closes.

    Returns the subprocess exit code.
    """
    storage = SQLiteStorage(db_path) if db_path else SQLiteStorage()
    monitor = MCPMonitor(
        storage=storage,
        session_id=session_id,
        metadata={"server_command": " ".join(server_command)},
    )

    proc = await asyncio.create_subprocess_exec(
        *server_command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    stderr_task = asyncio.create_task(_pipe_stderr(proc.stderr))

    stdin_reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(stdin_reader)
    loop = asyncio.get_event_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    stdout_writer_transport, stdout_writer_protocol = (
        await loop.connect_write_pipe(asyncio.BaseProtocol, sys.stdout.buffer)
    )

    class _StdoutWriter:
        """Thin wrapper so _write_jsonrpc can use writer.write/drain."""

        def write(self, data: bytes) -> None:
            stdout_writer_transport.write(data)

        async def drain(self) -> None:
            pass

    stdout_writer = _StdoutWriter()

    async def host_to_server() -> None:
        """Read from host stdin, record, forward to subprocess."""
        async for msg in _read_jsonrpc_lines(stdin_reader):
            try:
                monitor.on_jsonrpc_message(msg)
            except Exception:
                logger.debug("Monitor error on host→server", exc_info=True)
            try:
                raw = json.dumps(msg, separators=(",", ":")) + "\n"
                proc.stdin.write(raw.encode())
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                break
        if proc.stdin.can_write_eof():
            proc.stdin.write_eof()

    async def server_to_host() -> None:
        """Read from subprocess stdout, record, forward to host."""
        async for msg in _read_jsonrpc_lines(proc.stdout):
            try:
                monitor.on_jsonrpc_message(msg)
            except Exception:
                logger.debug("Monitor error on server→host", exc_info=True)
            try:
                await _write_jsonrpc(stdout_writer, msg)
            except (BrokenPipeError, ConnectionResetError):
                break

    try:
        await asyncio.gather(host_to_server(), server_to_host())
    except asyncio.CancelledError:
        pass
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
        stderr_task.cancel()
        storage.close()

    return proc.returncode or 0
