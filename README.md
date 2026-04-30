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

## Input guardrails

End-user text is checked **server-side** before it is stored in the model conversation or sent to the LLM. Implementation lives in [`guardrails.py`](guardrails.py). The API returns a **generic, customer-safe refusal** (see `MSG_BLOCKED` in that file); the original message is **not** echoed in error responses.

### API

- **`validate_customer_message(raw: str) -> str`** — strips unsafe control characters, normalizes whitespace, then runs policy checks. On success, returns the sanitized string; on failure, raises **`GuardrailError`** with **`public_message`** (always the standard refusal unless customized later) and **`code`** (machine-readable reason for logging).

### Checks performed

| Category | What happens |
|----------|----------------|
| **Sanitization** | Removes **null bytes** and most **Unicode control** characters (keeps `\n`, `\r`, `\t`). Collapses runs of **12+ spaces/tabs**. Applies **NFKC** normalization and strips common **zero-width** characters for substring checks. Empty-after-strip input is rejected (`code=empty`). |
| **Length** | Messages longer than **16 000** characters are rejected (`too_long`), aligned with the chat API schema. |
| **Instruction / jailbreak phrases** | Substring checks on **NFKC + casefold** text against **`_BLOCK_PHRASES`** (e.g. attempts to override prior instructions, “developer mode”, prompt exfiltration, DAN-style wording, “uncensored” / “bypass” phrasing, etc.). Match → `instruction_injection`. |
| **Channel smuggling** | Substring checks for **`_BLOCK_MARKERS`** (e.g. fake `system` code fences, bracketed `system` channels, common chat-template delimiters). Match → `channel_smuggling`. |
| **Malicious / execution patterns** | Regex set **`_BLOCK_REGEX`** on the post-strip text: e.g. `eval(`, `exec(`, `os.system`, `subprocess`, `__import__`, suspicious `compile(`, triple-backtick fenced `python` / shell blocks, and a few high-risk library / shell patterns. Match → `unsafe_code`. |
| **Spam / obfuscation** | If the message is long enough, **one character** dominating a large fraction of non-space content triggers `spam_pattern`. |
| **Role confusion** | Four or more lines matching `system:` / `assistant:` / `user:` / `tool:` at line start (with content) → `role_confusion`. |
| **Format abuse** | More than **80** newlines, or a run of **25+** consecutive newlines → `format_abuse`. |

### Model policy (defense in depth)

[`chat_service.py`](chat_service.py) appends a short **Security** block to **`SYSTEM_PROMPT`**: user text is **untrusted**; the model should not follow conflicting “privileged mode” instructions, reveal hidden prompts, or treat user content as executable code.

### Where it runs

| Location | Behavior |
|----------|----------|
| [`web_app.py`](web_app.py) | **`POST /api/chat/stream`**: runs **`validate_customer_message`** before appending the user turn. On failure → **HTTP 400** with JSON **`detail`** = the public refusal. Set **`GUARDRAIL_LOG=1`** to log **`[guardrail] blocked code=…`** to stderr (no user text). |
| [`chat_service.py`](chat_service.py) | **`_sanitize_tail_user_message`** re-validates the **last** message if it is a **`user`** turn at the start of **`run_turn`** and **`stream_turn`**. If the web layer is bypassed, a bad user turn is **dropped** and a refusal is returned: sync path appends an **assistant** message; streaming path emits **`guardrail`** then **`turn_done`**. |
| [`chatbot.py`](chatbot.py) | CLI validates each line before enqueueing; prints the refusal and continues. |
| [`static/chat.js`](static/chat.js) | Handles SSE **`guardrail`** events; for **400** responses, parses FastAPI **`detail`** so the user sees the refusal string instead of raw JSON. |

### Limitations

Heuristics **reduce** prompt injection, jailbreak-style text, and pasted “run this code” content; they do **not** replace authentication, rate limits, WAFs, content moderation APIs, or secure design of the MCP backend. Tight phrase lists can occasionally **false-positive** on rare legitimate wording; tune **`_BLOCK_PHRASES`** / **`_BLOCK_MARKERS`** in [`guardrails.py`](guardrails.py) if needed.

## Web UI, Uvicorn, and Docker

- Local / server process: `uvicorn web_app:app --host 0.0.0.0 --port 9100` (see [`web_app.py`](web_app.py) module docstring).
- **Docker** ([`Dockerfile`](Dockerfile), repo root [`docker-compose.yml`](../docker-compose.yml)): app listens on **9100**; Compose maps **`9100:9100`**. Open **`http://<host>:9100`**.

### Server layout: `bootcamp/` + clone `bootcamp_assessment`

On the VPS, if you keep the same folder name as in this repo:

```text
bootcamp/
  docker-compose.yml      # copy from repo parent (see ../docker-compose.yml)
  .env                    # OPENAI_API_KEY, MCP_URL, etc.
  bootcamp_assessment/    # git clone — same tree as local bootcamp_assessment/ (Dockerfile + web_app.py here)
```

the default build context **`./bootcamp_assessment`** matches — you do **not** need **`COMPOSE_BUILD_CONTEXT`** in **`.env`**.

Only set **`COMPOSE_BUILD_CONTEXT`** if the app directory lives somewhere else (different path or name).

- If Uvicorn logs **`Could not import module "web_app"`** or **`ls: cannot access '/app/web_app.py'`**:
  1. On the host, confirm **`test -f ./bootcamp_assessment/web_app.py`** (from the directory that contains **`docker-compose.yml`**). Run **`docker compose config`** and verify **`build.context`** points at that folder.
  2. Rebuild without cache: **`docker compose build --no-cache web`**.
  3. Inspect the **image** without Compose (skips bind mounts): **`docker run --rm meridian-electronics-web:latest ls -la /app/web_app.py`**. If this works but **`docker compose run web ls …`** fails, you have a **`volumes:`** entry (often in **`docker-compose.override.yml`**) mounting over **`/app`** — remove it or fix the host path.
  4. Run **`docker compose config`** and check for **`volumes`** under **`web`**.
- The Dockerfile runs **`python -c "import web_app"`** at build time so **`docker compose build`** fails if sources were not copied into the image.

---

Exploration was performed with **`explore_mcp.py`** against the configured endpoint; tool descriptions and schemas match what the server returned from **`tools/list`**.

## Images

### Video
![Product Demo](https://www.loom.com/share/0409f0d674594372903d3086c53c1090)

### Test from Deployed App. (Note the url)
![Live Customer support](images/inference_02.png)

## Test Guarails
![Guardrail test](images/guardrail.png)

# Monitoring
![Monitoring with LangSmith](images/monitoring.png)

