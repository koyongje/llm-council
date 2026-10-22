# 참고파일(PDF) + 웹 검색 검토 기능 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users attach PDFs to a conversation so every council turn reads them, searches the web for current data, keeps conversation history, and returns a sourced revision-proposal table.

**Architecture:** `providers.py` gains PDF input, web search and source extraction for each vendor (raw httpx, no SDKs). A new pure-function module `citations.py` formats source lists and flags unverified links. `council.py` threads history, files and web search through the three stages. `storage.py` + a multipart endpoint persist PDFs per conversation. The React UI gains an attach button, a file list, a follow-up input, and GFM table rendering.

**Tech Stack:** FastAPI, httpx, pytest + pytest-asyncio (new dev deps), python-multipart (new dep), React 19 + react-markdown + remark-gfm (new dep).

**Spec:** `docs/superpowers/specs/2026-10-22-reference-files-design.md`

## Global Constraints

- Keep raw httpx calls in `backend/providers.py`; do not add vendor SDKs.
- PDF only; **total attached PDF size per conversation ≤ 14 MB** (`14 * 1024 * 1024` bytes), checked at upload; inline base64 on every request; no provider Files APIs.
- Web search is on for **Stage 1 only**, for every question (files or not). Stage 2, Stage 3 and title generation never search.
- PDFs go to Stage 1, Stage 2 and Stage 3; never to title generation.
- History = prior `(user content, stage3 response)` pairs only; never Stage 1/2 texts.
- Revision table (5 columns: `#`, `기획서 위치`, `현재 내용`, `수정 제안 (최신 데이터)`, `근거·출처`) only when the conversation has files.
- Unverified links in the Stage 3 answer get ` ⚠️ 미검증` appended; never deleted.
- If a provider call fails (including web search tool errors), drop that member; no retry without search.
- Keep the backend on port 8001; run as `uv run python -m backend.main`.

## Review Focus

1. Conversations saved before this change have no `files` key → must still load, list, and accept messages (test in Task 3).
2. A prior turn whose Stage 3 is the `"Error: Unable to generate final synthesis."` fallback or whose `stage3` is missing → excluded from history (test in Task 4).
3. Anthropic web search returns an error object (`content` is a dict, not a list) or `stop_reason: "pause_turn"` → no crash; pause is resumed (tests in Task 2).
4. A non-PDF renamed to `.pdf`, or an upload pushing the total past 14 MB → HTTP 400 with a readable reason and nothing written to disk (tests in Task 3).
5. The chairman writes a verified URL with a trailing slash, inside a markdown link, or bare → not flagged; an invented URL → flagged once, not twice on re-run (tests in Task 1).

---

### Task 1: Test setup and `citations.py`

**Files:**
- Modify: `pyproject.toml` (via `uv add --dev pytest pytest-asyncio`)
- Create: `backend/citations.py`
- Create: `tests/__init__.py` (empty), `tests/test_citations.py`
- Create: `pytest.ini` with `[pytest]` / `asyncio_mode = auto` / `testpaths = tests`

**Interfaces:**
- Produces (all in `backend/citations.py`):
  - `Source = Dict[str, str]` with keys `url`, `title`
  - `format_sources(sources: List[Source]) -> str`: a block beginning `"\n\n출처:\n"` and one line `- [title](url)` per unique URL (title falls back to the URL); if `sources` is empty, returns `"\n\n출처: 웹 검색 출처 없음"`.
  - `normalize_url(url: str) -> str`: lowercases scheme and host, strips a trailing `/` and trailing `.,;)` punctuation.
  - `collect_verified_urls(prior_messages: List[Dict], stage1_results: List[Dict]) -> Set[str]`: normalized URLs from every `stage1[*].sources` in prior assistant messages plus `stage1_results[*].sources`. A missing `sources` key counts as empty.
  - `mark_unverified(text: str, verified: Set[str]) -> str`: appends ` ⚠️ 미검증` after every markdown link `[..](url)` or bare `http(s)://` URL whose normalized form is not in `verified`. Idempotent: a link already followed by `⚠️ 미검증` is left alone.

