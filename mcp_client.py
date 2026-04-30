"""HTTP JSON-RPC client for Streamable MCP (shared by chatbot and scripts)."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ACCEPT_HEADER = "application/json, text/event-stream"


class MCPTransportError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class MCPJSONError(Exception):
    pass


def load_dotenv() -> None:
    """Set missing env vars from the first .env found walking up from cwd."""
    here = Path.cwd()
    for base in [here, *here.parents]:
        env_path = base / ".env"
        if not env_path.is_file():
            continue
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
        break


def ssl_context_from_insecure_flag(insecure: bool) -> ssl.SSLContext | None:
    if not insecure:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def env_mcp_insecure() -> bool:
    return os.environ.get("MCP_INSECURE", "").strip().lower() in ("1", "true", "yes")


def post_json_rpc(
    url: str,
    payload: dict[str, Any],
    *,
    ssl_context: ssl.SSLContext | None,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": ACCEPT_HEADER,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ssl_context) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise MCPTransportError(
            f"HTTP {e.code}",
            status_code=e.code,
            body=raw,
        ) from e
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise MCPJSONError(body[:2000]) from e


def mcp_initialize(url: str, *, ssl_context: ssl.SSLContext | None) -> dict[str, Any]:
    return post_json_rpc(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "meridian_chatbot", "version": "0.1.0"},
            },
        },
        ssl_context=ssl_context,
    )


def mcp_tools_list(url: str, *, ssl_context: ssl.SSLContext | None) -> dict[str, Any]:
    return post_json_rpc(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ssl_context=ssl_context,
    )


def mcp_tools_call(
    url: str,
    req_id: int,
    name: str,
    arguments: dict[str, Any],
    *,
    ssl_context: ssl.SSLContext | None,
) -> dict[str, Any]:
    return post_json_rpc(
        url,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        ssl_context=ssl_context,
    )


def mcp_tools_to_openai_functions(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map MCP tools/list entries to OpenAI Chat Completions tool schema."""
    out: list[dict[str, Any]] = []
    for t in mcp_tools:
        name = t.get("name")
        if not name:
            continue
        schema = t.get("inputSchema") or {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (t.get("description") or "").strip(),
                    "parameters": schema,
                },
            }
        )
    return out
