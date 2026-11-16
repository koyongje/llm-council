import pytest
from fastapi.testclient import TestClient

from backend import council, main, model_catalog, settings
from backend.config import COUNCIL_MODELS, CHAIRMAN_MODEL, TITLE_MODEL

GOOD = ["openai/gpt-5.1", "anthropic/claude-opus-5-5"]


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_PATH", str(path))
    return path


def test_defaults_come_from_config():
    assert settings.get_council() == (COUNCIL_MODELS, CHAIRMAN_MODEL)


def test_saved_council_is_returned():
    settings.set_council(GOOD, "google/gemini-3.1-pro-preview")
    assert settings.get_council() == (GOOD, "google/gemini-3.1-pro-preview")


def test_corrupt_file_falls_back_to_defaults(settings_file):
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text("{not json", encoding="utf-8")
    assert settings.get_council() == (COUNCIL_MODELS, CHAIRMAN_MODEL)


@pytest.mark.parametrize("members,chairman", [
    (["openai/gpt-5.1"], "openai/gpt-5.1"),                         # too few
    ([f"openai/m{i}" for i in range(7)], "openai/gpt-5.1"),         # too many
    (["openai/gpt-5.1", "openai/gpt-5.1"], "openai/gpt-5.1"),       # duplicate
    (["openai/gpt-5.1", "mistral/large"], "openai/gpt-5.1"),        # unknown provider
    (["openai/gpt-5.1", "gpt-5.1"], "openai/gpt-5.1"),              # no provider prefix
    (GOOD, "openai/"),                                              # empty model id
])
def test_invalid_council_is_rejected(members, chairman):
    with pytest.raises(ValueError):
        settings.set_council(members, chairman)
    assert settings.get_council() == (COUNCIL_MODELS, CHAIRMAN_MODEL)


async def test_stages_use_saved_council(monkeypatch):
    settings.set_council(GOOD, "google/gemini-3.1-pro-preview")
    seen = {}

    async def parallel(models, messages, **kw):
        seen["council"] = models
        return {}

    async def single(model, messages, **kw):
        seen["chairman"] = model
        return {"content": "x"}

    monkeypatch.setattr(council, "query_models_parallel", parallel)
    monkeypatch.setattr(council, "query_model", single)
    await council.stage1_collect_responses("q")
    assert seen["council"] == GOOD
    result = await council.stage3_synthesize_final("q", [], [])
    assert seen["chairman"] == "google/gemini-3.1-pro-preview"
    assert result["model"] == "google/gemini-3.1-pro-preview"


# --- model catalog -----------------------------------------------------------

OPENAI_LIST = {"data": [{"id": i} for i in [
    "gpt-5.1", "o3", "chatgpt-4o-latest", "gpt-4o-audio-preview", "gpt-realtime",
    "text-embedding-3-large", "gpt-image-1", "gpt-live-1", "dall-e-3", "gpt-4o-search-preview", "omni-moderation-latest",
]]}
ANTHROPIC_LIST = {"data": [{"id": "claude-opus-5-5"}, {"id": "claude-haiku-5-5"}]}
GEMINI_LIST = {"models": [
    {"name": "models/gemini-3.1-pro-preview", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
    {"name": "models/gemini-3.8-flash-tts", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/imagen-4", "supportedGenerationMethods": ["predict"]},
    {"name": "models/gemini-3.5-transcribe", "supportedGenerationMethods": ["generateContent"]},
    {"name": "models/gemini-robotics-er-2-preview", "supportedGenerationMethods": ["generateContent"]},
]}


@pytest.fixture
def fake_get(monkeypatch):
    replies = {"openai": OPENAI_LIST, "anthropic": ANTHROPIC_LIST, "google": GEMINI_LIST}

    async def _get(url, headers, params=None):
        for provider, reply in replies.items():
            if provider in url or (provider == "google" and "googleapis" in url):
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise AssertionError(url)

    monkeypatch.setattr(model_catalog, "_get", _get)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(model_catalog, name, "k")
    return replies


async def test_catalog_keeps_only_chat_models(fake_get):
    catalog = await model_catalog.list_models()
    assert catalog["openai"] == {"models": ["openai/chatgpt-4o-latest", "openai/gpt-5.1", "openai/o3"], "error": None}
    assert catalog["anthropic"] == {"models": ["anthropic/claude-haiku-5-5", "anthropic/claude-opus-5-5"], "error": None}
    assert catalog["google"] == {"models": ["google/gemini-3.1-pro-preview"], "error": None}


async def test_catalog_reports_missing_key_and_failures(fake_get, monkeypatch):
    monkeypatch.setattr(model_catalog, "OPENAI_API_KEY", None)
    fake_get["anthropic"] = RuntimeError("HTTP 401: invalid x-api-key")
    catalog = await model_catalog.list_models()
    assert catalog["openai"]["models"] == [] and "OPENAI_API_KEY" in catalog["openai"]["error"]
    assert catalog["anthropic"]["models"] == [] and "401" in catalog["anthropic"]["error"]
    assert catalog["google"]["error"] is None


# --- endpoints ---------------------------------------------------------------

def test_settings_endpoints_roundtrip():
    client = TestClient(main.app)
    body = client.get("/api/settings").json()
    assert body == {"council_models": COUNCIL_MODELS, "chairman_model": CHAIRMAN_MODEL, "title_model": TITLE_MODEL}

    r = client.put("/api/settings", json={"council_models": GOOD, "chairman_model": "openai/gpt-5.1"})
    assert r.status_code == 200 and r.json()["council_models"] == GOOD

    bad = client.put("/api/settings", json={"council_models": ["openai/gpt-5.1"], "chairman_model": "openai/gpt-5.1"})
    assert bad.status_code == 400 and bad.json()["detail"]
    assert client.get("/api/settings").json()["council_models"] == GOOD

    engines = [e["model"] for e in client.get("/api/engines").json()]
    assert engines == [*GOOD, TITLE_MODEL]


def test_models_endpoint(fake_get):
    body = TestClient(main.app).get("/api/models").json()
    assert set(body) == {"openai", "anthropic", "google"}


def test_settings_test_endpoint_pings_each_model(monkeypatch):
    async def parallel(models, messages, **kw):
        return {"openai/gpt-5.1": {"content": "OK"}, "anthropic/claude-opus-5-5": None}

    monkeypatch.setattr(main, "query_models_parallel", parallel)
    monkeypatch.setattr(main.engine_status, "get", lambda m: {"status": "credit", "message": "no credits", "at": "t"})
    body = TestClient(main.app).post("/api/settings/test", json={"models": GOOD}).json()
    assert body[0] == {"model": "openai/gpt-5.1", "ok": True, "status": "ok", "message": None}
    assert body[1] == {"model": "anthropic/claude-opus-5-5", "ok": False, "status": "credit", "message": "no credits"}
