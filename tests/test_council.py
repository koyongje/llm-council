import pytest

from backend import council
from backend.council import (
    build_history,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
)
from backend.providers import PdfFile

PDF = PdfFile("a.pdf", b"%PDF-1")
S1 = [{"model": "m", "response": "r1", "sources": []}]
S2 = [{"model": "m", "ranking": "FINAL RANKING:\n1. Response A", "parsed_ranking": ["Response A"]}]


class FakeCouncil:
    def __init__(self):
        self.parallel_reply = {"m": {"content": "x", "sources": []}}
        self.single_reply = {"content": "y", "sources": []}
        self.parallel_calls = []
        self.single_calls = []


@pytest.fixture
def fake_council(monkeypatch):
    fake = FakeCouncil()

    async def parallel(models, messages, files=None, web_search=False):
        fake.parallel_calls.append({"messages": messages, "files": files, "web_search": web_search})
        return fake.parallel_reply

    async def single(model, messages, timeout=300.0, files=None, web_search=False):
        fake.single_calls.append({"messages": messages, "files": files, "web_search": web_search})
        return fake.single_reply

    monkeypatch.setattr(council, "query_models_parallel", parallel)
    monkeypatch.setattr(council, "query_model", single)
    return fake


def test_build_history_pairs_and_skips_failures():
    prior = [{"role": "user", "content": "q1"}, {"role": "assistant", "stage3": {"model": "m", "response": "a1"}},
             {"role": "user", "content": "q2"}, {"role": "assistant", "stage3": {"model": "m", "response": "Error: Unable to generate final synthesis."}},
             {"role": "user", "content": "q3"}]
    assert build_history(prior) == [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]


async def test_stage1_uses_web_search_files_history_and_appends_sources(fake_council):
    fake_council.parallel_reply = {"m": {"content": "ans", "sources": [{"url": "https://a.com", "title": "A"}]}}
    out = await stage1_collect_responses("q", history=[{"role": "user", "content": "h"}, {"role": "assistant", "content": "ha"}], files=[PDF])
    call = fake_council.parallel_calls[0]
    assert call["web_search"] is True and call["files"] == [PDF]
    assert call["messages"][:2] == [{"role": "user", "content": "h"}, {"role": "assistant", "content": "ha"}]
    assert "출처 미확인" in call["messages"][-1]["content"]
    assert out[0]["response"] == "ans\n\n출처:\n- [A](https://a.com)" and out[0]["sources"] == [{"url": "https://a.com", "title": "A"}]


async def test_stage2_has_files_but_no_web_search(fake_council):
    fake_council.parallel_reply = {"m": {"content": "FINAL RANKING:\n1. Response A"}}
    history = [{"role": "user", "content": "h"}, {"role": "assistant", "content": "ha"}]
    results, label_to_model = await stage2_collect_rankings("q", S1, history=history, files=[PDF])
    call = fake_council.parallel_calls[0]
    assert call["web_search"] is False and call["files"] == [PDF]
    assert call["messages"][:2] == history
    assert results[0]["parsed_ranking"] == ["Response A"]
    assert label_to_model == {"Response A": "m"}


async def test_stage3_table_only_with_files_and_marks_unverified(fake_council):
    fake_council.single_reply = {"content": "see [x](https://fake.com)", "sources": []}
    with_files = await stage3_synthesize_final("q", S1, S2, files=[PDF], verified_urls={"https://a.com"})
    assert "기획서 위치" in fake_council.single_calls[-1]["messages"][-1]["content"]
    assert with_files["response"] == "see [x](https://fake.com) ⚠️ 미검증"
    await stage3_synthesize_final("q", S1, S2)
    assert "기획서 위치" not in fake_council.single_calls[-1]["messages"][-1]["content"]
    assert fake_council.single_calls[-1]["web_search"] is False
    assert "never invent new URLs" in fake_council.single_calls[-1]["messages"][-1]["content"]


async def test_stage2_prompt_hides_sources_block(fake_council):
    s1 = [{"model": "m", "body": "plain body", "response": "plain body\n\n출처:\n- [A](https://a.com)", "sources": []}]
    await stage2_collect_rankings("q", s1)
    prompt = fake_council.parallel_calls[0]["messages"][-1]["content"]
    assert "plain body" in prompt and "출처:" not in prompt


def test_build_history_skips_all_failed_turn():
    prior = [{"role": "user", "content": "q"}, {"role": "assistant", "stage3": {"model": "error", "response": council.ALL_FAILED_RESPONSE}}]
    assert build_history(prior) == []


def test_sse_all_stage1_failed_skips_later_stages(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    import backend.main as main
    from backend import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "UPLOADS_DIR", str(tmp_path / "up"))

    async def empty_stage1(*a, **k):
        return []

    async def boom(*a, **k):
        raise AssertionError("must not be called")

    async def title(q):
        return "T"

    monkeypatch.setattr(main, "stage1_collect_responses", empty_stage1)
    monkeypatch.setattr(main, "stage2_collect_rankings", boom)
    monkeypatch.setattr(main, "stage3_synthesize_final", boom)
    monkeypatch.setattr(main, "generate_conversation_title", title)
    client = TestClient(main.app)
    cid = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/message/stream", json={"content": "hi"})
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    types = [e["type"] for e in events]
    assert types == ["stage1_start", "stage1_complete", "stage3_complete", "title_complete", "complete"]
    assert events[2]["data"] == {"model": "error", "response": council.ALL_FAILED_RESPONSE}
    last = storage.get_conversation(cid)["messages"][-1]
    assert last["stage1"] == [] and last["stage3"]["model"] == "error"
