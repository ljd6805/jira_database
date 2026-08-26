# M8 Real BGE-M3 Validation Log

기준일: 2026-08-26  
상태: **CURRENT / PREFLIGHT PASS / 1-ROW SMOKE PASS / FULL 285 NEXT**

이 문서는 M8-03 실제 사내 BGE-M3 embedding 검증 과정을 기록한다. 실제 endpoint, API key, custom header 이름/값, Jira 식별자/본문은 기록하지 않는다.

---

## 1. 입력 corpus

M8-01 실데이터 Gate:

```text
corpus_schema_version: 0.1
text_profile: statement_v1
corpus_rows: 285
```

판정:

```text
M8-01 = PASS
```

285는 M7 SQLite의 active accepted Knowledge Item 수와 일치한다.

---

## 2. Runtime 설정 Preflight

사용자 로컬 환경에서 embedding 설정 loader를 실행해 다음 aggregate 결과를 확인했다.

```text
endpoint configured : true
api_key configured  : false
custom_headers      : 6
model               : BAAI/bge-m3
dimension           : 1024
```

의미:

- endpoint 값이 로드됐다.
- 표준 Bearer API key는 사용하지 않는다.
- 고정 custom header 6개가 JSON으로 정상 파싱됐다.
- model/dimension contract는 `BAAI/bge-m3` / `1024`다.

판정:

```text
M8-03 runtime configuration preflight = PASS
```

---

## 3. 1-row Real API Smoke Test

전체 285개를 보내기 전에 실제 corpus의 첫 embedding text 1건만 사내 endpoint로 호출했다.

최종 성공 출력:

```text
API call: PASS
vectors : 1
dimension: 1024
```

확인된 사실:

- 로컬 PC → 사내 embedding endpoint HTTP 연결 성공
- 현재 고정 custom header 6개로 요청 성공
- OpenAI-compatible request/response baseline이 실제 endpoint에서 동작
- dense vector 1개 반환
- vector dimension = 1024

따라서 현재 설정에서 제외한 동적 UUID 형태 header는 **적어도 이 embedding smoke request의 성공에 필수는 아니었다.** 다만 다른 사내 API/게이트웨이에서의 필요성까지 일반화하지 않는다.

판정:

```text
M8-03 1-row real API smoke = PASS
```

---

## 4. Troubleshooting 기록

### T01 · VS Code `vscode-sqlite`가 M7 DB를 열지 못함

증상:

```text
no such column: "table"
WHERE (type="table" OR type="view")
```

판단:

- M7 Gate에서 SQLite integrity/FK 검증은 이미 PASS했다.
- 오류 SQL은 DB 내용이 아니라 legacy VS Code extension이 schema 목록을 읽을 때 실행한 query에서 발생했다.
- 따라서 DB corruption으로 취급하지 않았다.

해결:

- 오래된 `vscode-sqlite` 대신 read-only 중심의 현대 SQLite Viewer extension으로 교체해 DB 내용을 확인했다.

재발 방지:

- DB viewer 오류와 DB integrity 오류를 분리한다.
- DB 이상 판단 전 `PRAGMA integrity_check`와 Python `sqlite3` query 결과를 우선한다.

### T02 · `.env` multi-line custom header parse 오류

증상:

```text
python-dotenv could not parse statement starting at line ...
```

원인:

- 여러 줄 JSON을 하나의 환경변수 값으로 묶지 않고 `.env`에 배치하면 각 JSON 줄을 독립 `KEY=VALUE` 문장으로 해석하려고 한다.

해결:

- `BGE_M3_HEADERS_JSON` 전체가 하나의 dotenv value가 되도록 작성했다.
- 한 줄 JSON 또는 quote로 감싼 multi-line JSON을 사용한다.

핵심 원칙:

```text
한 줄이어야 한다 X
JSON 전체가 하나의 환경변수 값이어야 한다 O
```

### T03 · `BGE_M3_HEADERS_JSON` JSONDecodeError

증상:

