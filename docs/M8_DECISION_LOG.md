# M8 Decision Log

기준일: 2026-08-26  
상태: **ACTIVE**

M8 · Embedding Unit / Chunk + BGE-M3 단계에서 합의한 결정을 시간 순서대로 기록한다.

---

## M8-01 · Active Accepted Corpus / Embedding Unit Baseline

상태: **PASS / DONE**

### 결정

M8 기본 corpus는 M7 SQLite의 모든 Knowledge가 아니라 다음 조건만 사용한다.

```text
knowledge_generation.state = active
AND accepted_attempt_id IS NOT NULL
    ↓
accepted knowledge_attempt
AND content_available = 1
    ↓
knowledge_item
```

Historical / candidate / review_required Generation과 accepted되지 않은 Attempt는 제외한다.

기본 Embedding Unit:

```text
Knowledge Item 1개
→ Embedding Unit 1개
```

근거:

```text
Knowledge Item       285
statement mean       114.01 chars
statement p95        206.4 chars
statement max        447 chars
```

따라서 baseline에서는 Chunk를 사용하지 않는다. Chunk는 실제 tokenizer 길이 문제, 복합 검색 의도, Retrieval sanity 개선 근거가 있을 때만 추가 검토한다.

Baseline text:

```text
text_profile = statement_v1
embedding_text = knowledge_item.statement.strip()
embedding_text_hash = SHA-256(UTF-8 embedding_text)
```

Corpus row:

```text
corpus_schema_version
text_profile
knowledge_item_id
knowledge_attempt_id
knowledge_generation_id
issue_version_id
jira_id
category
ordinal
embedding_text
embedding_text_hash
```

### Real DB Gate

최종 사용자 로컬 실행 결과:

```text
corpus_schema_version: 0.1
text_profile: statement_v1
corpus_rows: 285
```

초기에 `28`로 전달된 값은 복사/붙여넣기 과정의 전달 오류였고 실제 실행 결과는 `285`로 즉시 정정됐다. 프로젝트 결함으로 취급하지 않는다.

```text
[x] active accepted corpus exporter
[x] historical/candidate/review_required 제외
[x] accepted Attempt가 아닌 Item 제외
[x] deterministic ordering
[x] statement_v1 hash
[x] 실제 M7 DB corpus row = 285

M8-01 = PASS / DONE
```

---

## M8-02 · Deterministic Embedding Contract / BGE-M3 Adapter

상태: **IMPLEMENTED / CI PASS**

### 1. Embedding Contract v0.1

Knowledge identity와 Embedding artifact identity를 분리한다.

```text
Knowledge Item       ki_
Embedding Contract   ec_
Embedding Artifact   emb_
```

Embedding Contract v0.1 identity 입력:

```text
embedding_contract_version = 0.1
text_profile               = statement_v1
embedding_model            = BAAI/bge-m3
embedding_model_profile    = runtime supplied
embedding_dimension        = 1024
```

`embedding_model_profile`은 같은 model name 아래 serving revision/deployment 차이를 표현한다. revision metadata를 알 수 없는 Pilot에서는 `internal-bge-m3-unversioned`를 사용한다.

Endpoint URL과 인증/라우팅 header는 실행 환경 정보이므로 logical identity에 넣지 않는다.

### 2. Deterministic ID

M6와 같은 `id_schema_version=1 + kind + canonical JSON + full SHA-256` 규칙을 재사용한다.

```text
ec_ = H(contract version, text profile, model, model profile, dimension)

emb_ = H(knowledge_item_id, embedding_text_hash, ec_)
```

Vector 값, API endpoint, custom header, FAISS position은 `embedding_id` material이 아니다.

### 3. Runtime 설정 분리

실제 사내 endpoint/API key/custom header는 Git에 기록하지 않는다.

```text
.env
BGE_M3_ENDPOINT
BGE_M3_API_KEY
BGE_M3_HEADERS_JSON
```

일반 설정은 `config/settings.yaml`에서 관리한다.

```text
model = BAAI/bge-m3
model_profile = internal-bge-m3-unversioned
text_profile = statement_v1
dimension = 1024
batch_size = 64
requests_per_minute = 200
max_attempts = 3
```

Embedding 설정 loader는 Jira ID/Password 없이 독립 실행된다.

### 4. Custom Header Contract

사내 API가 표준 Bearer token 대신 custom header를 요구할 수 있으므로 generic header injection을 지원한다.

`.env` 예시:

```dotenv
BGE_M3_ENDPOINT=https://.../v1/embeddings
BGE_M3_API_KEY=
BGE_M3_HEADERS_JSON='{"X-Custom-Header-1":"value1","X-Custom-Header-2":"value2"}'
```

