#!/usr/bin/env python3
"""
Explore a Streamable HTTP MCP endpoint: initialize, list tools, call tools.

Loads MCP_URL from the environment, or from a .env file in cwd / parents.
Requires Accept: application/json (and optionally text/event-stream) on POSTs.

Examples:
  python explore_mcp.py list-tools
  python explore_mcp.py --insecure list-tools   # if SSL verify fails on your Python
  python explore_mcp.py call verify_customer_pin --arg email=a@b.net --arg pin=1234
  python explore_mcp.py verify-test-data
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ACCEPT_HEADER = "application/json, text/event-stream"
DEFAULT_TEST_DATA = Path(__file__).resolve().parent / "test_data.json"


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


def rpc_post(
    url: str,
    payload: dict[str, Any],
    *,
    ssl_context: ssl.SSLContext | None,
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
        with urllib.request.urlopen(req, timeout=60, context=ssl_context) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code}: {body}") from e
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise SystemExit(f"Non-JSON response:\n{body[:2000]}") from None


def mcp_initialize(url: str, *, ssl_context: ssl.SSLContext | None) -> dict[str, Any]:
    return rpc_post(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "explore_mcp", "version": "0.1.0"},
            },
        },
        ssl_context=ssl_context,
    )


def mcp_tools_list(url: str, *, ssl_context: ssl.SSLContext | None) -> dict[str, Any]:
    return rpc_post(
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
    return rpc_post(
        url,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        ssl_context=ssl_context,
    )


def cmd_list_tools(url: str, *, ssl_context: ssl.SSLContext | None) -> None:
    init = mcp_initialize(url, ssl_context=ssl_context)
    if "error" in init:
        print(json.dumps(init, indent=2))
        sys.exit(1)
    tools_resp = mcp_tools_list(url, ssl_context=ssl_context)
    if "error" in tools_resp:
        print(json.dumps(tools_resp, indent=2))
        sys.exit(1)
    tools = tools_resp.get("result", {}).get("tools", [])
    print(f"Server: {init.get('result', {}).get('serverInfo', {})}")
    print(f"Tools ({len(tools)}):\n")
    for t in tools:
        name = t.get("name")
        desc = (t.get("description") or "").strip().split("\n")[0]
        print(f"  • {name}")
        if desc:
            print(f"      {desc}")
        schema = t.get("inputSchema") or {}
        props = schema.get("properties") or {}
        req = set(schema.get("required") or [])
        if props:
            parts = []
            for k, v in props.items():
                tag = f"{k}*" if k in req else k
                parts.append(tag)
            print(f"      args: {', '.join(parts)}")
        print()


def cmd_call(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    ssl_context: ssl.SSLContext | None,
) -> None:
    mcp_initialize(url, ssl_context=ssl_context)
    out = mcp_tools_call(url, 3, tool_name, arguments, ssl_context=ssl_context)
    print(json.dumps(out, indent=2))


def cmd_verify_test_data(url: str, json_path: Path, *, ssl_context: ssl.SSLContext | None) -> None:
    rows = json.loads(json_path.read_text())
    mcp_initialize(url, ssl_context=ssl_context)
    for i, row in enumerate(rows):
        email = row["email"]
        pin = row["pin"]
        resp = mcp_tools_call(
            url,
            10 + i,
            "verify_customer_pin",
            {"email": email, "pin": pin},
            ssl_context=ssl_context,
        )
        err = resp.get("error")
        if err:
            print(f"[{email}] ERROR: {err}")
            continue
        result = resp.get("result") or {}
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        preview = "\n".join(texts).strip() or json.dumps(result, indent=2)
        print(f"[{email}]\n{preview}\n")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Explore an HTTP MCP endpoint")
    parser.add_argument(
        "--url",
        default=os.environ.get("MCP_URL", ""),
        help="MCP HTTP URL (default: env MCP_URL)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS certificate verification (use if Python lacks CA certs, e.g. macOS python.org install)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _ssl_ctx(ns: argparse.Namespace) -> ssl.SSLContext | None:
        if ns.insecure:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        return None

    p_list = sub.add_parser("list-tools", help="Print tools from tools/list")

    def _list(ns: argparse.Namespace) -> None:
        cmd_list_tools(ns.url, ssl_context=_ssl_ctx(ns))

    p_list.set_defaults(func=_list)

    p_call = sub.add_parser("call", help="Call a tool by name")
    p_call.add_argument("tool_name")
    p_call.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Argument (repeatable). Values are parsed as JSON if possible.",
    )
    p_call.add_argument("--json-args", help="JSON object string for all arguments")

    def _do_call(a: argparse.Namespace) -> None:
        args: dict[str, Any] = {}
        if a.json_args:
            args.update(json.loads(a.json_args))
        for pair in a.arg:
            if "=" not in pair:
                raise SystemExit(f"Bad --arg (need KEY=VALUE): {pair}")
            k, _, v = pair.partition("=")
            k = k.strip()
            try:
                args[k] = json.loads(v)
            except json.JSONDecodeError:
                args[k] = v
        cmd_call(a.url, a.tool_name, args, ssl_context=_ssl_ctx(a))

    p_call.set_defaults(func=_do_call)

    p_verify = sub.add_parser(
        "verify-test-data",
        help="Call verify_customer_pin for each row in test_data.json",
    )
    p_verify.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_TEST_DATA,
        help=f"path to JSON array (default: {DEFAULT_TEST_DATA})",
    )

    def _do_verify(a: argparse.Namespace) -> None:
        if not a.data.is_file():
            raise SystemExit(f"Missing file: {a.data}")
        cmd_verify_test_data(a.url, a.data, ssl_context=_ssl_ctx(a))

    p_verify.set_defaults(func=_do_verify)

    args = parser.parse_args()
    if not args.url:
        raise SystemExit("Set MCP_URL or pass --url")
    args.func(args)


if __name__ == "__main__":
    main()
