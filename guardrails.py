"""
Server-side input guardrails: prompt-injection / jailbreak heuristics, unsafe code patterns,
and basic abuse signals. Complements model behavior; not a substitute for secure backends.

Public errors are generic (no echo of user payload).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Customer-safe copy (do not reveal detection specifics).
MSG_BLOCKED = (
    "We're sorry — that message can't be processed. "
    "Please ask about products, availability, orders, or signing in to your account."
)


class GuardrailError(ValueError):
    """Raised when input must not be sent to the model."""

    def __init__(self, public_message: str = MSG_BLOCKED, *, code: str = "blocked"):
        super().__init__(public_message)
        self.public_message = public_message
        self.code = code


@dataclass(frozen=True)
class GuardrailResult:
    text: str
    """Sanitized text safe to store and forward."""


_ALLOWED_CTRL = frozenset("\n\r\t")
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_MULTI_SPACE = re.compile(r"[ \t]{12,}")

# Instruction override / jailbreak-style phrases (checked on NFKC-lowercased text).
_BLOCK_PHRASES = (
    "ignore all previous",
    "ignore previous instructions",
    "ignore the above",
    "ignore above instructions",
    "disregard all prior",
    "disregard all previous",
    "disregard the above",
    "override previous",
    "override your instructions",
    "new system prompt",
    "updated system prompt",
    "you are now ",
    "you must now ",
    "pretend you are",
    "act as if you are",
    "developer mode",
    "debug mode",
    "maintenance mode",
    "jailbreak",
    "dan mode",
    "show me your prompt",
    "reveal your prompt",
    "print your instructions",
    "repeat the words above",
    "repeat everything above",
    "what are your rules",
    "what is your system prompt",
    "bypass your",
    "without restrictions",
    "no restrictions mode",
    "uncensored mode",
    "simulate an uncensored",
    "ignore safety",
    "disable safety",
    "ignore ethical",
    "do anything now",
    "token-smuggling",
    "end of system",
    "hidden instructions",
    "secret instructions",
    "real instructions follow",
    "base64 decode and execute",
)

# Delimiter / fake channel markers often used to smuggle system content.
_BLOCK_MARKERS = (
    "```system",
    "[system]",
    "<<sys>>",
    "</system>",
    "<|im_start|>system",
    "<|im_start|>user",
    "<|im_start|>assistant",
    "<|im_end|>",
    "### instruction",
    "### system",
    "[INST]",
    "[/INST]",
    "<<SYS>>",
    "<<ASSISTANT>>",
)

# Dangerous code / execution patterns (checked on original text after light normalize).
_BLOCK_REGEX = (
    re.compile(r"\b(eval|exec)\s*\(", re.IGNORECASE),
    re.compile(r"\bos\.system\s*\(", re.IGNORECASE),
    re.compile(r"\bsubprocess\.(run|Popen|call|check_output)\s*\(", re.IGNORECASE),
    re.compile(r"\b__import__\s*\(", re.IGNORECASE),
    re.compile(r"\bcompile\s*\(\s*['\"]", re.IGNORECASE),
    re.compile(r"`{3,}\s*(python|py|bash|sh|zsh|powershell|pwsh)\b", re.IGNORECASE),
    re.compile(r"\b(importlib\.metadata|ctypes\.windll|pickle\.loads)\b", re.IGNORECASE),
    re.compile(r"\b(?:rm\s+-rf|mkfifo|/dev/tcp)\b", re.IGNORECASE),
)

_ROLE_LINE = re.compile(r"(?m)^\s*(system|assistant|user|tool)\s*:\s*\S")

# Homogeneous run used to pad / break filters.
_MIN_LEN_CHAR_SPAM = 120
_CHAR_SPAM_RATIO = 0.72


def _strip_control_chars(s: str) -> str:
    out: list[str] = []
    for ch in s:
        if ch in _ALLOWED_CTRL:
            out.append(ch)
            continue
        if ord(ch) == 0:
            continue
        cat = unicodedata.category(ch)
        if cat == "Cc":
            continue
        out.append(ch)
    return "".join(out)


def _normalize_for_policy(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = _ZERO_WIDTH.sub("", t)
    t = t.casefold()
    return t


def _char_dominance_spam(text: str) -> bool:
    if len(text) < _MIN_LEN_CHAR_SPAM:
        return False
    counts: dict[str, int] = {}
    for ch in text:
        if ch.isspace():
            continue
        counts[ch] = counts.get(ch, 0) + 1
    if not counts:
        return False
    most = max(counts.values())
    letters = sum(counts.values())
    return letters > 0 and (most / letters) >= _CHAR_SPAM_RATIO


def _role_marker_spam(text: str) -> bool:
    return len(_ROLE_LINE.findall(text)) >= 4


def validate_customer_message(raw: str) -> str:
    """
    Sanitize and policy-check end-user text.
    Returns sanitized string on success.
    Raises GuardrailError when the message must be rejected.
    """
    if raw is None:
        raise GuardrailError(code="empty")

    text = raw.strip()
    if not text:
        raise GuardrailError(code="empty")

    text = _strip_control_chars(text)
    text = _MULTI_SPACE.sub(" ", text)
    text = text.strip()
    if not text:
        raise GuardrailError(code="empty")

    # Length bound aligned with API schema; defense in depth.
    if len(text) > 16000:
        raise GuardrailError(code="too_long")

    policy_view = _normalize_for_policy(text)

    for phrase in _BLOCK_PHRASES:
        if phrase in policy_view:
            raise GuardrailError(code="instruction_injection")

    for marker in _BLOCK_MARKERS:
        if marker.casefold() in policy_view:
            raise GuardrailError(code="channel_smuggling")

    for rx in _BLOCK_REGEX:
        if rx.search(text):
            raise GuardrailError(code="unsafe_code")

    if _char_dominance_spam(text):
        raise GuardrailError(code="spam_pattern")

    if _role_marker_spam(text):
        raise GuardrailError(code="role_confusion")

    # Vertical whitespace flooding (paste attacks).
    if text.count("\n") > 80 or "\n" * 25 in text:
        raise GuardrailError(code="format_abuse")

    return text