규칙:

- `BGE_M3_HEADERS_JSON`은 JSON object이며 key/value 모두 문자열이다.
- header가 여러 개여도 하나의 JSON object로 전달한다.
- 표준 Bearer 인증을 사용하지 않으면 `BGE_M3_API_KEY`는 비운다.
- API key와 custom header를 둘 다 사용하는 배포도 지원한다.
- custom header는 HTTP request에만 사용한다.
- header 이름/값은 embedding identity, vector artifact, stdout, 공개 문서에 기록하지 않는다.
- 실제 header 이름/값은 `.env`에만 저장한다.

### 5. Request / Batch

OpenAI-compatible baseline:

```json
{
  "model": "BAAI/bge-m3",
  "input": ["text1", "text2"]
}
```

최대 batch 64:

```text
285
→ 64 + 64 + 64 + 64 + 29
→ 5 requests
```

64 초과 설정은 HTTP 호출 전에 거부한다.

### 6. Response Mapping

응답 배열의 물리 순서가 아니라 `data[].index`를 authoritative mapping으로 사용한다.

검증:

```text
index 누락 없음
index 중복 없음
범위 밖 index 없음
response count = request count
각 vector dimension = 1024
```

### 7. Retry / Failure

재시도:

```text
network / timeout
HTTP 429
HTTP 500 / 502 / 503 / 504
```

기본 총 시도 횟수 3회.

즉시 실패:

```text
400 / 401 / 403 / 404 등 request/auth/config 오류
response schema 오류
index mapping 오류
dimension 오류
```

### 8. Publish

Pilot에서는 partial vector artifact를 final 결과로 publish하지 않는다.

```text
모든 batch 성공
→ 전체 mapping/dimension 검증
→ temp JSONL
→ atomic replace
→ final artifact

중간 batch 실패
→ final artifact publish 금지
```

Resume/checkpoint는 후속 orchestration 단계에서 다룬다.

### 9. Embedding Artifact v0.1

```text
embedding_schema_version
embedding_contract_version
embedding_contract_hash
embedding_id
knowledge_item_id
knowledge_attempt_id
knowledge_generation_id
issue_version_id
jira_id
category
ordinal
text_profile
embedding_text_hash
embedding_model
embedding_model_profile
embedding_dimension
vector
```

M9는 `embedding_id ↔ knowledge_item_id` mapping을 유지한 채 FAISS를 만든다.

### 10. 구현

```text
src/jira_collector/embedding/
├─ corpus.py
├─ contract.py
├─ client.py
├─ config.py
├─ artifact.py
└─ runner.py

tools/jira_knowledge/embed_bge_m3.py
```

테스트:

```text
deterministic ec_/emb_
285 → 5 batch
response index 순서 복원
index 중복/누락 차단
dimension mismatch 차단
429/5xx retry
400 즉시 실패
custom header JSON validation / HTTP forwarding
corpus JSONL hash 재검증
atomic publish
Jira credential 없이 embedding config load
```

GitHub Actions pytest: **PASS**

```text
[x] embedding contract / deterministic ID
[x] OpenAI-compatible client
[x] batch <= 64
[x] response index mapping
[x] 1024 dimension contract
[x] retry/non-retry test
[x] custom header runtime support
[x] atomic publish
[x] independent runtime config
[x] CI PASS

M8-02 = IMPLEMENTED
```

---

## M8-03 · Real BGE-M3 Gate

상태: **CURRENT / NEXT VALIDATION**

실제 사내 endpoint로 다음을 확인한다.

```text
[ ] corpus_rows = 285
[ ] embedding_rows = 285
[ ] batch_count = 5
[ ] embedding_dimension = 1024
[ ] emb_ ↔ ki_ mapping 무결성
[ ] 동일 input/contract 재실행 identity 재현
[ ] 작은 quality sanity check
```

실행 전 `.env`에 실제 endpoint와 필요한 인증 정보를 입력한다. Bearer 방식이면 `BGE_M3_API_KEY`, custom header 방식이면 `BGE_M3_HEADERS_JSON`, 둘 다 필요한 환경이면 둘 다 사용한다. 실제 값은 Git/public 문서에 기록하지 않는다.

---

## 아직 결정하지 않은 것

- Chunk size / overlap
- BGE-M3 축소 dimension
- FAISS index structure
- retrieval top-k
- production incremental embedding/resume orchestration

**M8에서는 FAISS를 구현하지 않는다.** FAISS는 M9 책임이다.
