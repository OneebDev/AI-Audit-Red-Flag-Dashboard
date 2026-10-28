"""Tests for the Groq client, key rotation, grounding, and safe fallbacks."""

from __future__ import annotations

import json

import pandas as pd
import pytest
import requests

import groq_client
from groq_client import (
    CHAT_URL,
    DEFAULT_MODEL,
    MODEL_CATALOG,
    SYSTEM_PROMPT,
    GroqClient,
    env_keys,
    explain_entry,
    facts_from_row,
    fallback_models,
    is_grounded,
    masked,
    normalize_keys,
    source_label,
)

KEY_ONE = "gsk_firstKey1234567890"
KEY_TWO = "gsk_secondKey0987654321"


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self) -> dict[str, object]:
        return self._body


def _chat_body(text: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": text}}]}


def _models_body(*model_ids: str) -> dict[str, object]:
    return {"data": [{"id": model_id} for model_id in model_ids]}


def test_normalize_keys_accepts_strings_and_sequences() -> None:
    assert normalize_keys(" a, b\nc ") == ["a", "b", "c"]
    assert normalize_keys(["a", "a", "b"]) == ["a", "b"]
    assert normalize_keys('"quoted-key"') == ["quoted-key"]
    assert normalize_keys(None) == []
    assert normalize_keys("") == []


def test_env_keys_reads_both_variable_names(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEYS", raising=False)
    monkeypatch.delenv("GROQ_KEYS", raising=False)
    assert env_keys() == []

    monkeypatch.setenv("GROQ_KEYS", "key-a,key-b")
    assert env_keys() == ["key-a", "key-b"]

    monkeypatch.setenv("GROQ_API_KEYS", "key-c")
    assert env_keys() == ["key-c"]


def test_masked_never_reveals_the_middle() -> None:
    assert masked(KEY_ONE) == f"{KEY_ONE[:4]}...{KEY_ONE[-4:]}"
    assert masked("short") == "gsk_...****"
    assert KEY_ONE[10:20] not in masked(KEY_ONE)


def test_facts_from_row_contains_only_structured_fields(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[checked_demo["duplicate_invoice"].notna()].iloc[0]

    facts = facts_from_row(row)
    serialized = json.dumps(facts, default=str)

    assert facts["EntryID"] == row["EntryID"]
    assert facts["Date"] == row["Date"].strftime("%m/%d/%Y")
    assert facts["Vendor"] == row["Vendor"]
    assert facts["Amount"].startswith("Rs. ")
    assert facts["AmountValue"] == pytest.approx(round(float(row["Amount"]), 2))
    assert facts["ApprovalLimit"] == "Rs. 5,00,000"
    assert facts["ShareOfLimit"] == pytest.approx(
        round(float(row["Amount"]) / 500_000.0 * 100.0, 2)
    )
    assert facts["InvoiceReference"] == row["duplicate_invoice"]
    assert facts["DuplicateGapDays"] == int(row["duplicate_gap_days"])
    assert "GroundTruth" not in serialized
    assert "ApprovedBy" in facts


def test_is_grounded_accepts_facts_and_rejects_invented_numbers(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[checked_demo["flag_duplicate"]].iloc[0]
    facts = facts_from_row(row)

    assert is_grounded(
        f"{row['EntryID']} repeats a {facts['Amount']} posting on {facts['Date']}.",
        facts,
    )
    assert is_grounded("This is a 3 sentence summary.", facts)
    assert not is_grounded("The payment was actually Rs. 999,999.99.", facts)
    assert not is_grounded("The vendor sent 42 invoices.", facts)


def test_chat_returns_content_and_sends_safe_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, headers, json, timeout):
        captured.update(
            {"url": url, "headers": headers, "json": json, "timeout": timeout}
        )
        return FakeResponse(200, _chat_body("Grounded explanation."))

    monkeypatch.setattr(groq_client.requests, "post", fake_post)
    client = GroqClient([KEY_ONE])

    text = client.chat([{"role": "user", "content": "FACTS: {}"}])

    assert text == "Grounded explanation."
    assert captured["url"] == CHAT_URL
    assert captured["headers"]["Authorization"] == f"Bearer {KEY_ONE}"
    assert captured["timeout"] == 20
    payload = captured["json"]
    assert payload["model"] == DEFAULT_MODEL
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 220
    assert KEY_ONE not in json.dumps(payload)


def test_chat_rotates_to_the_next_key_after_429(monkeypatch) -> None:
    seen: list[str] = []

    def fake_post(url, headers, json, timeout):
        seen.append(headers["Authorization"])
        if len(seen) == 1:
            return FakeResponse(429, {}, {"Retry-After": "0"})
        return FakeResponse(200, _chat_body("Second key worked."))

    monkeypatch.setattr(groq_client.requests, "post", fake_post)

    text = GroqClient([KEY_ONE, KEY_TWO]).chat([{"role": "user", "content": "hi"}])

    assert text == "Second key worked."
    assert seen == [f"Bearer {KEY_ONE}", f"Bearer {KEY_TWO}"]


def test_chat_rotates_after_network_errors(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_post(url, headers, json, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.ConnectionError("network down")
        return FakeResponse(200, _chat_body("Recovered."))

    monkeypatch.setattr(groq_client.requests, "post", fake_post)

    assert GroqClient([KEY_ONE, KEY_TWO]).chat([{"role": "user", "content": "hi"}]) == "Recovered."


def test_chat_returns_none_when_every_key_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        groq_client.requests,
        "post",
        lambda url, headers, json, timeout: FakeResponse(429),
    )

    assert GroqClient([KEY_ONE, KEY_TWO]).chat([{"role": "user", "content": "hi"}]) is None


def test_chat_without_keys_does_not_call_the_network(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("network must not be used without a key")

    monkeypatch.setattr(groq_client.requests, "post", unexpected)

    assert GroqClient([]).chat([{"role": "user", "content": "hi"}]) is None


def test_test_key_statuses(monkeypatch) -> None:
    statuses = iter(
        [
            FakeResponse(200),
            FakeResponse(401),
            FakeResponse(403),
            FakeResponse(429),
            FakeResponse(500),
        ]
    )
    monkeypatch.setattr(groq_client.requests, "get", lambda *args, **kwargs: next(statuses))
    client = GroqClient([KEY_ONE])

    assert client.test_key(KEY_ONE) == "valid"
    assert client.test_key(KEY_ONE) == "invalid"
    assert client.test_key(KEY_ONE) == "invalid"
    assert client.test_key(KEY_ONE) == "rate-limited"
    assert client.test_key(KEY_ONE) == "error"


def test_test_key_network_error_is_safe(monkeypatch) -> None:
    def failing(*args, **kwargs):
        raise requests.Timeout(f"timed out for {KEY_ONE}")

    monkeypatch.setattr(groq_client.requests, "get", failing)

    status = GroqClient([KEY_ONE]).test_key(KEY_ONE)

    assert status == "error"
    assert KEY_ONE not in status


def test_list_models_filters_non_chat_models(monkeypatch) -> None:
    body = _models_body(
        "llama-3.3-70b-versatile",
        "whisper-large-v3",
        "tts-1",
        "llama-guard-4-12b",
        "nomic-embed-text",
        "llama-3.1-8b-instant",
    )
    monkeypatch.setattr(
        groq_client.requests, "get", lambda *args, **kwargs: FakeResponse(200, body)
    )

    models = GroqClient([KEY_ONE]).list_models()

    assert models == ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]
    assert fallback_models() == [model for model, _ in MODEL_CATALOG]


def test_list_models_returns_empty_without_keys(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("network must not be used without a key")

    monkeypatch.setattr(groq_client.requests, "get", unexpected)

    assert GroqClient([]).list_models() == []


def test_explain_entry_sends_only_facts_and_returns_grounded_text(
    checked_demo: pd.DataFrame, monkeypatch
) -> None:
    row = checked_demo[checked_demo["flag_duplicate"]].iloc[0]
    captured: dict[str, object] = {}

    def fake_post(url, headers, json, timeout):
        captured.update({"json": json, "headers": headers})
        body = _chat_body(
            f"{row['EntryID']} repeats a payment on {row['Date'].strftime('%m/%d/%Y')}."
        )
        return FakeResponse(200, body)

    monkeypatch.setattr(groq_client.requests, "post", fake_post)

    text = explain_entry(row, [KEY_ONE], model="llama-3.1-8b-instant")

    assert text == f"{row['EntryID']} repeats a payment on {row['Date'].strftime('%m/%d/%Y')}."
    payload = captured["json"]
    system = payload["messages"][0]
    user = payload["messages"][1]
    assert system["content"] == SYSTEM_PROMPT
    assert "Use only these facts" in system["content"]
    assert "do not invent amounts, names or dates" in system["content"]
    assert "3 sentences max" in system["content"]
    assert str(row["EntryID"]) in user["content"]
    assert "GroundTruth" not in user["content"]
    assert KEY_ONE not in json.dumps(payload)
    assert payload["model"] == "llama-3.1-8b-instant"
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 220


def test_explain_entry_discards_invented_numbers(
    checked_demo: pd.DataFrame, monkeypatch
) -> None:
    row = checked_demo[checked_demo["flag_duplicate"]].iloc[0]

    monkeypatch.setattr(
        groq_client.requests,
        "post",
        lambda url, headers, json, timeout: FakeResponse(
            200, _chat_body("The payment was Rs. 987,654.32, much higher than recorded.")
        ),
    )

    assert explain_entry(row, [KEY_ONE]) is None


def test_explain_entry_falls_back_on_failures(
    checked_demo: pd.DataFrame, monkeypatch
) -> None:
    row = checked_demo[checked_demo["flag_duplicate"]].iloc[0]

    monkeypatch.setattr(
        groq_client.requests,
        "post",
        lambda url, headers, json, timeout: FakeResponse(429),
    )
    assert explain_entry(row, [KEY_ONE, KEY_TWO]) is None

    monkeypatch.setattr(
        groq_client.requests,
        "post",
        lambda url, headers, json, timeout: FakeResponse(200, _chat_body("")),
    )
    assert explain_entry(row, [KEY_ONE]) is None

    def failing(url, headers, json, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(groq_client.requests, "post", failing)
    assert explain_entry(row, [KEY_ONE]) is None


def test_explain_entry_requires_a_key(checked_demo: pd.DataFrame, monkeypatch) -> None:
    row = checked_demo[checked_demo["flag_duplicate"]].iloc[0]

    def unexpected(*args, **kwargs):
        raise AssertionError("network must not be used without a key")

    monkeypatch.setattr(groq_client.requests, "post", unexpected)

    assert explain_entry(row, []) is None
    assert explain_entry(row, "") is None


def test_roman_urdu_uses_its_own_system_prompt(
    checked_demo: pd.DataFrame, monkeypatch
) -> None:
    row = checked_demo[checked_demo["flag_duplicate"]].iloc[0]
    captured: dict[str, object] = {}

    def fake_post(url, headers, json, timeout):
        captured["json"] = json
        return FakeResponse(200, _chat_body(f"{row['EntryID']} duplicate posting."))

    monkeypatch.setattr(groq_client.requests, "post", fake_post)

    explain_entry(row, [KEY_ONE], language="Roman Urdu")

    assert (
        captured["json"]["messages"][0]["content"]
        == groq_client.SYSTEM_PROMPT_ROMAN_URDU
    )
    assert "Roman Urdu" in captured["json"]["messages"][0]["content"]


def test_keys_never_appear_in_logs_or_exception_text(
    checked_demo: pd.DataFrame, monkeypatch, caplog
) -> None:
    row = checked_demo[checked_demo["flag_duplicate"]].iloc[0]

    def failing(url, headers, json, timeout):
        raise requests.ConnectionError(f"connection dropped for {headers['Authorization']}")

    monkeypatch.setattr(groq_client.requests, "post", failing)

    with caplog.at_level("DEBUG"):
        assert explain_entry(row, [KEY_ONE]) is None

    assert KEY_ONE not in caplog.text
    assert KEY_ONE not in json.dumps(facts_from_row(row), default=str)


def test_source_label_names_the_model() -> None:
    assert source_label("llama-3.3-70b-versatile") == "Groq (llama-3.3-70b-versatile)"
    assert source_label(DEFAULT_MODEL).startswith("Groq (")
