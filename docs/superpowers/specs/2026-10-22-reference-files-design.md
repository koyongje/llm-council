# 참고파일(PDF) + 웹 검색 기반 검토 기능 설계

## 의도와 배경

사용자는 자신이 작성한 기획서(PDF)를 LLM Council에 올려 **내용 검토와 "최신 데이터로 갱신할 부분" 제안**을 받고자 한다. 모델의 학습 지식은 시점이 고정되어 있으므로 최신 수치는 **모델이 웹에서 직접 찾아와야** 하며, 제안을 믿고 기획서에 반영할 수 있도록 **출처 링크**가 필수다.

## 목표

1. 대화창에서 PDF를 올리면 해당 대화에 첨부되어 저장되고, **그 대화의 이후 모든 질문**에 자동으로 함께 전달된다.
2. Stage 1 위원 모델(GPT, Gemini, Claude)이 PDF를 읽고 **웹 검색**으로 최신 데이터를 찾아, 수치마다 출처 URL을 붙여 제안한다.
3. 후속 질문이 가능하다. 후속 질문 때는 **이전 사용자 질문들 + 각 턴의 의장 최종 답변(Stage 3)**을 대화 기록으로 함께 넘긴다.
4. 파일이 첨부된 대화에서 의장(Stage 3)의 최종 답변은 **수정 제안 표**로 정리된다.

   | # | 기획서 위치 | 현재 내용 | 수정 제안 (최신 데이터) | 근거·출처 |
   |---|---|---|---|---|

## 비목표

- PDF 외 형식(docx, xlsx, 이미지 등) 지원
- 여러 대화에서 공유하는 파일 보관함
- 수정된 PDF/문서 파일 생성 (제안 표까지만)
- 텍스트 분할·임베딩 검색(RAG). PDF는 원본 그대로 각 API에 전달한다.

## 안티 목표 (기술적으로 동작해도 실패로 보는 것)

- 출처 없는 "최신" 수치, 또는 모델이 지어낸 URL이 표에 들어가는 것
- 후속 질문에서 모델이 첨부 파일이나 이전 제안을 모르는 것
- 파일을 붙이지 않은 일반 질문에 수정 제안 표 형식이 강제되는 것

## 제약

- 백엔드는 `backend/providers.py`에서 Anthropic / OpenAI / Gemini API를 **raw httpx**로 직접 호출한다(공식 SDK 미사용). 이 방식을 유지한다.
- PDF만 허용하고, 한 대화에 여러 파일을 올릴 수 있다. 크기 한도는 아래 "크기 한도" 참조.
- 위원 3개 중 일부가 실패해도 나머지로 진행하는 기존 graceful degradation을 유지한다.
- 대화 저장소는 기존과 같이 `data/` 아래 JSON + 파일 (git 제외 디렉터리).

## 현재 상태 (설계에 영향을 주는 사실)

- `frontend/src/components/ChatInterface.jsx`는 `conversation.messages.length === 0`일 때만 입력창을 보여준다 → 현재 UI에서는 **후속 질문 자체가 불가능**하다. 이 조건을 제거해야 한다.
- `backend/council.py`의 각 stage는 `[{"role": "user", "content": <문자열>}]` 하나만 보낸다. 대화 기록·파일을 전달하는 경로가 없다.
- `providers.query_model(model, messages)`의 `messages`는 `{role, content: str}` 목록이고, 각 provider 함수가 자기 형식으로 변환한다.
- 프론트엔드는 SSE 엔드포인트 `POST /api/conversations/{id}/message/stream`을 쓴다. 일괄 엔드포인트 `/message`도 존재하며 stage 변경은 두 엔드포인트에 모두 반영해야 한다.

## 결정된 동작

