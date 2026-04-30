# Input guardrails

End-user text is validated **server-side** before it is stored or sent to the LLM. Implementation: [`guardrails.py`](../guardrails.py). Blocked requests use a **generic refusal** (`MSG_BLOCKED`); the raw message is **not** returned to the client.

## API

- **`validate_customer_message(raw: str) -> str`** — sanitize, then policy checks. Success → sanitized string; failure → **`GuardrailError`** with **`public_message`** and **`code`**.

## Checks

| Category | Behavior |
|----------|----------|
| **Sanitization** | Strip **null** and most **Unicode controls** (keep `\n\r\t`). Collapse **12+** spaces/tabs. **NFKC** + strip zero-width chars for phrase matching. Empty → `empty`. |
| **Length** | Over **16 000** chars → `too_long`. |
| **Instruction / jailbreak** | Substrings on normalized text (`_BLOCK_PHRASES`) → `instruction_injection`. |
| **Channel smuggling** | Markers like fake system fences / template tokens (`_BLOCK_MARKERS`) → `channel_smuggling`. |
| **Unsafe code** | Regex (`_BLOCK_REGEX`): `eval(`, `exec(`, `os.system`, `subprocess`, fenced shell/python blocks, etc. → `unsafe_code`. |
| **Spam** | Single character dominates long messages → `spam_pattern`. |
| **Role confusion** | Many lines like `system:` / `assistant:` … → `role_confusion`. |
| **Format abuse** | Excess newlines → `format_abuse`. |

## Model policy

[`chat_service.py`](../chat_service.py) adds a **Security** paragraph to **`SYSTEM_PROMPT`**: user content is untrusted; refuse privileged-mode tricks, prompt exfiltration, and executing user-supplied code.

## Where it runs

| Location | Behavior |
|----------|----------|
| [`web_app.py`](../web_app.py) | **`POST /api/chat/stream`** validates before enqueueing user message → **400** + **`detail`**. **`GUARDRAIL_LOG=1`** logs **`code`** to stderr. |
| [`chat_service.py`](../chat_service.py) | Re-validates trailing **`user`** message in **`run_turn`** / **`stream_turn`**; drops bad turns; SSE **`guardrail`** event or assistant refusal. |
| [`chatbot.py`](../chatbot.py) | CLI: print refusal, continue. |
| [`static/chat.js`](../static/chat.js) | SSE **`guardrail`**; parses **400** **`detail`**. |

## Limitations

Heuristics are **not** auth, rate limits, WAF, or moderation APIs. Lists may **false-positive**; tune **`_BLOCK_PHRASES`** / **`_BLOCK_MARKERS`** as needed.

- [Architecture](architecture.md) · [Tests](tests.md)
