"""Groq (OpenAI-compatible) client for optional grounded explanations.

Keys are held in memory only. They are never written to disk, logged, cached,
included in exception text, or copied into the Excel report. Only structured
facts from a flagged row are sent to the model, and a response containing a
number that is absent from those facts is discarded.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping, Sequence

import requests

from detection import FLAG_COLUMNS, FLAG_LABELS
from utils import format_date, format_pkr

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
CHAT_URL = f"{GROQ_BASE_URL}/chat/completions"
MODELS_URL = f"{GROQ_BASE_URL}/models"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
REQUEST_TIMEOUT = 20
RETRYABLE_STATUS = {401, 403, 408, 429, 500, 502, 503, 504}
EXCLUDED_MODEL_TOKENS = ("whisper", "tts", "guard", "embed")

SYSTEM_PROMPT = (
    "Use only these facts; do not invent amounts, names or dates; "
    "3 sentences max; clear simple English."
)
SYSTEM_PROMPT_ROMAN_URDU = (
    "Use only these facts; do not invent amounts, names or dates; "
    "3 sentences max; clear simple Roman Urdu (Urdu written with English letters)."
)

MODEL_CATALOG = (
    ("llama-3.3-70b-versatile", "Balanced quality and speed (default)"),
    ("openai/gpt-oss-120b", "Strongest reasoning; runs with low reasoning effort"),
    ("openai/gpt-oss-20b", "Very fast and cheap"),
    ("llama-3.1-8b-instant", "Fastest and lightest"),
)

NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalize_keys(keys: object) -> list[str]:
    """Accept a string, newline list, or sequence and return unique keys."""
    if keys is None:
        return []
    if isinstance(keys, str):
        parts = re.split(r"[\s,]+", keys)
    else:
        parts = []
        for item in keys:
            parts.extend(re.split(r"[\s,]+", str(item)))
    unique: list[str] = []
    for part in parts:
        key = part.strip().strip('"').strip("'")
        if key and key not in unique:
            unique.append(key)
    return unique


def env_keys() -> list[str]:
    """Read comma-separated keys from GROQ_API_KEYS or GROQ_KEYS in the environment."""
    for name in ("GROQ_API_KEYS", "GROQ_KEYS"):
        value = os.environ.get(name)
        if value:
            return normalize_keys(value)
    return []


def masked(key: str) -> str:
    """Return a safe display label for a key."""
    text = str(key or "")
    if len(text) <= 8:
        return "gsk_...****"
    return f"{text[:4]}...{text[-4:]}"


def _active_flags(row: Mapping[str, object]) -> list[str]:
    return [
        FLAG_LABELS[column]
        for column in FLAG_COLUMNS
        if row.get(column) is True or str(row.get(column, False)).lower() == "true"
    ]


def facts_from_row(row: Mapping[str, object]) -> dict[str, object]:
    """Extract only verifiable fields for the optional LLM call."""
    reasons = row.get("flag_reasons")
    if isinstance(reasons, list):
        reasons = [str(reason) for reason in reasons]
    else:
        reasons = []

    amount = row.get("Amount")
    limit = row.get("approval_limit_used")
    facts: dict[str, object] = {
        "EntryID": str(row.get("EntryID", "")),
        "Date": format_date(row.get("Date")),
        "Vendor": str(row.get("Vendor", "")),
        "Account": str(row.get("Account", "")),
        "Amount": format_pkr(amount),
        "AmountValue": round(float(amount), 2) if amount is not None and str(amount) not in ("", "nan") else None,
        "PostedBy": str(row.get("PostedBy", "")),
        "ApprovedBy": str(row.get("ApprovedBy", "")),
        "RiskScore": int(row.get("risk_score", 0) or 0),
        "RiskLevel": str(row.get("risk_level", "")),
        "Flags": _active_flags(row),
        "RuleReasons": reasons,
    }
    if limit is not None and str(limit) not in ("", "nan"):
        facts["ApprovalLimit"] = format_pkr(limit)
        facts["ApprovalLimitValue"] = round(float(limit), 2)
        try:
            facts["ShareOfLimit"] = round(float(amount) / float(limit) * 100.0, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    gap = row.get("duplicate_gap_days")
    if gap is not None and str(gap) != "nan":
        facts["DuplicateGapDays"] = int(float(gap))
    reference = row.get("duplicate_invoice")
    if reference is not None and str(reference) != "nan":
        facts["InvoiceReference"] = str(reference)
    return facts


def _allowed_number_tokens(facts: Mapping[str, object]) -> set[str]:
    """Return every number-like token that legitimately appears in the facts."""
    serialized = json.dumps(facts, ensure_ascii=False, default=str)
    allowed = set()
    for token in NUMBER_PATTERN.findall(serialized):
        allowed.add(token.replace(",", ""))
    # Small counts are safe: flags, sentences, dates, and gap days.
    allowed.update({"1", "2", "3", "4", "5", "6", "7", "8", "9", "0"})
    return allowed


def is_grounded(text: str, facts: Mapping[str, object]) -> bool:
    """Return False when the text contains a number absent from the facts."""
    allowed = _allowed_number_tokens(facts)
    for token in NUMBER_PATTERN.findall(str(text)):
        normalized = token.replace(",", "")
        if normalized not in allowed:
            return False
    return True


class GroqClient:
    """Small round-robin client for the Groq OpenAI-compatible API."""

    def __init__(self, keys: object = None, timeout: int = REQUEST_TIMEOUT) -> None:
        self.keys = normalize_keys(keys if keys is not None else env_keys())
        self.timeout = timeout
        self._next = 0

    @property
    def has_keys(self) -> bool:
        return bool(self.keys)

    def _ordered(self) -> list[str]:
        if not self.keys:
            return []
        return self.keys[self._next :] + self.keys[: self._next]

    def _advance(self) -> None:
        if self.keys:
            self._next = (self._next + 1) % len(self.keys)

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.2,
        max_tokens: int = 220,
    ) -> str | None:
        """Call the chat endpoint, rotating keys on auth, quota, or network errors."""
        if not self.keys:
            return None

        payload: dict[str, object] = {
            "model": model,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
            "messages": list(messages),
        }
        if str(model).startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = "low"

        for key in self._ordered():
            try:
                response = requests.post(
                    CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.RequestException:
                self._advance()
                continue

            if response.status_code == 200:
                try:
                    body = response.json()
                    choices = body.get("choices") or []
                    content = choices[0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError):
                    self._advance()
                    continue
                text = str(content or "").strip()
                if text:
                    return text
                self._advance()
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except (TypeError, ValueError):
                    delay = 0.0
                if delay > 0:
                    time.sleep(min(delay, 2.0))
            if response.status_code in RETRYABLE_STATUS:
                self._advance()
                continue
            self._advance()

        return None

    def test_key(self, key: str) -> str:
        """Return ``valid``, ``invalid``, ``rate-limited``, or ``error``.

        The key is used only in the request header and never appears in the
        returned status or in a raised message.
        """
        try:
            response = requests.get(
                MODELS_URL,
                headers={"Authorization": f"Bearer {key}"},
                timeout=self.timeout,
            )
        except requests.RequestException:
            return "error"
        if response.status_code == 200:
            return "valid"
        if response.status_code == 429:
            return "rate-limited"
        if response.status_code in (401, 403):
            return "invalid"
        return "error"

    def list_models(self) -> list[str]:
        """Return chat model ids from the first key that responds."""
        if not self.keys:
            return []
        for key in self._ordered():
            try:
                response = requests.get(
                    MODELS_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=self.timeout,
                )
            except requests.RequestException:
                self._advance()
                continue
            if response.status_code != 200:
                self._advance()
                continue
            try:
                body = response.json()
                items = body.get("data") or []
                model_ids = [str(item.get("id")) for item in items if item.get("id")]
            except (ValueError, AttributeError, TypeError):
                self._advance()
                continue
            filtered = [
                model
                for model in model_ids
                if not any(token in model.lower() for token in EXCLUDED_MODEL_TOKENS)
            ]
            return sorted(set(filtered))
        return []


def fallback_models() -> list[str]:
    """Return the static model list used when discovery fails."""
    return [model for model, _ in MODEL_CATALOG]


def explain_entry(
    row: Mapping[str, object],
    keys: object,
    model: str = DEFAULT_MODEL,
    language: str = "English",
    temperature: float = 0.2,
    max_tokens: int = 220,
) -> str | None:
    """Return a grounded LLM explanation, or None to trigger the template."""
    clean_keys = normalize_keys(keys)
    if not clean_keys:
        return None

    facts = facts_from_row(row)
    system_prompt = (
        SYSTEM_PROMPT_ROMAN_URDU if language == "Roman Urdu" else SYSTEM_PROMPT
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": "FACTS:\n" + json.dumps(facts, ensure_ascii=False, default=str),
        },
    ]
    client = GroqClient(clean_keys)
    text = client.chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if not text:
        return None
    if not is_grounded(text, facts):
        return None
    return text


def source_label(model: str) -> str:
    """Return the user-facing explanation-source label."""
    return f"Groq ({model})"