### 파일 업로드와 저장
- 대화창 입력 영역에 파일 첨부 버튼. 업로드는 메시지 전송과 별도의 요청으로 즉시 수행한다.
- 새 엔드포인트 (예: `POST /api/conversations/{id}/files`, multipart). 서버는 PDF 여부(`%PDF` 시그니처 / content-type)와 20MB 제한을 검사하고, 거부 시 이유를 반환한다.
- 저장: `data/uploads/{conversation_id}/` 아래 파일, 대화 JSON에 `files: [{id, filename, size, uploaded_at}]` 목록.
- 첨부된 파일 목록은 대화 화면 상단(또는 입력창 근처)에 이름으로 표시된다.

### 모델에 전달되는 내용
| 단계 | PDF | 대화 기록 | 웹 검색 |
|---|---|---|---|
| Stage 1 위원 | ✅ | ✅ | ✅ |
| Stage 2 평가 | ✅ (원문 대조용) | ✅ | ❌ |
| Stage 3 의장 | ✅ | ✅ | ❌ (위원들의 출처를 사용) |
| 제목 생성 | ❌ | ❌ | ❌ |

- 대화 기록 = 이전 턴의 `(user 질문, Stage 3 의장 답변)` 쌍들. Stage 1/2 개별 응답은 넘기지 않는다(비용).
- 대화에 파일이 **없어도** Stage 1 웹 검색은 항상 켠다(사용자 결정). 일반 질문에도 출처 표기 지시와 URL 검증이 적용되며, 답변 형식만 자유 형식이다. 따라서 OpenAI는 모든 요청에서 Responses API를 쓴다.

### Provider별 구현 방향 (raw HTTP)
- **Anthropic** (Messages API): PDF는 `document` 콘텐츠 블록(`source.type: "base64"`, `media_type: "application/pdf"`), 웹 검색은 서버 도구 `web_search`(정확한 tool type 버전 문자열은 구현 시 최신 문서로 확인). 응답 `content`에 `text` 외 `server_tool_use` / `web_search_tool_result` 블록이 섞이므로 `text` 블록만 이어 붙이고, 인용(citations)의 URL은 보존해 출처로 쓸 수 있게 한다.
- **OpenAI**: Chat Completions는 일반 모델에서 웹 검색 도구를 지원하지 않으므로 **Responses API(`/v1/responses`)로 전환**한다. PDF는 `input_file`(`file_data`: base64 data URL), 웹 검색은 `tools: [{"type": "web_search"}]`. 응답 텍스트와 `url_citation` 주석을 사용.
- **Gemini** (`generateContent`): PDF는 `inline_data`(`mime_type: application/pdf`), 웹 검색은 `tools: [{"google_search": {}}]`. 출처는 `groundingMetadata.groundingChunks[].web.uri`.
- `query_model` 인터페이스는 메시지 content가 문자열 외에 **첨부 파일**과 **웹 검색 on/off**를 표현할 수 있도록 확장한다(형태는 구현자 재량). 각 provider 함수가 자기 형식으로 변환한다.

### 출처 처리
- Stage 1 프롬프트: "최신 데이터는 반드시 웹 검색으로 확인하고, 각 수치 옆에 출처 URL을 마크다운 링크로 적어라. 확인하지 못한 수치는 '출처 미확인'으로 표시하라."
- provider가 구조화된 인용(citations/grounding)을 돌려주면 응답 텍스트 끝에 `출처:` 목록으로 덧붙여, 모델이 본문에 링크를 빠뜨려도 Stage 2/3가 출처를 볼 수 있게 한다.
- Stage 3 의장 프롬프트: 위원 응답에 실제로 등장한 URL만 사용, 새 URL 생성 금지, 출처가 없는 제안은 "출처 미확인"으로 표기.
- Gemini의 grounding URI는 `vertexaisearch.cloud.google.com` 리다이렉트 링크일 수 있다. 클릭하면 원문으로 이동하므로 그대로 사용한다.