- [ ] **Step 1: Add dev dependencies and pytest config**

Run: `uv add --dev pytest pytest-asyncio`, then create `pytest.ini` and `tests/__init__.py`.

- [ ] **Step 2: Write the failing tests in `tests/test_citations.py`**

```python
from backend.citations import format_sources, normalize_url, collect_verified_urls, mark_unverified

def test_format_sources_lists_unique_links():
    out = format_sources([{"url": "https://a.com/x", "title": "A"}, {"url": "https://a.com/x", "title": "A"}, {"url": "https://b.com", "title": ""}])
    assert out == "\n\n출처:\n- [A](https://a.com/x)\n- [https://b.com](https://b.com)"

def test_format_sources_empty():
    assert format_sources([]) == "\n\n출처: 웹 검색 출처 없음"

def test_normalize_url():
    assert normalize_url("HTTPS://Example.com/path/") == "https://example.com/path"
    assert normalize_url("https://example.com/a).") == "https://example.com/a"

def test_collect_verified_urls_merges_prior_and_current():
    prior = [{"role": "user", "content": "q"},
             {"role": "assistant", "stage1": [{"model": "m", "response": "r", "sources": [{"url": "https://old.com/", "title": ""}]}]},
             {"role": "assistant", "stage1": [{"model": "m", "response": "r"}]}]
    current = [{"model": "m", "response": "r", "sources": [{"url": "https://new.com", "title": ""}]}]
    assert collect_verified_urls(prior, current) == {"https://old.com", "https://new.com"}

def test_mark_unverified_flags_only_unknown_links():
    text = "See [ok](https://ok.com/) and [bad](https://bad.com) and https://ok.com and https://fake.org/x."
    out = mark_unverified(text, {"https://ok.com"})
    assert out == "See [ok](https://ok.com/) and [bad](https://bad.com) ⚠️ 미검증 and https://ok.com and https://fake.org/x ⚠️ 미검증."

def test_mark_unverified_is_idempotent():
    once = mark_unverified("[bad](https://bad.com)", set())
    assert mark_unverified(once, set()) == once
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_citations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.citations'`

- [ ] **Step 4: Implement `backend/citations.py` with the five interfaces above**

Use one regex that matches either a markdown link `\[[^\]]*\]\((https?://[^)\s]+)\)` or a bare `https?://[^\s)\]]+`, and process matches in a single `re.sub` pass so a URL inside a markdown link is not matched twice. Strip the trailing `.,;` punctuation of a bare URL from the match before comparing, and keep that punctuation after the marker.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_citations.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock pytest.ini tests/__init__.py tests/test_citations.py backend/citations.py
git commit -m "feat: add citation formatting and unverified-link marking"
```

---

### Task 2: Provider PDF input, web search and sources

**Files:**
- Modify: `backend/providers.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `Source` from Task 1 (`{"url", "title"}` dicts)
- Produces (in `backend/providers.py`):
  - `@dataclass class PdfFile: filename: str; data: bytes`
  - `async def query_model(model: str, messages: List[Dict[str, str]], timeout: float = 300.0, files: Optional[List[PdfFile]] = None, web_search: bool = False) -> Optional[Dict[str, Any]]`. Returns `{"content": str, "reasoning_details": None, "sources": List[Source]}` or `None` on any failure.
  - `async def query_models_parallel(models: List[str], messages: List[Dict[str, str]], files: Optional[List[PdfFile]] = None, web_search: bool = False) -> Dict[str, Optional[Dict[str, Any]]]`
  - `files` are attached to the **last** message in `messages`, which is always `role: "user"`. Earlier messages are plain text history.

Wire formats (one per provider; base64 has no newlines: `base64.standard_b64encode(data).decode()`):

