"""Shared Meridian chat logic: system prompt, MCP formatting, agent turns (sync + stream)."""

from __future__ import annotations

import json
import os
from typing import Any, Iterator

from openai import OpenAI

from mcp_client import MCPJSONError, MCPTransportError, mcp_tools_call

# Cost-efficient default; override with env OPENAI_MODEL.
DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are the Meridian Electronics virtual customer support assistant.

You help customers with:
- Product availability and catalog questions (search, list, or fetch by SKU).
- Authenticating returning customers using verify_customer_pin when they provide email and PIN.
- Order history and order details (list_orders, get_order) after you know their customer_id from verification or context.
- Placing new orders (create_order) only after the customer is verified and you have confirmed SKU, quantities, and prices from get_product or list_products.

Policies:
- Be concise, professional, and friendly.
- Use tools for facts; do not invent inventory, prices, or order data.
- Before create_order, confirm line items and that stock/pricing look correct from tool output.
- If a tool returns an error, explain it simply and suggest next steps (e.g. wrong PIN, unknown SKU).
- Never ask for or repeat full payment card numbers; this backend handles payment state abstractly.
"""


def format_mcp_tool_result(envelope: dict[str, Any]) -> str:
    if err := envelope.get("error"):
        return "Tool returned error: " + json.dumps(err, ensure_ascii=False)
    result = envelope.get("result") or {}
    texts: list[str] = []
    for block in result.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            texts.append(str(block["text"]))
    if texts:
        body = "\n".join(texts).strip()
    elif result.get("structuredContent") is not None:
        body = json.dumps(result["structuredContent"], ensure_ascii=False)
    else:
        body = json.dumps(result, ensure_ascii=False)
    if result.get("isError"):
        body = "[isError=true]\n" + body
    return body


def run_turn(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    openai_tools: list[dict[str, Any]],
    mcp_url: str,
    ssl_context: Any,
    *,
    tool_id_counter: list[int],
    max_tool_rounds: int,
) -> tuple[list[dict[str, Any]], bool]:
    """One user-visible turn; returns (updated_messages, hit_tool_round_limit)."""
    rounds = 0
    hit_limit = False
    while rounds < max_tool_rounds:
        rounds += 1
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
        )
        choice = completion.choices[0]
        msg = choice.message

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content,
        }
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if not msg.tool_calls:
            return messages, False

        for tc in msg.tool_calls:
            tool_id_counter[0] += 1
            req_id = tool_id_counter[0]
            name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            try:
                raw = mcp_tools_call(mcp_url, req_id, name, arguments, ssl_context=ssl_context)
                content = format_mcp_tool_result(raw)
            except MCPTransportError as e:
                content = f"MCP HTTP failure: {e} body={e.body[:1500] if e.body else ''}"
            except MCPJSONError as e:
                content = f"MCP non-JSON response: {e}"

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                }
            )

        if choice.finish_reason == "length":
            hit_limit = True
            break

    limited = hit_limit or rounds >= max_tool_rounds
    if limited and messages and messages[-1].get("role") == "tool":
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        msg = completion.choices[0].message
        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
            }
        )
    return messages, limited


def _merge_stream_tool_calls(
    tool_calls_accum: dict[int, dict[str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx in sorted(tool_calls_accum.keys()):
        raw = tool_calls_accum[idx]
        out.append(
            {
                "id": raw.get("id", ""),
                "type": "function",
                "function": {
                    "name": raw.get("name", ""),
                    "arguments": raw.get("arguments", "") or "{}",
                },
            }
        )
    return out


def stream_turn(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    openai_tools: list[dict[str, Any]],
    mcp_url: str,
    ssl_context: Any,
    *,
    tool_id_counter: list[int],
    max_tool_rounds: int,
) -> Iterator[dict[str, Any]]:
    """
    Stream one user turn as JSON-serializable event dicts for SSE.
    Events: delta, tools_pending, tool_result, turn_done, error
    """
    rounds = 0
    hit_limit = False

    while rounds < max_tool_rounds:
        rounds += 1
        tool_calls_accum: dict[int, dict[str, str]] = {}
        content_buf: list[str] = []
        finish_reason: str | None = None

        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto",
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                ch = chunk.choices[0]
                if ch.finish_reason:
                    finish_reason = ch.finish_reason
                delta = ch.delta
                if delta is None:
                    continue
                if delta.content:
                    content_buf.append(delta.content)
                    yield {"type": "delta", "text": delta.content}
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        i = tc.index
                        if i not in tool_calls_accum:
                            tool_calls_accum[i] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            tool_calls_accum[i]["id"] += tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_accum[i]["name"] += tc.function.name
                            if tc.function.arguments:
                                tool_calls_accum[i]["arguments"] += tc.function.arguments
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return

        tc_list = _merge_stream_tool_calls(tool_calls_accum) if tool_calls_accum else []
        text_joined = "".join(content_buf)
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": text_joined if text_joined else None,
        }
        if tc_list:
            assistant_msg["tool_calls"] = tc_list
        messages.append(assistant_msg)

        if not tc_list:
            yield {"type": "turn_done", "limited": False}
            return

        names = [t["function"]["name"] for t in tc_list]
        yield {"type": "tools_pending", "names": names}

        for tc in tc_list:
            tc_id = tc["id"]
            name = tc["function"]["name"]
            tool_id_counter[0] += 1
            req_id = tool_id_counter[0]
            try:
                arguments = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            try:
                raw = mcp_tools_call(mcp_url, req_id, name, arguments, ssl_context=ssl_context)
                content = format_mcp_tool_result(raw)
                ok = not raw.get("error") and not (raw.get("result") or {}).get("isError")
            except MCPTransportError as e:
                content = f"MCP HTTP failure: {e} body={e.body[:1500] if e.body else ''}"
                ok = False
            except MCPJSONError as e:
                content = f"MCP non-JSON response: {e}"
                ok = False

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": content,
                }
            )
            preview = content[:280] + ("…" if len(content) > 280 else "")
            yield {"type": "tool_result", "name": name, "ok": ok, "preview": preview}

        if finish_reason == "length":
            hit_limit = True
            break

    limited = hit_limit or rounds >= max_tool_rounds
    if limited and messages and messages[-1].get("role") == "tool":
        try:
            stream2 = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
            )
            for chunk in stream2:
                if not chunk.choices:
                    continue
                d = chunk.choices[0].delta
                if d and d.content:
                    yield {"type": "delta", "text": d.content}
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            yield {"type": "turn_done", "limited": True}
            return

    yield {"type": "turn_done", "limited": limited}


def default_model() -> str:
    return os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