### 의장 출력 형식
- 대화에 파일이 있으면: 짧은 요약 1~2문장 + 위 5열 표 + (필요 시) 표 아래 보충 설명. 후속 질문이 표 형식에 맞지 않는 성격이면(예: "3번 제안 출처 더 찾아줘") 의장이 자유 형식으로 답해도 된다.
- 파일이 없으면: 기존과 동일한 자유 형식.

### UI
- 입력창은 대화 내내 표시(후속 질문 허용).
- 첨부 버튼, 첨부 파일 목록(이름·크기), 업로드 실패 메시지 표시.
- Stage 3 표는 기존 `ReactMarkdown`으로 렌더링한다. react-markdown은 기본적으로 GFM 표를 지원하지 않으므로 `remark-gfm` 플러그인 추가가 필요하다.

## 비용·성능 메모
- 질문 1회당 PDF가 최대 7회 모델에 전달된다(Stage 1 ×3, Stage 2 ×3, Stage 3 ×1), 웹 검색 호출 비용이 추가된다. 사용자에게 이 비용 증가는 설명되었고 수용되었다.
- 웹 검색 + 긴 PDF로 응답 시간이 늘어난다. 현재 요청 제한 시간 300초를 유지하되, 실제 측정 후 조정한다.

### 크기 한도 (설계자 판단)
- 파일당 20MB가 아니라 **대화당 첨부 PDF 합계 14MB 이하**로 업로드 시점에 검사한다. base64로 약 33% 커지므로 14MB → 약 19MB가 되어, 대화 기록을 더해도 Gemini inline 요청 한도(20MB) 안에 들어간다.
- provider별 파일 업로드 API(Files API 등)는 쓰지 않는다. 모든 요청에 inline base64로 보낸다.
- 페이지 수·컨텍스트 초과로 특정 provider가 요청을 거부하면, 그 위원만 실패로 처리하고 나머지로 진행한다(기존 graceful degradation). 업로드 시 페이지 수 제한은 두지 않는다.

### 웹 검색 실패 처리 (설계자 판단)
- 도구 오류로 요청 자체가 실패하면 그 위원은 실패로 처리하고, 검색 없이 재시도하지 않는다.
- 요청은 성공했는데 모델이 검색하지 않았거나 provider가 인용을 돌려주지 않으면, 응답은 유지하되 `출처:` 목록 자리에 "웹 검색 출처 없음"을 붙여 Stage 2/3가 알 수 있게 한다.

### URL 검증 (설계자 판단)
- 프롬프트 지시에 더해 코드로 검증한다. Stage 1에서 provider가 **구조화된 인용/grounding으로 실제 반환한 URL**만 "검증된 URL" 집합으로 모은다. 모델이 본문에 직접 쓴 링크는 이 집합에 들지 않는다.
- Stage 3 답변의 링크 중 이 집합에 없는 것은 지우지 않고 링크 뒤에 `⚠️ 미검증`을 붙인다.

## 구현자에게 맡기는 것
- `query_model` 메시지 확장의 구체 형태, 파일 ID 방식, 엔드포인트 이름
- 업로드 UI의 세부 디자인 (기존 라이트 테마, `#4a90e2` 유지)
- 첨부 파일 삭제 기능 유무 (있으면 좋지만 필수 아님)
- `check_models`에 PDF/웹 검색 경로 점검 추가 여부

## 결정 기록
사용자가 정한 것: 웹에서 최신 데이터 직접 검색, 파일은 대화 단위로 유지, 후속 질문 시 이전 질문과 답변 전달, 수정 제안 표 + 출처 링크, 파일 없는 질문에도 웹 검색.

설계자가 정하고 사용자에게 설명한 것: PDF만 지원, Stage 2 평가자에게도 PDF 전달, 대화 기록에는 의장 답변만 포함, 웹 검색은 Stage 1만.

설계자 판단(검토 후 추가): 대화당 합계 14MB 한도와 inline 전송, 웹 검색 실패 처리, 코드 기반 URL 검증.
