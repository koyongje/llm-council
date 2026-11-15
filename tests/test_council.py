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

    async def parallel(models, messages, files=None, web_search=False, timeout=300.0):
        fake.parallel_calls.append({"messages": messages, "files": files, "web_search": web_search, "timeout": timeout})
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
    assert call["timeout"] == 600.0
    assert call["messages"][:2] == [{"role": "user", "content": "h"}, {"role": "assistant", "content": "ha"}]
    assert "출처 미확인" in call["messages"][-1]["content"]
    assert out[0]["body"] == "ans"
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


async def test_stage3_chairman_sees_sources_block(fake_council):
    s1 = [{"model": "m", "body": "b", "response": "b\n\n출처:\n- [A](https://a.com)", "sources": [{"url": "https://a.com", "title": "A"}]}]
    await stage3_synthesize_final("q", s1, S2)
    prompt = fake_council.single_calls[-1]["messages"][-1]["content"]
    assert "출처:" in prompt and "https://a.com" in prompt


async def test_stage3_retries_without_files_when_chairman_fails_with_files(monkeypatch):
    calls = []

    async def single(model, messages, timeout=300.0, files=None, web_search=False):
        calls.append(files)
        return None if files else {"content": "see [x](https://fake.com)", "sources": []}

    monkeypatch.setattr(council, "query_model", single)
    r = await stage3_synthesize_final("q", S1, S2, files=[PDF], verified_urls=set())
    assert calls == [[PDF], []]
    assert r["response"] == "see [x](https://fake.com) ⚠️ 미검증"


async def test_stage3_error_response_when_both_attempts_fail(monkeypatch):
    calls = []

    async def single(model, messages, timeout=300.0, files=None, web_search=False):
        calls.append(files)
        return None

    monkeypatch.setattr(council, "query_model", single)
    r = await stage3_synthesize_final("q", S1, S2, files=[PDF])
    assert len(calls) == 2
    assert r["response"] == council.CHAIRMAN_ERROR_RESPONSE


async def test_stage3_no_retry_without_files(monkeypatch):
    calls = []

    async def single(model, messages, timeout=300.0, files=None, web_search=False):
        calls.append(files)
        return None

    monkeypatch.setattr(council, "query_model", single)
    await stage3_synthesize_final("q", S1, S2)
    assert len(calls) == 1


def test_sse_payload_keeps_korean_unescaped():
    from backend.main import _sse
    out = _sse({"type": "x", "data": "한글"})
    assert "한글" in out and out.endswith("\n\n")


def test_parse_ranking_fallback_dedupes_repeated_labels():
    text = "Response A is good. Response B is weaker than Response A."
    assert council.parse_ranking_from_text(text) == ["Response A", "Response B"]


def test_aggregate_counts_each_label_once_per_evaluator():
    stage2 = [{"model": "m", "ranking": "Response A beats Response B; Response A wins.",
               "parsed_ranking": ["Response A", "Response B"]}]
    agg = council.calculate_aggregate_rankings(stage2, {"Response A": "x/a", "Response B": "x/b"})
    assert agg == [
        {"model": "x/a", "average_rank": 1.0, "rankings_count": 1},
        {"model": "x/b", "average_rank": 2.0, "rankings_count": 1},
    ]


def test_sse_failure_mid_council_saves_nothing(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    import backend.main as main
    from backend import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "UPLOADS_DIR", str(tmp_path / "up"))

    async def ok_stage1(*a, **k):
        return [{"model": "x/a", "body": "b", "response": "b", "sources": []}]

    async def boom(*a, **k):
        raise RuntimeError("stage 2 exploded")

    async def title(q):
        return "T"

    monkeypatch.setattr(main, "stage1_collect_responses", ok_stage1)
    monkeypatch.setattr(main, "stage2_collect_rankings", boom)
    monkeypatch.setattr(main, "generate_conversation_title", title)
    client = TestClient(main.app)
    cid = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/message/stream", json={"content": "hi"})
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    assert events[-1] == {"type": "error", "message": "stage 2 exploded"}
    # The client drops the optimistic messages on error; the server must agree
    assert storage.get_conversation(cid)["messages"] == []


def test_aggregate_excludes_self_votes_and_reranks_the_rest():
    labels = {"Response A": "x/a", "Response B": "x/b", "Response C": "x/c"}
    stage2 = [
        # Each evaluator puts itself first; that vote is dropped and the
        # remaining labels are renumbered from 1
        {"model": "x/a", "ranking": "", "parsed_ranking": ["Response A", "Response B", "Response C"]},
        {"model": "x/b", "ranking": "", "parsed_ranking": ["Response B", "Response A", "Response C"]},
        {"model": "x/c", "ranking": "", "parsed_ranking": ["Response C", "Response B", "Response A"]},
    ]
    agg = council.calculate_aggregate_rankings(stage2, labels)
    # a: b→1, c→2 = 1.5 ; b: a→1, c→1 = 1.0 ; c: a→2, b→2 = 2.0
    assert agg == [
        {"model": "x/b", "average_rank": 1.0, "rankings_count": 2},
        {"model": "x/a", "average_rank": 1.5, "rankings_count": 2},
        {"model": "x/c", "average_rank": 2.0, "rankings_count": 2},
    ]


def test_sse_sends_keepalive_comments_while_a_stage_runs(tmp_path, monkeypatch):
    import asyncio
    from fastapi.testclient import TestClient
    import backend.main as main
    from backend import storage
    monkeypatch.setattr(storage, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "UPLOADS_DIR", str(tmp_path / "up"))
    monkeypatch.setattr(main, "HEARTBEAT_SECONDS", 0.01)

    async def slow_empty_stage1(*a, **k):
        await asyncio.sleep(0.1)
        return []

    async def title(q):
        return "T"

    monkeypatch.setattr(main, "stage1_collect_responses", slow_empty_stage1)
    monkeypatch.setattr(main, "generate_conversation_title", title)
    client = TestClient(main.app)
    cid = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/message/stream", json={"content": "hi"})
    # SSE comment lines keep the connection visibly alive; data events are unchanged
    assert ": keepalive" in r.text
    assert r.text.index(": keepalive") < r.text.index('"stage1_complete"')