| | PDF block in last user message | Web search | Sources | Text |
|---|---|---|---|---|
| Anthropic `POST /v1/messages` | `{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}` before the `{"type": "text", ...}` block | `tools: [{"type": "web_search_20260209", "name": "web_search"}]` | every `web_search_result` (`url`, `title`) inside `web_search_tool_result` blocks whose `content` is a list | join `text` blocks |
| OpenAI `POST /v1/responses` (replaces chat completions) | `{"role": "user", "content": [{"type": "input_file", "filename": name, "file_data": "data:application/pdf;base64," + b64}, {"type": "input_text", "text": ...}]}`; history items are `{"role", "content": str}` in `input` | `tools: [{"type": "web_search"}]` | `url_citation` annotations (`url`, `title`) on `output_text` parts | join `output_text` parts of `output` items with `type == "message"` |
| Gemini `generateContent` | `{"inline_data": {"mime_type": "application/pdf", "data": b64}}` part before the text part | `tools: [{"google_search": {}}]` | `candidates[0].groundingMetadata.groundingChunks[*].web` (`uri` → `url`, `title`) | non-`thought` text parts (unchanged) |

Anthropic `pause_turn`: if `stop_reason == "pause_turn"`, append `{"role": "assistant", "content": data["content"]}` to the request messages and POST again, at most 3 continuations; text and sources from every response are accumulated.

- [ ] **Step 1: Write the failing tests in `tests/test_providers.py`**

Monkeypatch `backend.providers._post` with an async fake that records `(url, payload)` and returns canned JSON. Monkeypatch the three API key constants in `backend.providers` to `"k"`.

```python
PDF = PdfFile("plan.pdf", b"%PDF-1.4 x")

async def test_anthropic_sends_pdf_and_web_search_and_extracts_sources(fake_post):
    fake_post.reply = {"stop_reason": "end_turn", "content": [
        {"type": "server_tool_use"},
        {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://a.com", "title": "A"}]},
        {"type": "text", "text": "answer"}]}
    r = await query_model("anthropic/claude-opus-5-5", [{"role": "user", "content": "q"}], files=[PDF], web_search=True)
    body = fake_post.calls[0][1]
    assert body["messages"][-1]["content"][0]["type"] == "document"
    assert body["tools"] == [{"type": "web_search_20260209", "name": "web_search"}]
    assert r == {"content": "answer", "reasoning_details": None, "sources": [{"url": "https://a.com", "title": "A"}]}

async def test_anthropic_tolerates_search_error_object(fake_post):
    fake_post.reply = {"stop_reason": "end_turn", "content": [
        {"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
        {"type": "text", "text": "answer"}]}
    r = await query_model("anthropic/claude-opus-5-5", [{"role": "user", "content": "q"}], web_search=True)
    assert r["sources"] == []

async def test_anthropic_resumes_pause_turn(fake_post):
    fake_post.replies = [{"stop_reason": "pause_turn", "content": [{"type": "text", "text": "part1 "}]},
                         {"stop_reason": "end_turn", "content": [{"type": "text", "text": "part2"}]}]
    r = await query_model("anthropic/claude-opus-5-5", [{"role": "user", "content": "q"}], web_search=True)
    assert r["content"] == "part1 part2"
    assert fake_post.calls[1][1]["messages"][-1]["role"] == "assistant"

async def test_openai_uses_responses_api(fake_post):
    fake_post.reply = {"output": [{"type": "web_search_call"}, {"type": "message", "content": [
        {"type": "output_text", "text": "answer", "annotations": [{"type": "url_citation", "url": "https://b.com", "title": "B"}]}]}]}
    r = await query_model("openai/gpt-5.1", [{"role": "user", "content": "old"}, {"role": "assistant", "content": "prev"}, {"role": "user", "content": "q"}], files=[PDF], web_search=True)
    url, body = fake_post.calls[0]
    assert url == "https://api.openai.com/v1/responses"
    assert body["input"][-1]["content"][0]["type"] == "input_file"
    assert body["input"][0] == {"role": "user", "content": "old"}
    assert body["tools"] == [{"type": "web_search"}]
    assert r["sources"] == [{"url": "https://b.com", "title": "B"}]

async def test_gemini_sends_inline_pdf_and_grounding(fake_post):
    fake_post.reply = {"candidates": [{"content": {"parts": [{"text": "answer"}]},
        "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://c.com", "title": "C"}}]}}]}
    r = await query_model("google/gemini-3.1-pro-preview", [{"role": "user", "content": "q"}], files=[PDF], web_search=True)
    body = fake_post.calls[0][1]
    assert body["contents"][-1]["parts"][0]["inline_data"]["mime_type"] == "application/pdf"
    assert body["tools"] == [{"google_search": {}}]
    assert r["sources"] == [{"url": "https://c.com", "title": "C"}]

async def test_no_tools_when_web_search_off(fake_post):
    fake_post.reply = {"candidates": [{"content": {"parts": [{"text": "t"}]}}]}
    await query_model("google/gemini-3.8-flash", [{"role": "user", "content": "q"}])
    assert "tools" not in fake_post.calls[0][1]

async def test_gemini_without_candidates_returns_none(fake_post):
    fake_post.reply = {"promptFeedback": {"blockReason": "SAFETY"}}
    assert await query_model("google/gemini-3.1-pro-preview", [{"role": "user", "content": "q"}]) is None
```

