# Andela A3: AI Engineering Bootcamp Assessment

## MCP exploration

The assessment uses a **remote MCP server** exposed over **Streamable HTTP**: JSON-RPC `POST` requests to a single URL (see `MCP_URL`). The helper script [`explore_mcp.py`](explore_mcp.py) performs `initialize`, `tools/list`, and `tools/call` without extra dependencies (stdlib only).

### Configuration

- Set **`MCP_URL`** to the MCP HTTP endpoint (including path, e.g. `…/mcp`).
- The script loads the first **`.env`** it finds walking upward from the current working directory, so a `.env` in the parent repo root is picked up when you run commands from there.
- Optionally export `MCP_URL` in the shell instead of using `.env`.

### Running `explore_mcp.py`

From the repo root (or any directory whose ancestor contains `.env`):

```bash
python3 bootcamp_assessment/explore_mcp.py list-tools
python3 bootcamp_assessment/explore_mcp.py call verify_customer_pin \
  --arg email=donaldgarcia@example.net --arg pin=7912
python3 bootcamp_assessment/explore_mcp.py verify-test-data
```

- **`list-tools`** — runs `initialize` then `tools/list`, prints server metadata and each tool’s name, summary line, and argument keys.
- **`call <tool_name>`** — passes arguments via repeated `--arg KEY=VALUE` (values are JSON-parsed when valid) or `--json-args '{"key":"value"}'`.
- **`verify-test-data`** — reads [`test_data.json`](test_data.json) (override with `--data /path/to/file.json`) and calls **`verify_customer_pin`** for each `{ "email", "pin" }` row.

Global flags:

- **`--url …`** — override `MCP_URL`.
- **`--insecure`** — disable TLS certificate verification. Use only if your Python install fails verification (e.g. missing CA bundle on some macOS python.org installs). Prefer fixing the trust store when possible.

### Error handling (`explore_mcp.py`)

The exploration script uses small, explicit checks rather than a shared error-policy layer.

| Layer | Behavior |
|--------|----------|
| **Missing endpoint** | If `MCP_URL` is unset and `--url` is not passed, the program exits with a short message (`SystemExit`). |
| **Missing test data file** | `verify-test-data` exits if `--data` does not exist. |
| **CLI argument parsing** | `--arg` entries must look like `KEY=VALUE`; otherwise the program exits with a clear message. `--arg` values are parsed as JSON when possible; if parsing fails, the raw string is used. `--json-args` is passed to `json.loads` without a custom wrapper, so invalid JSON raises a normal traceback. |
| **HTTP layer** | **`urllib.error.HTTPError`** is caught: the response body is decoded with **`errors="replace"`** (so bad bytes do not crash decoding), then the process exits with **`HTTP <status>: <body>`**. |
| **Response body shape** | After a successful HTTP status, the body must be JSON. **`json.JSONDecodeError`** triggers exit with **`Non-JSON response:`** plus up to **2000** characters of the body for inspection. |
| **Timeouts** | Requests use a **60s** read timeout. **`URLError`**, timeouts, DNS failures, and TLS failures (when not using `--insecure`) are **not** caught inside `rpc_post`; they surface as Python exceptions unless addressed externally (e.g. **`--insecure`** for local CA issues). |
| **JSON-RPC errors** | **`list-tools`**: if either **`initialize`** or **`tools/list`** returns a top-level **`error`** object, the full JSON-RPC envelope is printed and the process exits with code **1**. |
| **`call`** | The full JSON-RPC response is always printed. **`initialize`** errors are **not** inspected before **`tools/call`**; JSON-RPC **`error`** or tool-level failures appear in the printed JSON (including MCP/tool messages such as missing **`Accept`**). |
| **`verify-test-data`** | **`test_data.json`** is parsed with **`json.loads`**; invalid JSON or rows missing **`email`** / **`pin`** raise a normal exception (not converted into a row-level message). For each row, if the response includes a top-level **`error`**, the script prints **`[<email>] ERROR: …`** and **continues** with the next row. Otherwise it prints text **`content`** when present, or falls back to pretty-printing the **`result`** object. It does **not** interpret **`result.isError`** or **`structuredContent`** beyond that fallback. |
| **TLS** | **`--insecure`** disables certificate verification and hostname checks to work around environments where Python’s trust store is incomplete; it does not add retries or backoff. |

### Protocol notes (observed behavior)

- Requests use **`Content-Type: application/json`** and **`Accept: application/json, text/event-stream`**. Omitting `Accept` caused **`Not Acceptable: Client must accept application/json`** for `tools/call` on this server.
- **`initialize`** with `protocolVersion` **`2024-11-05`** succeeded; the server advertised **`tools`**, **`resources`**, and **`prompts`** capability buckets (with `listChanged: false` where applicable).

### Server snapshot (`tools/list`)

| Property | Value |
|----------|--------|
| Server name | `order-mcp` |
| Server version | `1.22.0` (as returned at exploration time) |
| Tools count | **8** |

### Tools

| Tool | Purpose (short) | Arguments |
|------|-------------------|-----------|
| `list_products` | List/filter catalog | `category` (optional), `is_active` (optional) |
| `get_product` | Product details by SKU | `sku` (required) |
| `search_products` | Search name/description | `query` (required) |
| `get_customer` | Customer by UUID | `customer_id` (required) |
| `verify_customer_pin` | Auth via email + PIN | `email`, `pin` (required) |
| `list_orders` | List/filter orders | `customer_id` (optional), `status` (optional) |
| `get_order` | Order details + lines | `order_id` (required) |
| `create_order` | New order | `customer_id`, `items` (required) |

Tool responses in JSON-RPC `tools/call` results included **`content`** (e.g. `type: "text"`) and **`structuredContent`** with a **`result`** string; **`isError`** indicated failure vs success.

### Test data

- [`test_data.csv`](test_data.csv) — source table (`Email`, `Pin`).
- [`test_data.json`](test_data.json) — same rows as objects with lowercase keys `email` / `pin`, suitable for scripting and for **`verify-test-data`**.

---

Exploration was performed with **`explore_mcp.py`** against the configured endpoint; tool descriptions and schemas match what the server returned from **`tools/list`**.
