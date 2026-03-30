"""HTTP/SSE MCP proxy for ToolWitness.

Exposes a wrapped MCP server's tools via HTTP transport (SSE or
streamable-http) so the proxy can run independently of Cursor's
process lifecycle.  Internally manages the real MCP server as a
stdio child subprocess.

Architecture::

    Cursor ──HTTP/SSE──▶  ToolWitness HTTP Proxy
                              │
                              ├─ records tool calls to SQLite
                              │
                              └─ stdio ──▶ real MCP server (child)

The proxy:
- On startup, spawns the real MCP server and reads its ``tools/list``
- Registers each tool as a FastMCP tool that forwards to the child
- Records all tool calls via :class:`MCPMonitor` (same as stdio proxy)
- If the child crashes, restarts it with exponential backoff
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import uuid
from typing import Any

from toolwitness.adapters.mcp import MCPMonitor
from toolwitness.proxy.stdio import (
    DEFAULT_MAX_CHILD_RESTARTS,
    HEARTBEAT_INTERVAL_SECONDS,
    _read_jsonrpc_lines,
)
from toolwitness.storage.sqlite import SQLiteStorage

logger = logging.getLogger("toolwitness")


class _ChildManager:
    """Manages a stdio MCP server child process with auto-restart."""

    def __init__(
        self,
        server_command: list[str],
        max_restarts: int = DEFAULT_MAX_CHILD_RESTARTS,
    ) -> None:
        self._command = server_command
        self._max_restarts = max_restarts
        self._proc: asyncio.subprocess.Process | None = None
        self._restart_count = 0
        self._request_id_counter = 0
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._tools: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Spawn the child and start reading its responses."""
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert self._proc.stdout is not None
        assert self._proc.stderr is not None

        self._reader_task = asyncio.create_task(self._read_responses())
        self._stderr_task = asyncio.create_task(self._pipe_stderr())

    async def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
        if self._stderr_task:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stderr_task
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def _restart_if_needed(self) -> bool:
        """Attempt to restart the child. Returns True if successful."""
        if self._restart_count >= self._max_restarts:
            logger.error("Child restart limit reached (%d)", self._max_restarts)
            return False
        self._restart_count += 1
        backoff = min(2 ** self._restart_count, 30)
        logger.warning(
            "Child died, restarting in %ds (attempt %d/%d)",
            backoff, self._restart_count, self._max_restarts,
        )
        await asyncio.sleep(backoff)
        await self.start()
        return True

    async def _pipe_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                break
            logger.debug("child stderr: %s", line.decode(errors="replace").rstrip())

    async def _read_responses(self) -> None:
        """Read JSON-RPC responses from the child and resolve pending futures."""
        assert self._proc is not None and self._proc.stdout is not None
        async for msg in _read_jsonrpc_lines(self._proc.stdout):
            msg_id = msg.get("id")
            if msg_id is not None:
                req_id = str(msg_id)
                fut = self._pending.pop(req_id, None)
                if fut and not fut.done():
                    fut.set_result(msg)

    def _next_id(self) -> str:
        self._request_id_counter += 1
        return str(self._request_id_counter)

    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to the child and await the response."""
        async with self._lock:
            if (self._proc is None or self._proc.returncode is not None) \
                    and not await self._restart_if_needed():
                return {"error": {"code": -1, "message": "Child process unavailable"}}

        assert self._proc is not None and self._proc.stdin is not None

        req_id = self._next_id()
        request: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = fut

        raw = json.dumps(request, separators=(",", ":")) + "\n"
        try:
            self._proc.stdin.write(raw.encode())
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            self._pending.pop(req_id, None)
            if not fut.done():
                fut.cancel()
            async with self._lock:
                if await self._restart_if_needed():
                    return await self.send_request(method, params)
            return {"error": {"code": -1, "message": "Child pipe broken"}}

        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return {"error": {"code": -1, "message": "Child response timeout"}}

    async def initialize(self) -> dict[str, Any]:
        """Send the MCP initialize handshake and cache the tool list."""
        init_resp = await self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "toolwitness-proxy", "version": "0.3.0"},
        })

        await self.send_request("notifications/initialized")

        tools_resp = await self.send_request("tools/list", {})
        result = tools_resp.get("result", {})
        self._tools = result.get("tools", [])
        return init_resp

    @property
    def tools(self) -> list[dict[str, Any]]:
        return list(self._tools)

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Forward a tools/call to the child and return the result."""
        params: dict[str, Any] = {"name": name}
        if arguments:
            params["arguments"] = arguments
        resp = await self.send_request("tools/call", params)
        return resp