Put the `fake_post` fixture in `tests/conftest.py`: an object with `calls`, `reply` (returned every call) or `replies` (popped in order).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_providers.py -v`
Expected: FAIL (`ImportError: cannot import name 'PdfFile'`)

- [ ] **Step 3: Implement the interfaces in `backend/providers.py`**

Extend each `_query_*` with `files` and `web_search` parameters per the table. Change `OPENAI_API_URL` to `https://api.openai.com/v1/responses`. Every provider returns the `sources` key, which is an empty list when web search is off.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 5: Live check that existing calls still work**

Run: `uv run python -m backend.check_models`
Expected: 4 `OK` lines, exit 0. This exercises the OpenAI Responses API for real.

- [ ] **Step 6: Commit**

```bash
git add backend/providers.py tests/conftest.py tests/test_providers.py
git commit -m "feat: PDF input, web search and sources for all providers"
```

---

### Task 3: File storage and upload endpoint

**Files:**
- Modify: `backend/config.py` (add `UPLOADS_DIR = "data/uploads"`, `MAX_CONVERSATION_FILES_BYTES = 14 * 1024 * 1024`)
- Modify: `backend/storage.py`, `backend/main.py`
- Modify: `pyproject.toml` (via `uv add python-multipart`)
- Test: `tests/test_files_api.py`

**Interfaces:**
- Consumes: `PdfFile` from Task 2
- Produces:
  - `storage.add_file(conversation_id: str, filename: str, data: bytes) -> Dict[str, Any]`: writes `UPLOADS_DIR/{conversation_id}/{file_id}.pdf` (`file_id` = uuid4 hex), appends `{"id", "filename", "size", "uploaded_at"}` to `conversation["files"]`, and returns that dict.
  - `storage.get_files(conversation_id: str) -> List[PdfFile]`: reads the bytes for every entry in `conversation.get("files", [])`.
  - `create_conversation` writes `"files": []`. `get_conversation` sets `files` to `[]` when the key is missing.
  - `POST /api/conversations/{conversation_id}/files` (multipart field `file`) → 200 with the file dict; 404 if the conversation is unknown; 400 `{"detail": "Only PDF files are supported"}` unless the bytes start with `b"%PDF-"`; 400 `{"detail": "Attachments for this conversation would exceed 14 MB"}` when existing sizes + new size > `MAX_CONVERSATION_FILES_BYTES`. Nothing is written on 400.
  - The `Conversation` response model gains `files: List[Dict[str, Any]] = []`.

- [ ] **Step 1: Add dependency**

Run: `uv add python-multipart`

