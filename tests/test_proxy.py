"""Tests for the MCP stdio proxy."""

import asyncio
import json
import sys

import pytest

from toolwitness.proxy.stdio import _read_jsonrpc_lines


class TestReadJsonrpcLines:
    """Unit tests for the JSON-RPC line reader."""

    @pytest.mark.asyncio
    async def test_parses_valid_lines(self):
        reader = asyncio.StreamReader()
        msg1 = {"jsonrpc": "2.0", "method": "ping"}
        msg2 = {"jsonrpc": "2.0", "id": 1, "result": {}}
        reader.feed_data(json.dumps(msg1).encode() + b"\n")
        reader.feed_data(json.dumps(msg2).encode() + b"\n")
        reader.feed_eof()

        results = []
        async for msg in _read_jsonrpc_lines(reader):
            results.append(msg)

        assert len(results) == 2
        assert results[0]["method"] == "ping"
        assert results[1]["id"] == 1

    @pytest.mark.asyncio
    async def test_skips_blank_lines(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"\n\n")
        reader.feed_data(json.dumps({"id": 1}).encode() + b"\n")
        reader.feed_data(b"\n")
        reader.feed_eof()

        results = []
        async for msg in _read_jsonrpc_lines(reader):
            results.append(msg)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_skips_non_json(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b"not json\n")
        reader.feed_data(json.dumps({"ok": True}).encode() + b"\n")
        reader.feed_eof()

        results = []
        async for msg in _read_jsonrpc_lines(reader):
            results.append(msg)

        assert len(results) == 1
        assert results[0]["ok"] is True


class TestRunProxy:
    """Integration tests using a simple echo server subprocess."""

    @pytest.mark.asyncio
    async def test_proxy_with_echo_server(self, tmp_path):
        echo_script = tmp_path / "echo_server.py"
        echo_script.write_text(
            "import sys, json\n"
            "for line in sys.stdin:\n"
            "    line = line.strip()\n"
            "    if not line:\n"
            "        continue\n"
            "    msg = json.loads(line)\n"
            "    if msg.get('method') == 'tools/call':\n"
            "        resp = json.dumps({\n"
            "            'jsonrpc': '2.0',\n"
            "            'id': msg['id'],\n"
            "            'result': {\n"
            "                'content': {'temp_f': 72, 'city': 'Miami'}\n"
            "            }\n"
            "        })\n"
            "        sys.stdout.write(resp + '\\n')\n"
            "        sys.stdout.flush()\n"
            "    elif msg.get('method') == 'shutdown':\n"
            "        break\n"
        )

        cmd = [sys.executable, str(echo_script)]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None

        call_msg = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "get_weather", "arguments": {"city": "Miami"}},
        }
        proc.stdin.write(json.dumps(call_msg).encode() + b"\n")
        await proc.stdin.drain()

        line = await asyncio.wait_for(proc.stdout.readline(), timeout=5.0)
        response = json.loads(line)
        assert response["id"] == "1"
        assert response["result"]["content"]["temp_f"] == 72

        shutdown = {"jsonrpc": "2.0", "method": "shutdown"}
        proc.stdin.write(json.dumps(shutdown).encode() + b"\n")
        proc.stdin.write_eof()
        await asyncio.wait_for(proc.wait(), timeout=5.0)