async def _heartbeat_loop(
    storage: SQLiteStorage,
    session_id: str,
    stop_event: asyncio.Event,
) -> None:
    pid = os.getpid()
    while not stop_event.is_set():
        try:
            storage.save_heartbeat(session_id, pid, status="alive")
        except Exception:
            logger.debug("Heartbeat write failed", exc_info=True)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)


async def run_http_proxy(
    server_command: list[str],
    db_path: str | None = None,
    session_id: str | None = None,
    transport: str = "sse",
    host: str = "127.0.0.1",
    port: int = 8323,
    max_child_restarts: int = DEFAULT_MAX_CHILD_RESTARTS,
) -> None:
    """Run the HTTP MCP proxy.

    Spawns the real MCP server as a child, discovers its tools, then
    serves them via FastMCP with the chosen HTTP transport.  Tool calls
    are forwarded to the child and recorded via MCPMonitor.
    """
    from mcp.server.fastmcp import FastMCP

    storage = SQLiteStorage(db_path) if db_path else SQLiteStorage()
    effective_session_id = session_id or uuid.uuid4().hex[:16]

    monitor = MCPMonitor(
        storage=storage,
        session_id=effective_session_id,
        metadata={"server_command": " ".join(server_command), "transport": transport},
    )

    child = _ChildManager(server_command, max_restarts=max_child_restarts)
    await child.start()
    await child.initialize()

    storage.save_proxy_event(
        effective_session_id, "http_proxy_start",
        f"transport={transport} wrapping {' '.join(server_command)}",
    )

    proxy_mcp = FastMCP(
        "toolwitness-proxy",
        instructions=(
            "ToolWitness HTTP proxy. Transparently forwards tool calls to the "
            "wrapped MCP server while recording them for verification."
        ),
    )

    def _make_tool_handler(tool_name: str) -> Any:
        """Create a handler closure for a specific child tool."""
        async def handler(**kwargs: Any) -> Any:
            call_params: dict[str, Any] = {"name": tool_name, "arguments": kwargs}
            req_id = str(uuid.uuid4().hex[:12])

            try:
                monitor.on_tool_call(params=call_params, request_id=req_id)
            except Exception:
                logger.debug("Monitor error on tool call", exc_info=True)

            resp = await child.call_tool(tool_name, kwargs)

            result_data = resp.get("result", resp.get("error", {}))
            try:
                from toolwitness.adapters.mcp import _extract_content
                content = _extract_content(result_data)
                monitor.on_tool_result(result=content, request_id=req_id)
            except Exception:
                logger.debug("Monitor error on tool result", exc_info=True)

            if "error" in resp:
                return f"Error: {resp['error']}"

            content_parts = result_data.get("content", [])
            if isinstance(content_parts, list):
                texts = [
                    p.get("text", "")
                    for p in content_parts
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                if texts:
                    return "\n".join(texts)
            return json.dumps(result_data)

        return handler

    for tool_def in child.tools:
        name = tool_def.get("name", "")
        description = tool_def.get("description", "")

        fn = _make_tool_handler(name)
        fn.__name__ = name
        fn.__doc__ = description

        proxy_mcp.tool(name=name, description=description)(fn)

        logger.info("Registered proxied tool: %s", name)

    stop_heartbeat = asyncio.Event()
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(storage, effective_session_id, stop_heartbeat),
    )

    try:
        logger.info(
            "HTTP proxy (%s) listening on %s:%d with %d tools",
            transport, host, port, len(child.tools),
        )
        proxy_mcp.run(transport=transport, host=host, port=port)
    finally:
        stop_heartbeat.set()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
        storage.save_heartbeat(effective_session_id, os.getpid(), status="stopped")
        storage.save_proxy_event(effective_session_id, "http_proxy_stop")
        await child.stop()
        storage.close()