- [ ] **Step 2: Write the failing tests in `tests/test_files_api.py`**

Use `fastapi.testclient.TestClient(backend.main.app)`, and monkeypatch `backend.storage.DATA_DIR` / `backend.storage.UPLOADS_DIR` to `tmp_path` subdirectories.

```python
def test_upload_pdf_attaches_to_conversation(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/files", files={"file": ("plan.pdf", b"%PDF-1.4 data", "application/pdf")})
    assert r.status_code == 200 and r.json()["filename"] == "plan.pdf" and r.json()["size"] == 13
    assert client.get(f"/api/conversations/{cid}").json()["files"][0]["filename"] == "plan.pdf"
    assert [f.data for f in storage.get_files(cid)] == [b"%PDF-1.4 data"]

def test_rejects_non_pdf(client, uploads_dir):
    cid = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/files", files={"file": ("x.pdf", b"PK\x03\x04", "application/pdf")})
    assert r.status_code == 400 and r.json()["detail"] == "Only PDF files are supported"
    assert not any(uploads_dir.rglob("*.pdf"))

def test_rejects_when_total_exceeds_limit(client, monkeypatch):
    monkeypatch.setattr("backend.main.MAX_CONVERSATION_FILES_BYTES", 20)
    cid = client.post("/api/conversations", json={}).json()["id"]
    assert client.post(f"/api/conversations/{cid}/files", files={"file": ("a.pdf", b"%PDF-" + b"x" * 10, "application/pdf")}).status_code == 200
    r = client.post(f"/api/conversations/{cid}/files", files={"file": ("b.pdf", b"%PDF-" + b"x" * 10, "application/pdf")})
    assert r.status_code == 400 and r.json()["detail"] == "Attachments for this conversation would exceed 14 MB"

def test_upload_unknown_conversation_404(client):
    assert client.post("/api/conversations/nope/files", files={"file": ("a.pdf", b"%PDF-", "application/pdf")}).status_code == 404

def test_legacy_conversation_without_files_key_loads(client, data_dir):
    (data_dir / "old.json").write_text('{"id": "old", "created_at": "2025-01-01T00:00:00", "title": "t", "messages": []}')
    assert client.get("/api/conversations/old").json()["files"] == []
    assert storage.get_files("old") == []
```

The 14 MB wording is fixed copy, so the 400 message stays the same even when the limit is patched in the test.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_files_api.py -v`
Expected: FAIL (404/405 on the files route)

- [ ] **Step 4: Implement the storage functions, the config values and the endpoint**

In `main.py`, import `MAX_CONVERSATION_FILES_BYTES` from `.config` at module level, so the test can patch `backend.main.MAX_CONVERSATION_FILES_BYTES`.

- [ ] **Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock backend/config.py backend/storage.py backend/main.py tests/test_files_api.py
git commit -m "feat: per-conversation PDF upload and storage"
```

---

### Task 4: Council history, files, web search, table and link verification

**Files:**
- Modify: `backend/council.py`, `backend/main.py`
- Test: `tests/test_council.py`

