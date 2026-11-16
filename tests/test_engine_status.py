import pytest
from fastapi.testclient import TestClient

from backend import engine_status, main, providers
from backend.providers import query_model

MSG = [{"role": "user", "content": "q"}]


@pytest.fixture(autouse=True)
def clean_status():
    engine_status.reset()
    yield
    engine_status.reset()


def failing_post(text):
    async def _post(url, headers, payload, timeout):
        raise RuntimeError(text)
    return _post


@pytest.mark.parametrize("text,expected", [
    ('HTTP 429: {"error": {"message": "You have no credits remaining.", "code": "insufficient_quota"}}', "credit"),
    ('HTTP 400: {"error": {"message": "Your credit balance is too low to access the Anthropic API."}}', "credit"),
    ('HTTP 429: {"error": {"message": "Your prepayment credits are depleted."}}', "credit"),
    ('HTTP 429: {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}}', "rate_limit"),
    ("HTTP 500: internal error", "error"),
])
async def test_failure_is_classified(fake_post, monkeypatch, text, expected):
    monkeypatch.setattr(providers, "_post", failing_post(text))
    assert await query_model("openai/gpt-5.1", MSG) is None
    entry = engine_status.get("openai/gpt-5.1")
    assert entry["status"] == expected
    assert entry["message"] == text[:200] and entry["at"]


async def test_success_clears_failure(fake_post, monkeypatch):
    monkeypatch.setattr(providers, "_post", failing_post("HTTP 429: no credits remaining"))
    await query_model("openai/gpt-5.1", MSG)
    monkeypatch.setattr(providers, "_post", fake_post)
    fake_post.reply = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}]}
    assert await query_model("openai/gpt-5.1", MSG) is not None
    entry = engine_status.get("openai/gpt-5.1")
    assert entry["status"] == "ok" and entry["message"] is None


async def test_empty_response_is_recorded_as_error(fake_post):
    fake_post.reply = {"candidates": [{"content": {"parts": [{"text": " "}]}}]}
    await query_model("google/gemini-3.1-pro-preview", MSG)
    assert engine_status.get("google/gemini-3.1-pro-preview")["status"] == "error"


def test_long_message_is_truncated():
    engine_status.record_failure("m", "x" * 500)
    assert len(engine_status.get("m")["message"]) == 200


def test_engines_endpoint_lists_configured_models_once_in_order(monkeypatch):
    monkeypatch.setattr(main, "COUNCIL_MODELS", ["a/1", "b/2"])
    monkeypatch.setattr(main, "CHAIRMAN_MODEL", "b/2")
    monkeypatch.setattr(main, "TITLE_MODEL", "c/3")
    engine_status.record_failure("a/1", "HTTP 429: insufficient_quota")
    body = TestClient(main.app).get("/api/engines").json()
    assert [e["model"] for e in body] == ["a/1", "b/2", "c/3"]
    assert body[0]["status"] == "credit"
    assert body[1] == {"model": "b/2", "status": "unknown", "message": None, "at": None}
