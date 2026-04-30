# Observability (LangSmith)

Optional tracing via [`observability.py`](../observability.py):

- **`wrap_openai`** — LLM calls (including streaming) export runs when tracing is on.
- **`@trace_turn`** — parent spans for **`meridian.run_turn`** / **`meridian.stream_turn`**.
- **`traced_mcp_tools_call`** — MCP **`tools/call`** as named tool runs.

## Environment

Typical **`.env`** entries:

- **`LANGSMITH_API_KEY`** or **`LANGCHAIN_API_KEY`**
- **`LANGSMITH_TRACING`** — default **on** when a key is present; set **`false`** to disable export.
- **`LANGSMITH_PROJECT`** / **`LANGCHAIN_PROJECT`** — default **`meridian-electronics`** if unset.

[`configure_langsmith()`](../observability.py) syncs legacy LangChain env names. **`web_app`** startup logs when tracing is enabled.

Do not commit API keys; keep **`.env`** out of git.

- [Architecture](architecture.md)
