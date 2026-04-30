"""
LangSmith observability: OpenAI auto-tracing (wrap_openai) and MCP tool spans.

Env (typically in .env):
  LANGSMITH_API_KEY or LANGCHAIN_API_KEY — required to export traces
  LANGSMITH_TRACING — default true when a key is present; set false to disable
  LANGSMITH_PROJECT or LANGCHAIN_PROJECT — defaults to meridian-electronics

https://docs.langchain.com/langsmith/trace-openai
"""

from __future__ import annotations

import os
from typing import Any

from mcp_client import load_dotenv, mcp_tools_call
from openai import OpenAI


def configure_langsmith() -> None:
    """Sync legacy LangChain env names and defaults (idempotent)."""
    key = (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY") or "").strip()
    if not key:
        return
    os.environ.setdefault("LANGSMITH_API_KEY", key)
    os.environ.setdefault("LANGCHAIN_API_KEY", key)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    proj = (os.environ.get("LANGSMITH_PROJECT") or os.environ.get("LANGCHAIN_PROJECT") or "").strip()
    if proj:
        os.environ.setdefault("LANGSMITH_PROJECT", proj)
        os.environ.setdefault("LANGCHAIN_PROJECT", proj)
    else:
        os.environ.setdefault("LANGSMITH_PROJECT", "meridian-electronics")
        os.environ.setdefault("LANGCHAIN_PROJECT", "meridian-electronics")


def langsmith_enabled() -> bool:
    key = (os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY") or "").strip()
    if not key:
        return False
    flag = os.environ.get("LANGSMITH_TRACING", "true").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return True


def ensure_observability_configured() -> None:
    load_dotenv()
    configure_langsmith()


def instrument_openai(client: OpenAI) -> OpenAI:
    """Wrap OpenAI client so chat completions (incl. streaming) export child runs to LangSmith."""
    ensure_observability_configured()
    if not langsmith_enabled():
        return client
    try:
        from langsmith.wrappers import wrap_openai

        return wrap_openai(client)
    except ImportError:
        return client


def traced_mcp_tools_call(
    url: str,
    req_id: int,
    name: str,
    arguments: dict[str, Any],
    *,
    ssl_context: Any,
) -> dict[str, Any]:
    """MCP tools/call as a LangSmith tool run (named after the MCP tool)."""
    ensure_observability_configured()
    if not langsmith_enabled():
        return mcp_tools_call(url, req_id, name, arguments, ssl_context=ssl_context)
    try:
        from langsmith import traceable

        @traceable(name=name, run_type="tool")
        def _invoke() -> dict[str, Any]:
            return mcp_tools_call(url, req_id, name, arguments, ssl_context=ssl_context)

        return _invoke()
    except ImportError:
        return mcp_tools_call(url, req_id, name, arguments, ssl_context=ssl_context)


def trace_turn(run_name: str):
    """Decorator for meridian.run_turn / meridian.stream_turn parent spans."""

    def _decorator(fn):
        try:
            from langsmith import traceable

            return traceable(name=run_name)(fn)
        except ImportError:
            return fn

    return _decorator
