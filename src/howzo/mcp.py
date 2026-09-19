"""MCP stdio server (newline-delimited JSON-RPC 2.0).

Run `howzo mcp` to expose howzo_ask / howzo_whatis / howzo_list to MCP clients.
"""
import contextlib
import io
import json
import sys

from . import __version__
from .commands import cmd_ask, cmd_list, cmd_whatis

MCP_TOOLS = [
    {"name": "howzo_ask",
     "description": "Ask in English what you want to do (e.g. 'how do I rotate a pdf'). Returns the best-matching installed tool with usage hints.",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "howzo_whatis",
     "description": "Look up an installed tool by name and show what it does plus help.",
     "inputSchema": {"type": "object", "properties": {"tool": {"type": "string"}}, "required": ["tool"]}},
    {"name": "howzo_list",
     "description": "List installed tools (name, source, one-liner), optionally filtered by source.",
     "inputSchema": {"type": "object", "properties": {"source": {"type": "string"}}}},
]


def mcp_handle(msg):
    m, params = msg.get("method"), msg.get("params", {}) or {}
    mid = msg.get("id")

    def reply(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result} if mid is not None else None

    def error(code, message):
        if mid is None:
            return None
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if m == "initialize":
        return reply({"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "howzo", "version": __version__}})
    if m == "notifications/initialized":
        return None
    if m == "ping":
        return reply({})
    if m == "tools/list":
        return reply({"tools": MCP_TOOLS})
    if m == "tools/call":
        name, args = params.get("name"), params.get("arguments", {}) or {}
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                if name == "howzo_ask":
                    cmd_ask([args.get("query", "")])
                elif name == "howzo_whatis":
                    cmd_whatis([args.get("tool", "")])
                elif name == "howzo_list":
                    cmd_list(["--source", args["source"]] if args.get("source") else [])
                else:
                    return reply({"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True})
        except Exception as e:
            return reply({"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
        return reply({"content": [{"type": "text", "text": buf.getvalue()}]})
    return error(-32601, f"method not found: {m}")


def cmd_mcp(args):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        resp = mcp_handle(msg)
        if resp:
            print(json.dumps(resp), flush=True)
    return 0
