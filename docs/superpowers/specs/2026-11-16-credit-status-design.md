# 엔진별 크레딧·한도 소진 표시 — 설계 (소규모 변경)

## 의도
OpenAI 크레딧이 떨어졌을 때 위원회가 아무 설명 없이 2명으로 줄었다(2026-11-16). 사용자는 **어떤 엔진이
크레딧이나 토큰 한도가 떨어졌는지** 화면에서 바로 알고 싶다.

## 범위 (사용자 결정)
- 엔진(모델)별 상태만 표시한다. 잔액 추정, 단가표, 사용액 집계, 잔액 입력은 **하지 않는다**
  (처음 설계했다가 사용자가 "복잡한 계산은 모두 중지"로 철회).

## 접근 방식
- **선택:** 모든 호출이 지나가는 `query_model`에서 성공/실패를 메모리에 기록 → `GET /api/engines` → 사이드바 패널.
- 탈락: 실패 이유를 Stage 결과에 실어 보내기 — 저장 형식과 두 엔드포인트, Stage 컴포넌트를 모두 바꿔야 하고
  제목 생성 엔진은 잡지 못한다.
- 탈락: 잔액 조회 API — 세 공급자 모두 공개 API가 없다.

## 설계
- `backend/engine_status.py`(신규): 메모리 dict, 모델 id → `{status, message, at}`.
  - 상태: `unknown`(아직 호출 없음) / `ok` / `credit`(크레딧·결제 소진) / `rate_limit`(429·한도 초과) / `error`.
  - 판정(대소문자 무시 부분 문자열): `credit` ← "insufficient_quota", "no credits remaining",
    "exceeded your current quota", "credit balance is too low", "prepayment credits are depleted";
    그 밖에 `rate_limit` ← "http 429", "rate limit", "resource_exhausted"; 나머지는 `error`.
  - 메시지는 200자로 자른다. 성공하면 `ok`로 돌아가고 메시지를 지운다.
- `providers.query_model`: 성공 시 `record_success`, 실패(예외·빈 응답) 시 `record_failure(model, 오류 문구)`.
  오류 문구는 이미 `_post`의 `RuntimeError("HTTP {code}: {본문}")`로 여기까지 온다.
- `main.py`: `GET /api/engines` → 설정된 엔진(`COUNCIL_MODELS`, `CHAIRMAN_MODEL`, `TITLE_MODEL`, 중복 제거, 순서 유지)마다
  `{model, status, message, at}`.
- 프론트엔드: `api.getEngineStatus()`; `Sidebar` 하단 `EngineStatus` 패널 — 엔진마다 이름과 배지
  (정상 / 크레딧 소진 / 한도 초과 / 오류 / 확인 전), 문제 있으면 짧은 메시지. `App`이 마운트 시와
  SSE `stage1_complete`·`stage2_complete`·`stage3_complete`·`complete`·`error` 때 다시 불러온다.

## 내 판단으로 정한 것
- 상태는 메모리에만 둔다: 서버를 재시작하면 "확인 전"으로 돌아간다(다음 질문 때 다시 판정).
- "지금 확인" 버튼(유료 핑)은 넣지 않는다. 필요하면 `uv run python -m backend.check_models`.
- 한도 초과(429)는 크레딧 소진과 구분해 표시한다: 잠시 뒤 풀리는 문제이기 때문.

## 검증
- 단위 테스트: 판정 3종 + 일반 오류, 성공 시 복구, 빈 응답 실패 기록, `GET /api/engines` 목록·순서.
- 프론트엔드 lint·build.
