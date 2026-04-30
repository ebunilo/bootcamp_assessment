#!/usr/bin/env python3
"""
Meridian Electronics — AI support chatbot (OpenAI tool calling + MCP backend).

Uses a cost-efficient mini model by default (override with OPENAI_MODEL).
Loads OPENAI_API_KEY and MCP_URL from the environment or a nearby .env file.

  python3 chatbot.py
  python3 chatbot.py --insecure   # if MCP TLS verification fails locally
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from openai import OpenAI

from chat_service import DEFAULT_MODEL, SYSTEM_PROMPT, run_turn
from mcp_client import (
    env_mcp_insecure,
    load_dotenv,
    mcp_initialize,
    mcp_tools_list,
    mcp_tools_to_openai_functions,
    ssl_context_from_insecure_flag,
)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Meridian Electronics MCP chatbot")
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        help=f"OpenAI model id (default: env OPENAI_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS verification for MCP (same as MCP_INSECURE=1)",
    )
    parser.add_argument(
        "--max-tool-rounds",
        type=int,
        default=12,
        help="Max model↔tool iterations per user message",
    )
    args = parser.parse_args()

    mcp_url = os.environ.get("MCP_URL", "").strip()
    if not mcp_url:
        sys.exit("Set MCP_URL (or add it to .env).")

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        sys.exit("Set OPENAI_API_KEY (or add it to .env).")

    insecure = args.insecure or env_mcp_insecure()
    ssl_ctx = ssl_context_from_insecure_flag(insecure)

    init = mcp_initialize(mcp_url, ssl_context=ssl_ctx)
    if init.get("error"):
        sys.exit("MCP initialize failed: " + json.dumps(init["error"]))

    listed = mcp_tools_list(mcp_url, ssl_context=ssl_ctx)
    if listed.get("error"):
        sys.exit("MCP tools/list failed: " + json.dumps(listed["error"]))

    mcp_tools = listed.get("result", {}).get("tools") or []
    openai_tools = mcp_tools_to_openai_functions(mcp_tools)

    client = OpenAI(api_key=api_key)
    tool_id_counter = [100]

    print(
        "Meridian Electronics support (type 'quit' or Ctrl-D to exit)\n"
        f"Model: {args.model}  |  MCP tools: {len(openai_tools)}\n"
    )

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break

        messages.append({"role": "user", "content": line})
        messages, limited = run_turn(
            client,
            args.model,
            messages,
            openai_tools,
            mcp_url,
            ssl_ctx,
            tool_id_counter=tool_id_counter,
            max_tool_rounds=args.max_tool_rounds,
        )
        last = messages[-1]
        text = last.get("content") if last.get("role") == "assistant" else None
        if text:
            print(f"Assistant: {text}\n")
        else:
            print("Assistant: (no text reply)\n")
        if limited:
            print("(Stopped: max tool rounds reached for this message.)\n")


if __name__ == "__main__":
    main()
