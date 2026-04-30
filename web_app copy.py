#!/usr/bin/env python3
"""
Meridian Electronics — customer-facing chat UI (FastAPI + SSE streaming).

  cd bootcamp_assessment && python3 -m uvicorn web_app:app --reload --host 0.0.0.0 --port 8000

Env: OPENAI_API_KEY, MCP_URL, OPENAI_MODEL (optional), MCP_INSECURE (optional),
     LANGSMITH_API_KEY + LANGSMITH_TRACING (optional, see observability.py).
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import urllib.error
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, Field

from chat_service import SYSTEM_PROMPT, default_model, stream_turn
from guardrails import GuardrailError, validate_customer_message
from mcp_client import (
    env_mcp_insecure,
    load_dotenv,
    mcp_initialize,
    mcp_tools_list,
    mcp_tools_to_openai_functions,
    ssl_context_from_insecure_flag,
)
from observability import configure_langsmith, instrument_openai, langsmith_enabled

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_SESSIONS = 2000

sessions: dict[str, dict[str, Any]] = {}
app_state: dict[str, Any] = {}


def _is_tls_verify_failure(exc: BaseException) -> bool:
    """True when urllib/ssl failed because local Python cannot verify the server cert."""
    if isinstance(exc, ssl.SSLError):
        return True
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, ssl.SSLError):
        return True
    msg = str(exc).lower()
    return "certificate verify failed" in msg or "sslcertverificationerror" in msg.replace(" ", "")


def _load_mcp_tools(mcp_url: str, ssl_ctx: ssl.SSLContext | None) -> list[dict[str, Any]]:
    init = mcp_initialize(mcp_url, ssl_context=ssl_ctx)
    if init.get("error"):
        raise RuntimeError(f"MCP initialize error: {init['error']}")
    listed = mcp_tools_list(mcp_url, ssl_context=ssl_ctx)
    if listed.get("error"):
        raise RuntimeError(f"MCP tools/list error: {listed['error']}")
    mcp_tools = listed.get("result", {}).get("tools") or []
    return mcp_tools_to_openai_functions(mcp_tools)


def _evict_sessions_if_needed() -> None:
    if len(sessions) <= MAX_SESSIONS:
        return
    # Drop oldest keys (dict preserves insertion order in Py3.7+)
    overflow = len(sessions) - MAX_SESSIONS
    for _ in range(overflow):
        sessions.pop(next(iter(sessions)), None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    configure_langsmith()
    if langsmith_enabled():
        print(
            f"LangSmith tracing on (project={os.environ.get('LANGSMITH_PROJECT', 'default')})",
            file=sys.stderr,
        )
    mcp_url = os.environ.get("MCP_URL", "").strip()
    if not mcp_url:
        print("WARNING: MCP_URL not set — chat will fail until configured.", file=sys.stderr)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("WARNING: OPENAI_API_KEY not set — chat will fail until configured.", file=sys.stderr)

    insecure_requested = env_mcp_insecure()
    ssl_ctx: ssl.SSLContext | None = ssl_context_from_insecure_flag(insecure_requested)
    openai_tools: list[dict[str, Any]] = []

    if mcp_url and api_key:
        try:
            openai_tools = _load_mcp_tools(mcp_url, ssl_ctx)
            print(f"MCP ready: {len(openai_tools)} tools", file=sys.stderr)
        except (urllib.error.URLError, ssl.SSLError, OSError) as e:
            if not insecure_requested and _is_tls_verify_failure(e):
                print(
                    "MCP TLS certificate verification failed (common with python.org Python on macOS). "
                    "Retrying with verification disabled. Set MCP_INSECURE=1 to silence this, "
                    "or run Install Certificates.command from your Python folder.",
                    file=sys.stderr,
                )
                ssl_ctx = ssl_context_from_insecure_flag(True)
                try:
                    openai_tools = _load_mcp_tools(mcp_url, ssl_ctx)
                    print(f"MCP ready: {len(openai_tools)} tools (insecure TLS)", file=sys.stderr)
                except Exception as e2:
                    print("MCP bootstrap failed after insecure retry:", e2, file=sys.stderr)
            else:
                print("MCP bootstrap failed:", e, file=sys.stderr)
        except RuntimeError as e:
            print(e, file=sys.stderr)

    app_state["mcp_url"] = mcp_url
    app_state["ssl_ctx"] = ssl_ctx
    app_state["openai_tools"] = openai_tools
    base_client = OpenAI(api_key=api_key) if api_key else None
    app_state["client"] = instrument_openai(base_client) if base_client else None
    app_state["model"] = default_model()
    app_state["max_tool_rounds"] = int(os.environ.get("MAX_TOOL_ROUNDS", "12"))

    yield


app = FastAPI(title="Meridian Support", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")


class SessionCreateResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=16000)


@app.get("/api/health")
async def health():
    ok = bool(app_state.get("client") and app_state.get("mcp_url") and app_state.get("openai_tools"))
    return {"ok": ok, "model": app_state.get("model")}


@app.post("/api/sessions", response_model=SessionCreateResponse)
async def create_session():
    sid = uuid4().hex
    sessions[sid] = {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        "tool_seq": 100,
        "lock": threading.Lock(),
    }
    _evict_sessions_if_needed()
    return SessionCreateResponse(session_id=sid)


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest):
    client = app_state.get("client")
    mcp_url = app_state.get("mcp_url")
    tools = app_state.get("openai_tools") or []
    ssl_ctx = app_state.get("ssl_ctx")
    model = app_state.get("model")
    max_rounds = app_state.get("max_tool_rounds", 12)

    if not client or not mcp_url or not tools:
        raise HTTPException(status_code=503, detail="Service not configured (OpenAI or MCP).")

    sess = sessions.get(body.session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="Unknown session.")

    try:
        safe_message = validate_customer_message(body.message)
    except GuardrailError as e:
        if os.environ.get("GUARDRAIL_LOG", "").strip().lower() in ("1", "true", "yes"):
            print(f"[guardrail] blocked code={e.code}", file=sys.stderr)
        raise HTTPException(status_code=400, detail=e.public_message) from e

    def sse_bytes() -> Any:
        lock = sess["lock"]
        with lock:
            messages = sess["messages"]
            messages.append({"role": "user", "content": safe_message})
            tool_id_counter = [int(sess["tool_seq"])]

            for ev in stream_turn(
                client,
                model,
                messages,
                tools,
                mcp_url,
                ssl_ctx,
                tool_id_counter=tool_id_counter,
                max_tool_rounds=max_rounds,
            ):
                line = "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
                yield line.encode("utf-8")

            sess["tool_seq"] = tool_id_counter[0]

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(sse_bytes(), media_type="text/event-stream", headers=headers)


@app.get("/")
async def index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=500, detail="UI not built: static/index.html missing.")
    return FileResponse(index_path)
