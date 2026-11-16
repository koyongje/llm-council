# 의장 답변 "주요 비판"·"반대 의견" 섹션 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 의장(Stage 3) 답변 본문 뒤에 `## 주요 비판`과 `## 반대 의견` 섹션이 항상 붙도록 의장 프롬프트를 바꾼다.

**Architecture:** `backend/council.py`에 상수 `CRITIQUE_INSTRUCTION`을 추가하고 `stage3_synthesize_final`의 의장 프롬프트에서 `TABLE_INSTRUCTION` 뒤(파일 유무와 무관)에 넣는다. 두 엔드포인트가 모두 이 함수를 쓰므로 다른 곳은 바뀌지 않는다.

**Tech Stack:** Python 3.10+, pytest(httpx 가짜 객체, 네트워크 없음), uv.

**Spec:** `docs/superpowers/specs/2026-11-16-critique-dissent-design.md`

## Global Constraints

- 섹션 제목은 정확히 `## 주요 비판`, `## 반대 의견` (한국어 고정).
- 반대 의견이 없으면 정확히 `실질적인 반대 의견 없음`이라고 쓰고, 이견을 지어내지 않는다.
- 주요 비판은 2–5개, 두 섹션 모두 짧게. 후속 질문(자유 형식 답변)에도 항상 붙인다.
- Stage 2 프롬프트, 순위 파싱, 프론트엔드, 추가 API 호출은 바꾸지 않는다.
- 커밋은 사용자가 요청할 때만 한다.

## Review Focus

1. 파일 첨부 시 표 지시와 비판 지시의 순서 — 섹션이 표보다 뒤에 와야 한다 → Task 1 테스트에서 프롬프트 내 위치 순서를 확인.
2. 파일 없는 경우에도 섹션 지시가 들어가야 한다 → Task 1 테스트의 파일 없는 호출로 확인.
3. PDF 실패 후 파일 없이 재시도하는 경로에서도 지시가 유지돼야 한다 → 재시도는 같은 `chairman_prompt`를 쓰므로 코드상 자동. 기존 재시도 테스트로 충분.
4. 모델이 실제로 지시를 따르는지(가짜 이견 생성 여부)는 단위 테스트로 확인할 수 없다 → 사용자 승인 시 유료 실행 1회로 확인.
5. `mark_unverified`가 새 섹션의 링크에도 적용되는지 → 답변 전체에 적용되므로 기존 테스트가 이미 다룬다.

---

### Task 1: 의장 프롬프트에 비판·반대 의견 지시 추가

**Files:**
- Modify: `backend/council.py:14-18` (상수 추가), `backend/council.py:205-207` (프롬프트)
- Test: `tests/test_council.py`
- Modify: `CLAUDE.md` (Request flow의 Stage 3 줄, Gotchas의 Reference files 줄)

**Interfaces:**
- Produces: `council.CRITIQUE_INSTRUCTION: str` (모듈 상수). `stage3_synthesize_final` 시그니처는 변경 없음.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_council.py`, 기존 `fake_council` 픽스처 사용)

```python
async def test_stage3_prompt_asks_for_critique_and_dissent(fake_council):
    fake_council.single_reply = {"content": "answer", "sources": []}
    await stage3_synthesize_final("q", S1, S2)
    prompt = fake_council.single_calls[-1]["messages"][-1]["content"]
    assert "## 주요 비판" in prompt and "## 반대 의견" in prompt
    assert "실질적인 반대 의견 없음" in prompt

    await stage3_synthesize_final("q", S1, S2, files=[PDF])
    prompt = fake_council.single_calls[-1]["messages"][-1]["content"]
    assert prompt.index("기획서 위치") < prompt.index("## 주요 비판") < prompt.index("## 반대 의견")
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_council.py::test_stage3_prompt_asks_for_critique_and_dissent -v`
Expected: FAIL (`"## 주요 비판" in prompt` assertion)

- [ ] **Step 3: `CRITIQUE_INSTRUCTION` 추가 후 프롬프트에 삽입**

`TABLE_INSTRUCTION` 아래에 상수를 정의하고, 프롬프트의 `{TABLE_INSTRUCTION ...}` 줄 바로 다음 줄에 `{CRITIQUE_INSTRUCTION}`을 넣는다. 문구:

```python
CRITIQUE_INSTRUCTION = """After the main answer (and after any table and notes), always end with these two short sections, including for follow-up questions:
## 주요 비판
2-5 bullet points on the key weaknesses, risks and uncertainties of your final answer, drawn from the Stage 2 evaluations and caveats raised in Stage 1.
## 반대 의견
Name each model whose conclusion or reasoning differed from your final answer and summarize its reasoning. Never invent disagreement to fill this section: if there was no substantive dissent, write "실질적인 반대 의견 없음"."""
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `uv run pytest -q`
Expected: 67 passed

- [ ] **Step 5: CLAUDE.md 갱신**

Request flow의 Stage 3 설명과 Gotchas의 "Reference files & web search" 항목에 한 줄씩 추가: 의장 답변은 항상 `## 주요 비판`(2–5개)과 `## 반대 의견`(없으면 "실질적인 반대 의견 없음")으로 끝난다.

- [ ] **Step 6: 커밋 (사용자 요청 시에만)**

```bash
git add backend/council.py tests/test_council.py CLAUDE.md docs/superpowers/specs/2026-11-16-critique-dissent-design.md docs/superpowers/plans/2026-11-16-critique-dissent.md
git commit -m "feat: chairman answer ends with key criticism and dissent sections"
```
