# 화면에서 위원·의장 변경 — 설계

## 의도
필요할 때 위원회 구성(위원·의장)을 바꿔 가며 시험해 보고 싶다. 지금은 `config.py`를 고치고 서버를 재시작해야 한다.

## 접근 방식 (사용자 결정)
- **C. 화면 설정 패널 (선택)**, **전체 공통 설정 하나** (대화별 설정 아님).
- 탈락: A `config.py` 수정(현행) — 매번 코드 수정·재시작. B `.env` — 재시작 필요, 오타를 실행 전까지 모름.

## 설계
### 백엔드
- `backend/settings.py`(신규): `data/settings.json`에 `{council_models: [...], chairman_model}` 저장(기존
  `storage._write_json`으로 원자적 쓰기). 파일이 없거나 읽을 수 없으면 `config.py` 값을 기본으로 쓴다.
  - `get_council() -> (council_models, chairman_model)`
  - `set_council(council_models, chairman_model)`: 검증 — 위원 2–6명, 중복 없음, 모든 id가
    `provider/model-id` 형식이고 provider가 `anthropic|openai|google`. 실패 시 `ValueError`.
- `council.py`·`main.py`·`check_models.py`: 모듈 상수 대신 **호출 시점에** `settings.get_council()`을 읽는다.
  → 다음 질문부터 재시작 없이 적용. `TITLE_MODEL`은 그대로 `config.py`(변경 대상 아님).
- `backend/model_catalog.py`(신규): 공급자별 모델 목록 API 호출(요금 없음) 후 채팅 모델만 걸러
  `provider/id` 목록 반환. 키가 없거나 호출이 실패한 공급자는 `error` 메시지와 빈 목록.
  - OpenAI `GET /v1/models`: id가 `gpt-`·`o<숫자>`·`chatgpt-`로 시작하고 audio·realtime·tts·transcribe·image·
    embedding·moderation·search를 포함하지 않는 것.
  - Anthropic `GET /v1/models`(`limit=1000`): 전부.
  - Gemini `GET /v1beta/models`(`pageSize=1000`): `supportedGenerationMethods`에 `generateContent`가 있고 이름에
    `gemini`가 들어간 것(embedding·tts·image 제외). `models/` 접두어 제거.
- `main.py` 엔드포인트:
  - `GET /api/settings` → `{council_models, chairman_model, title_model}`
  - `PUT /api/settings` body `{council_models, chairman_model}` → 검증 실패 400(메시지 포함)
  - `GET /api/models` → `{openai: {models, error}, anthropic: {...}, google: {...}}`
  - `POST /api/settings/test` body `{models: [...]}` → 각 모델에 "Reply with the single word: OK" 한 번
    (`query_models_parallel`, 아주 적은 비용) → `[{model, ok, status, message}]`. 결과는 엔진 상태 패널에도
    자동 반영(`query_model`이 기록).
  - `GET /api/engines`는 현재 설정을 읽는다.

### 프론트엔드
- 사이드바 "위원회 설정" 버튼 → 모달 `CouncilSettings.jsx`:
  ```
  위원회 설정
  위원   [openai/gpt-5.1            ] [삭제]
         [google/gemini-3.1-pro-... ] [삭제]
         [anthropic/claude-opus-5-5 ] [삭제]
         [+ 위원 추가]
  의장   [anthropic/claude-opus-5-5 ]
  (입력칸은 불러온 모델 목록을 자동완성으로 제안, 목록에 없는 id도 직접 입력 가능)
  [연결 확인]  [저장]  [취소]
  OpenAI 목록 불러오기 실패: ...   ← 공급자별 오류
  ```
  - "연결 확인": 위원+의장을 `POST /api/settings/test`로 확인, 행마다 정상/크레딧 소진/한도 초과/오류 표시.
  - "저장": `PUT /api/settings`; 400이면 메시지 표시. 저장 후 엔진 상태 다시 불러오기.
  - 질문이 진행 중일 때는 저장 버튼 비활성화.

## 내 판단으로 정한 것
- 위원 수 2–6명(1명이면 상호 평가가 의미 없고, 많으면 비용·시간이 급증).
- 의장은 위원이 아니어도 된다.
- 저장 전 연결 확인은 **선택**(강제하지 않음). 확인은 "호출이 되는지"까지만 — 웹 검색·PDF 지원 여부는
  `check_models --full`로만 확인 가능(설정 화면에 한 줄 안내).
- 질문이 도는 중 설정을 바꿀 수 없게 화면에서 막는다(남은 Stage가 다른 구성으로 도는 것 방지).
- 모델 목록은 모달을 열 때마다 새로 불러온다(캐시 없음).

## 범위 밖
- 대화별 설정, 제목 모델 변경, 모델 단가·기능 표시, 웹 검색·PDF 지원 자동 판별.

## 검증
- 단위 테스트: 설정 기본값/저장/검증 실패, 손상된 파일 시 기본값, stage가 저장된 설정을 쓰는지,
  모델 목록 필터(가짜 응답 3종)·키 없음 오류, 4개 엔드포인트.
- 프론트엔드 lint·build. 실제 화면 확인은 사용자 승인 시.
