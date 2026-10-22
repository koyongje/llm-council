import pytest

from backend import providers


class FakePost:
    def __init__(self):
        self.calls = []
        self.reply = None
        self.replies = None

    async def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, payload))
        if self.replies is not None:
            return self.replies.pop(0)
        return self.reply


@pytest.fixture
def fake_post(monkeypatch):
    fake = FakePost()
    monkeypatch.setattr(providers, "_post", fake)
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(providers, name, "k")
    return fake