**Interfaces:**
- Consumes: `query_models_parallel` / `query_model` / `PdfFile` (Task 2), `format_sources` / `collect_verified_urls` / `mark_unverified` (Task 1), `storage.get_files` (Task 3)
- Produces (in `backend/council.py`):
  - `build_history(prior_messages: List[Dict]) -> List[Dict[str, str]]`: for each user message that is directly followed by an assistant message with a `stage3.response` that is not the error fallback, emit `{"role": "user", "content": user.content}` then `{"role": "assistant", "content": stage3.response}`. Skip unpaired or failed turns.
  - `stage1_collect_responses(user_query: str, history: List[Dict] = [], files: List[PdfFile] = []) -> List[Dict]`: sends `history + [{"role": "user", "content": build_stage1_prompt(user_query)}]` with `files` and `web_search=True`. Each result is `{"model", "response": content + format_sources(sources), "sources": sources}`.
  - `build_stage1_prompt(user_query: str) -> str`: the user query followed by this instruction block (exact copy):
    ```
    ---
    Instructions: Use web search to verify any figures, statistics or facts that may have changed recently, and prefer the most recent data. Next to each figure you state, put its source URL as a markdown link. If you could not verify a figure, mark it "출처 미확인". If documents are attached, base your review on their content.
    ```
  - `stage2_collect_rankings(user_query, stage1_results, history=[], files=[])`: the same prompt as today, sent after `history`, with `files`, and `web_search=False`.
  - `stage3_synthesize_final(user_query, stage1_results, stage2_results, history=[], files=[], verified_urls=set())`: sent after `history` with `files` and `web_search=False`. The chairman prompt gains this rule (exact copy): `Use only URLs that appear in the council responses above; never invent new URLs. If a claim has no source, write "출처 미확인".` When `files` is non-empty, it also gains the table instruction (exact copy):
    ```
    The user attached document(s). Start with a 1-2 sentence summary, then present your answer as a markdown table with exactly these columns:
    | # | 기획서 위치 | 현재 내용 | 수정 제안 (최신 데이터) | 근거·출처 |
    Add brief notes below the table only if needed. If the user's question is not a request for revisions (for example, a follow-up about one item), answer in free form instead.
    ```
    Apply `mark_unverified(response, verified_urls)` to the chairman's text before returning.
  - `run_full_council(user_query, prior_messages: List[Dict] = [], files: List[PdfFile] = [])`: builds the history, runs the stages, and computes `verified_urls = collect_verified_urls(prior_messages, stage1_results)`.
  - `main.py`: both send endpoints read `prior = conversation["messages"]` (loaded **before** `add_user_message`) and `files = storage.get_files(conversation_id)`. The batch endpoint calls `run_full_council(request.content, prior, files)`. The stream endpoint calls the stage functions directly with `build_history(prior)`, `files` and `collect_verified_urls(prior, stage1_results)`.
  - Use `None` defaults plus `or []` in the real signatures; do not use mutable defaults.

- [ ] **Step 1: Write the failing tests in `tests/test_council.py`**

Monkeypatch `backend.council.query_models_parallel` and `backend.council.query_model` with fakes that record their kwargs and messages.

```python
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

async def test_stage2_has_files_but_no_web_search(fake_council): ...  # assert web_search False, files == [PDF]

async def test_stage3_table_only_with_files_and_marks_unverified(fake_council):
    fake_council.single_reply = {"content": "see [x](https://fake.com)", "sources": []}
    with_files = await stage3_synthesize_final("q", S1, S2, files=[PDF], verified_urls={"https://a.com"})
    assert "기획서 위치" in fake_council.single_calls[-1]["messages"][-1]["content"]
    assert with_files["response"] == "see [x](https://fake.com) ⚠️ 미검증"
    await stage3_synthesize_final("q", S1, S2)
    assert "기획서 위치" not in fake_council.single_calls[-1]["messages"][-1]["content"]
    assert fake_council.single_calls[-1]["web_search"] is False
```

Write `test_stage2_has_files_but_no_web_search` out in full, in the same style as the tests above.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_council.py -v`
Expected: FAIL (`ImportError: cannot import name 'build_history'`)

- [ ] **Step 3: Implement the interfaces in `council.py` and wire up `main.py`**

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/council.py backend/main.py tests/test_council.py
git commit -m "feat: thread history, files and web search through council stages"
```

---

### Task 5: Frontend upload UI, follow-up input and tables

