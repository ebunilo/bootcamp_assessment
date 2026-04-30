# MCP server & exploration

The assessment uses a **remote MCP server** over **Streamable HTTP**: JSON-RPC `POST` to a single URL (`MCP_URL`). The helper script [`explore_mcp.py`](../explore_mcp.py) runs `initialize`, `tools/list`, and `tools/call` using the stdlib only.

## Configuration

- Set **`MCP_URL`** (full path, often ending in `/mcp`).
- The script walks upward from the current working directory and loads the first **`.env`** found (e.g. parent repo root).
- Or export **`MCP_URL`** in the shell.

## Running `explore_mcp.py`

From a directory whose ancestor contains `.env` (paths shown from monorepo root):

```bash
python3 bootcamp_assessment/explore_mcp.py list-tools
python3 bootcamp_assessment/explore_mcp.py call verify_customer_pin \
  --json-args '{"email":"donaldgarcia@example.net","pin":"7912"}'
python3 bootcamp_assessment/explore_mcp.py verify-test-data
```

**Subcommands**

| Command | Purpose |
|---------|---------|
| **`list-tools`** | `initialize` + `tools/list`; prints server metadata and each tool’s name, summary, and argument keys. |
| **`call <tool>`** | **`--arg KEY=VALUE`** (repeat; values JSON-parsed when valid) or **`--json-args '{"k":"v"}'`**. Use **`--json-args`** for **`pin`** so it stays a **string** (numeric pins otherwise become integers and fail MCP validation). |
| **`verify-test-data`** | Reads [`test_data.json`](../test_data.json); calls **`verify_customer_pin`** per row. Override path with **`--data`**. |

**Flags:** **`--url`**, **`--insecure`** (skip TLS verify — common on macOS python.org Python; prefer fixing CA bundle when possible).

## Protocol (observed)

- Use **`Content-Type: application/json`** and **`Accept: application/json, text/event-stream`**. Omitting **`Accept`** caused **`Not Acceptable: Client must accept application/json`** for **`tools/call`** on this host.
- **`initialize`** with **`protocolVersion` `2024-11-05`** succeeded; server advertised **`tools`**, **`resources`**, **`prompts`** (with `listChanged: false` where applicable).

## Server snapshot (`tools/list`)

| Property | Value |
|----------|--------|
| Server name | `order-mcp` |
| Server version | `1.22.0` (at exploration time) |
| Tools count | **8** |

## Tools

| Tool | Purpose | Arguments |
|------|---------|-----------|
| `list_products` | List/filter catalog | `category`, `is_active` (optional) |
| `get_product` | Product by SKU | `sku` |
| `search_products` | Search | `query` |
| `get_customer` | Customer by UUID | `customer_id` |
| `verify_customer_pin` | Email + PIN | `email`, `pin` |
| `list_orders` | List/filter orders | `customer_id`, `status` (optional) |
| `get_order` | Order + lines | `order_id` |
| `create_order` | New order | `customer_id`, `items` |

`tools/call` responses included **`content`** (e.g. `type: "text"`), **`structuredContent.result`**, and **`isError`**.

## Test data

- [`test_data.csv`](../test_data.csv) — `Email`, `Pin`.
- [`test_data.json`](../test_data.json) — same rows as `{ "email", "pin" }` for **`verify-test-data`**.

## Error handling (`explore_mcp.py`)

| Situation | Behavior |
|-----------|----------|
| Missing **`MCP_URL`** / **`--url`** | **`SystemExit`** with short message. |
| Missing **`--data`** file | **`verify-test-data`** exits. |
| Bad **`--arg`** format | **`SystemExit`** (must be `KEY=VALUE`). **`--json-args`** invalid JSON → traceback. |
| **`HTTPError`** | Body decoded with **`errors="replace"`**, exit **`HTTP <status>: <body>`**. |
| Non-JSON body | Exit with **`Non-JSON response:`** + first 2000 chars. |
| **`URLError`** / TLS / timeout | Not caught inside **`rpc_post`** (use **`--insecure`** locally if needed). |
| **`list-tools`** JSON-RPC **`error`** | Print envelope, exit **1**. |
| **`call`** | Always prints full JSON-RPC response. |
| **`verify-test-data`** | Bad JSON / missing keys → exception. Per-row JSON-RPC **`error`** → log line and continue. |
| **`--insecure`** | Disables TLS verification for MCP only. |

Exploration matched **`tools/list`** from the configured endpoint at the time it was run.

- [Architecture](architecture.md) · [Guardrails](guardrails.md)
