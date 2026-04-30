"""Unit tests for MCP client helpers (no network)."""

from __future__ import annotations

from mcp_client import mcp_tools_to_openai_functions


def test_mcp_tools_to_openai_skips_nameless_tool() -> None:
    out = mcp_tools_to_openai_functions(
        [
            {"name": "ok_tool", "description": "D", "inputSchema": {"type": "object", "properties": {}}},
            {"description": "no name"},
        ]
    )
    assert len(out) == 1
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "ok_tool"
    assert out[0]["function"]["parameters"] == {"type": "object", "properties": {}}