**Files:**
- Modify: `frontend/package.json` (via `npm install remark-gfm`)
- Modify: `frontend/src/api.js`, `frontend/src/App.jsx`, `frontend/src/components/ChatInterface.jsx`, `frontend/src/components/ChatInterface.css`, `frontend/src/components/Stage1.jsx`, `frontend/src/components/Stage3.jsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: `POST /api/conversations/{id}/files` and `conversation.files` (Task 3)
- Produces:
  - `api.uploadFile(conversationId, file) -> Promise<{id, filename, size, uploaded_at}>`. On a non-OK response, it throws `Error(detail)` using the JSON `detail` field.
  - `App.jsx` `handleUploadFile(file)` calls `api.uploadFile`, then appends the result to `currentConversation.files`, and rethrows on failure.
  - `ChatInterface` props add `onUploadFile` and read `conversation.files`.

- [ ] **Step 1: Install remark-gfm and enable it**

Run: `cd frontend && npm install remark-gfm`. Then pass `remarkPlugins={[remarkGfm]}` to the `ReactMarkdown` in `Stage1.jsx` and `Stage3.jsx`.

- [ ] **Step 2: Add table styles in `index.css`**

Style `.markdown-content table`: border-collapse, 1px `#ddd` cell borders, 6px 10px cell padding, header background `#f5f8fc`, and a horizontal-scroll wrapper behavior (`display: block; overflow-x: auto`).

- [ ] **Step 3: Add `api.uploadFile` and `handleUploadFile`**

- [ ] **Step 4: Update `ChatInterface`**

- Remove the `conversation.messages.length === 0 &&` condition so the input form always renders.
- Add an "Attach PDF" button that opens a hidden `<input type="file" accept="application/pdf">`. Disable it while `isLoading` or uploading.
- Show attached files above the input as `filename (x.x MB)` chips.
- Show an upload error in red text under the chips; clear it on the next successful upload.
- Reset the file input value after each pick so the same file can be picked again.

- [ ] **Step 5: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: no lint errors; build succeeds

- [ ] **Step 6: Manual browser check**

Start both servers and open http://localhost:5173.
- Create a conversation and attach a small PDF: the chip appears.
- Attach a `.txt` renamed to `.pdf`: the error text "Only PDF files are supported" appears.
- Ask a question: a Stage 3 table renders with borders.
- Ask a follow-up: the input is still visible and the answer refers to the earlier turn.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src
git commit -m "feat: PDF attach UI, follow-up input and GFM tables"
```

---

### Task 6: Live verification and docs

**Files:**
- Modify: `backend/check_models.py`
- Create: `tests/fixtures/sample.pdf`
- Modify: `CLAUDE.md`, `README.md`

**Interfaces:**
- Consumes: `query_models_parallel(..., files=, web_search=)` (Task 2), `PdfFile`
- Produces: `uv run python -m backend.check_models --full`, which sends `tests/fixtures/sample.pdf` with `web_search=True` to every `COUNCIL_MODELS` entry. It asks: "What market size figure does the attached PDF state? Then find the latest published figure for the Korean e-commerce market via web search." It prints `OK model (n sources)` or `FAIL`, and exits 1 on any FAIL or on zero sources.

- [ ] **Step 1: Create the fixture**

Write `tests/fixtures/sample.pdf` as a hand-written minimal one-page PDF (Helvetica, a single `Tj` text op) whose only text is `Market size 2023: 1.2 trillion KRW`. Confirm the file starts with `%PDF-`.

- [ ] **Step 2: Add `--full` mode to `check_models.py`**

- [ ] **Step 3: Live run**

Run: `uv run python -m backend.check_models --full`
Expected: three `OK` lines with a source count of at least 1 each, and exit code 0. If a provider rejects the request format, fix the wire format in `providers.py`, add a regression case to `tests/test_providers.py`, and re-run.

- [ ] **Step 4: Update docs**

- `CLAUDE.md`: add the test command `uv run pytest`, the `--full` check, `citations.py`, the files endpoint, and the history/web-search/table rules.
- `README.md`: add a short "Reference files" section covering attaching a PDF, the 14 MB per-conversation limit, web search, and the table output.

- [ ] **Step 5: Commit**

```bash
git add backend/check_models.py tests/fixtures/sample.pdf CLAUDE.md README.md
git commit -m "feat: live PDF + web search check; document reference files"
```
