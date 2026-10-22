# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Response rule
항상 한국어로 답변을 하세요.

## Project Overview

LLM Council is a 3-stage deliberation system where multiple LLMs (called directly via the Anthropic, OpenAI and Gemini APIs) collaboratively answer a user question. The key idea is anonymized peer review in Stage 2, so models can't play favorites. Upstream describes it as a "vibe coded" hack, provided as-is.

## Commands

```bash
# Setup
uv sync                              # backend deps (Python >=3.10, managed by uv)
cd frontend && npm install           # frontend deps

# Run (both servers)
./start.sh                           # bash
./start.ps1                          # Windows PowerShell (local, untracked)

# Run manually
uv run python -m backend.main        # backend on :8001 — must run from project root
cd frontend && npm run dev           # frontend on :5173

# Frontend
cd frontend && npm run lint          # ESLint
cd frontend && npm run build         # Vite production build
```

Backend tests: `uv run pytest` (httpx is faked; no network). `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GEMINI_API_KEY` must be set in a root `.env` file (`load_dotenv(override=True)`: `.env` wins over OS environment variables). Check keys and model ids with:

```bash
uv run python -m backend.check_models   # pings every configured model, exits 1 on any failure
uv run python -m backend.check_models --full   # live: sends tests/fixtures/sample.pdf + web search to every council model; exits 1 on FAIL or 0 sources (makes real paid API calls)
``` The root `main.py` is an unused uv stub; the real entry point is `backend/main.py`.

## Architecture

### Request flow

```
User query (+ history: prior user questions and chairman answers)
  → Stage 1: all COUNCIL_MODELS in parallel, web search on + attached PDFs
             → [{model, body, response, sources}]: `body` = raw content (what Stage 2 sees),
               `response` = body + sources block
  → Stage 2: anonymize as "Response A/B/C…" (sources block stripped), PDFs attached,
             each model evaluates + ranks all → [{model, ranking, parsed_ranking}] + label_to_model
  → aggregate rankings (average rank position across evaluators)
  → Stage 3: CHAIRMAN_MODEL synthesizes from stage1 + stage2 with PDFs attached
             (if that call fails, retried once without PDFs before the error response);
             links not found in any search result are marked ⚠️ 미검증
```

Prior turns are sent to the models as history: earlier user questions and chairman (Stage 3) answers only. Earlier Stage 1/2 texts are never included.

### Backend (`backend/`, FastAPI)

- `config.py`: `COUNCIL_MODELS`, `CHAIRMAN_MODEL`, `TITLE_MODEL` as `provider/model-id` (provider: `anthropic` | `openai` | `google`), API keys from `.env`, `DATA_DIR`, `UPLOADS_DIR` (`data/uploads`), `MAX_CONVERSATION_FILES_BYTES` (14 MB).
- `providers.py`: `query_model()` routes by the `provider/` prefix to raw-httpx clients for Anthropic Messages, OpenAI Responses and Gemini `generateContent`; `query_models_parallel()` uses `asyncio.gather`. To add a provider, add a function to `PROVIDERS`. `query_model(..., files=, web_search=)` returns `{content, reasoning_details, sources:[{url,title}]}`; PDFs go as Anthropic `document` blocks, OpenAI Responses `input_file` (OpenAI uses `/v1/responses`, `tool_choice: required` for search) and Gemini `inline_data`; search is Anthropic `web_search_20260209`, OpenAI `web_search`, Gemini `google_search`. Failures return `None` and are logged; callers drop failed models and continue (graceful degradation). Empty/whitespace-only content (e.g. OpenAI with no message item, Gemini `RECITATION`) counts as failure and returns `None`.
- `council.py`: stage functions, `parse_ranking_from_text()`, `calculate_aggregate_rankings()`, `run_full_council()`, and `generate_conversation_title()` (uses `TITLE_MODEL`).
- `citations.py`: `format_sources()` builds the sources block appended to Stage 1 responses; `collect_verified_urls()` + `mark_unverified()` tag chairman links not seen in any search result with `⚠️ 미검증`.
- `storage.py`: one JSON file per conversation in `data/conversations/` (`{id, created_at, title, messages[], files[]}`). Assistant messages store `{role, stage1, stage2, stage3}` only. Conversation ids must be UUIDs (`is_valid_id`); other ids are treated as not found (404) so paths cannot escape `data/`. `get_files()` skips and logs attachments whose PDF is missing.
- `main.py`: two send endpoints:
  - `POST /api/conversations/{id}/message`: batch, returns `{stage1, stage2, stage3, metadata}`.
  - `POST /api/conversations/{id}/message/stream`: **SSE, used by the frontend**. Emits `stage1_start/complete`, `stage2_start/complete` (with metadata), `stage3_start/complete`, `title_complete`, `complete`, or `error`. Title generation runs concurrently with the stages.
  - `POST /api/conversations/{id}/files`: PDF-only upload, 14 MB total per conversation (Gemini caps inline requests at 20 MB and base64 adds ~33%); files are stored with the conversation and passed to every stage.
  - Changes to stage behavior must be mirrored in both endpoints (the stream endpoint calls stage functions directly, not `run_full_council`).

### Frontend (`frontend/src/`, React 19 + Vite)

- `api.js`: backend client; `sendMessageStream()` parses SSE lines manually.
- `App.jsx`: conversation state; builds the assistant message progressively from SSE events using per-stage `loading` flags.
- `components/Stage1/2/3.jsx`: tabbed raw responses; raw evaluations + "Extracted Ranking" + aggregate rankings; chairman answer.

## Key Design Decisions & Gotchas

- **Metadata is ephemeral**: `label_to_model` and `aggregate_rankings` are returned to the client but never persisted. Reloaded conversations have no de-anonymization metadata.
- **De-anonymization is client-side**: models only ever see "Response X" labels; Stage2.jsx substitutes bold model names for display.
- **Stage 2 prompt format is load-bearing**: models must end with a `FINAL RANKING:` header and a numbered list (`1. Response C`). `parse_ranking_from_text()` parses that, with a fallback regex that grabs any `Response X` in order. Changing the prompt can break parsing.
- **Port 8001, not 8000** (user has another app on 8000). If changed, update both `backend/main.py` and `frontend/src/api.js`. CORS in `main.py` allows only `localhost:5173` and `localhost:3000`.
- **Relative imports** in `backend/` (`from .config import …`): always run as `python -m backend.main` from the project root.
- **Markdown rendering**: wrap every `ReactMarkdown` in `<div className="markdown-content">` (styles in `index.css`).
- **Styling**: light theme, primary color `#4a90e2`; Stage 3 uses a green tint (`#f0fff0`).
- **Reference files & web search**: web search is always on in Stage 1 (sources block appended to each response); PDFs go to Stages 1-3. Stage 2 sees responses *without* the sources block. History sent to models is only prior user question + chairman answer. The chairman emits a table only when files are attached, and unverifiable URLs are marked `⚠️ 미검증`. Per-conversation PDF limit is 14 MB because Gemini's 20 MB inline request cap applies after base64 encoding (+~33%).
