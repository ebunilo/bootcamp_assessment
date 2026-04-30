# Automated tests

[`pytest`](https://docs.pytest.org/) lives under [`tests/`](../tests/). Tests **do not** call real MCP or OpenAI: **`web_app`** lifespan mocks **`_load_mcp_tools`** and **`stream_turn`** where needed ([`conftest.py`](../tests/conftest.py)).

## Run

```bash
cd bootcamp_assessment
python3 -m pip install -r requirements.txt
python3 -m pytest tests/ -v
```

Config: [`pytest.ini`](../pytest.ini) (`pythonpath = .`).

## Modules

| File | Coverage |
|------|----------|
| [`test_guardrails.py`](../tests/test_guardrails.py) | Allowed / blocked input, sanitization, **`GuardrailError`**. |
| [`test_mcp_client.py`](../tests/test_mcp_client.py) | **`mcp_tools_to_openai_functions`** (no HTTP). |
| [`test_web_app.py`](../tests/test_web_app.py) | **`GET /api/health`**, **`POST /api/sessions`**, **`POST /api/chat/stream`** (guardrail **400**, SSE mock, session **404**), **`GET /`**. |

- [Guardrails](guardrails.md) · [Architecture](architecture.md)
