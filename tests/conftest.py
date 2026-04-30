"""Shared fixtures: FastAPI client with MCP bootstrap mocked (no real network)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Minimal OpenAI tool schema returned after MCP tools/list mapping
_FAKE_OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "verify_customer_pin",
            "description": "Verify PIN",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {"type": "string"},
                    "pin": {"type": "string"},
                },
                "required": ["email", "pin"],
            },
        },
    },
]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-placeholder")
    monkeypatch.setenv("MCP_URL", "https://test.invalid/mcp")
    monkeypatch.setenv("MCP_INSECURE", "1")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)

    # Avoid Docker/.env pulling unrelated vars during tests
    import web_app as web_app_module

    web_app_module.sessions.clear()

    with (
        patch.object(web_app_module, "_load_mcp_tools", return_value=_FAKE_OPENAI_TOOLS),
        patch.object(web_app_module, "instrument_openai", lambda c: c),
    ):
        with TestClient(web_app_module.app, raise_server_exceptions=True) as tc:
            yield tc

    web_app_module.sessions.clear()