```text
json.decoder.JSONDecodeError: Expecting value
BGE_M3_HEADERS_JSON은 JSON object여야 합니다.
```

원인:

초기 header 정의에 다음과 같은 Python 표현식이 포함돼 있었다.

```python
str(uuid.uuid4())
```

이것은 Python 실행식이지 JSON literal이 아니다.

해결:

- `.env`에는 static string header만 남겼다.
- Python 표현식 형태의 동적 UUID header는 static JSON에서 제외했다.

재발 방지:

- `.env` JSON에는 완성된 문자열/숫자/bool/null/배열/object 같은 JSON 값만 넣는다.
- runtime 계산이 필요한 header는 향후 필요성이 확인될 때 code-level dynamic header provider로 분리한다.

### T04 · 사내 custom header 지원 필요

상황:

- 사내 embedding API는 표준 Bearer API key만 사용하는 구조가 아니며 custom header를 사용한다.

결정:

```text
BGE_M3_ENDPOINT
BGE_M3_API_KEY        optional
BGE_M3_HEADERS_JSON   optional generic custom headers
```

구현 원칙:

- custom header는 HTTP request에만 사용
- header 이름/값은 `ec_`/`emb_` identity에 포함하지 않음
- header 이름/값은 embedding artifact/stdout/public docs에 기록하지 않음
- `EmbeddingRuntimeSettings`의 secret fields는 repr에서 제외

### T05 · Real API smoke에서 HTTP 404

증상:

```text
EmbeddingApiError: Embedding API HTTP 404; retry하지 않습니다.
```

판단:

- HTTP 서버까지는 도달했다.
- 404는 retry로 해결할 transient 장애가 아니다.
- custom header보다 endpoint route/path 오류를 우선 의심했다.

원인:

- `.env`의 `BGE_M3_ENDPOINT` 경로가 실제 embeddings route와 달랐다.

해결:

- endpoint를 실제 사내 OpenAI-compatible embeddings 전체 URL로 수정했다.
- 수정 후 동일 1-row smoke test가 PASS했다.

재발 방지:

HTTP 상태를 다음처럼 분류한다.

```text
404        → endpoint/path/config 우선 점검
401 / 403  → 인증/header 우선 점검
400 / 422  → request body/contract 우선 점검
429 / 5xx  → transient retry 대상
200        → response schema/dimension 검증
```

### T06 · `corpus_rows: 28` 전달 오류

상황:

- 대화 중 사용자 복사/붙여넣기 과정에서 `28`로 전달됐으나 실제 실행 출력은 `285`였다.

조치:

- 프로젝트 결함으로 기록하지 않는다.
- CLI의 `--expected-count 285` Gate를 유지해 실제 실행에서는 count mismatch를 실패로 처리한다.

교훈:

- 사람이 전달한 숫자와 실행기의 deterministic Gate를 분리한다.
- aggregate count는 가능하면 CLI 자체가 검증/종료코드로 강제한다.

---

## 5. 현재 M8-03 Gate 상태

```text
[x] M8-01 corpus_rows = 285
[x] embedding runtime settings parse
[x] custom header 6개 runtime load
[x] 1-row real API call success
[x] smoke vector dimension = 1024
[ ] corpus 285개 full embedding 성공
[ ] embedding_rows = 285
[ ] batch_count = 5
[ ] 모든 output dimension = 1024
[ ] emb_ ↔ ki_ mapping 무결성
[ ] 동일 input/contract 재실행 identity 재현
[ ] 작은 quality sanity check
[ ] final artifact atomic publish 확인
```

---

## 6. 다음 실행

전체 Pilot embedding:

```powershell
python tools/jira_knowledge/embed_bge_m3.py --corpus data/embedding/runs/20260804T043628Z/corpus.statement_v1.jsonl --output data/embedding/runs/20260804T043628Z/embeddings.statement_v1.bge_m3.jsonl --expected-count 285
```

성공 기대값:

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

실패 시 HTTP status, aggregate count, response contract 오류만 문서화하고 secret/header 값은 기록하지 않는다.
