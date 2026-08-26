# M8 Embedding Unit / Chunk + BGE-M3

기준일: 2026-08-26  
상태: **CURRENT / M8-01 PASS / M8-02 IMPLEMENTED / M8-03 REAL API VALIDATION NEXT**

M8은 M7 SQLite의 **active accepted Knowledge**를 검색용 embedding artifact로 변환하고 검증하는 단계다.

M8은 FAISS Retrieval 단계가 아니다. M8에서 Embedding Unit, Chunk 정책, deterministic embedding identity, BGE-M3 adapter와 vector artifact를 검증한 뒤 M9에서 FAISS를 만든다.

상세 결정 이력: `docs/M8_DECISION_LOG.md`

---

## 1. M8 입력 경계

기본 corpus는 M7 DB 전체가 아니다.

```text
knowledge_generation.state = active
AND accepted_attempt_id IS NOT NULL
    ↓
accepted knowledge_attempt
AND content_available = 1
    ↓
knowledge_item
```

Historical / candidate / review_required Generation과 accepted되지 않은 Attempt는 기본 embedding corpus에서 제외한다.

---

## 2. M8-01 · Corpus Baseline — PASS

### Embedding Unit

```text
Knowledge Item 1개
→ Embedding Unit 1개
```

Pilot 근거:

```text
Knowledge Item       285
statement mean       114.01 chars
statement p95        206.4 chars
statement max        447 chars
```

현재 corpus는 이미 짧은 atomic statement로 구성돼 있으므로 **baseline에서는 Chunk하지 않는다.**

Chunk는 BGE-M3 tokenizer 길이, 복합 검색 의도, Retrieval sanity 결과가 실제로 필요성을 보여줄 때만 추가한다.

### Text Profile

```text
text_profile = statement_v1
embedding_text = knowledge_item.statement.strip()
embedding_text_hash = SHA-256(UTF-8 embedding_text)
```

후속 비교 후보인 `category_statement_v1`, `issue_summary_category_statement_v1`는 아직 기본값이 아니다.

### Corpus Artifact v0.1

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

사용자 로컬 M7 SQLite에서 최종 확인:

```text
corpus_schema_version: 0.1
text_profile: statement_v1
corpus_rows: 285
```

따라서:

```text
M7 active accepted Knowledge Item 285
→ M8 corpus 285
→ 누락/중복 없음
```

**M8-01 = PASS / DONE**

---

## 3. M8-02 · Deterministic Embedding Contract — IMPLEMENTED

### 3.1 Identity 계층

Knowledge identity와 Embedding artifact identity를 분리한다.

```text
Knowledge
ki_ = knowledge_item_id

Embedding Contract
ec_ = embedding_contract_hash

Embedding Artifact
emb_ = embedding_id
```

Embedding Contract v0.1:

```text
embedding_contract_version = 0.1
text_profile               = statement_v1
embedding_model            = BAAI/bge-m3
embedding_model_profile    = runtime supplied
embedding_dimension        = 1024
```

`embedding_model_profile`은 같은 model name 아래 serving revision/deployment 차이를 표현한다. revision metadata를 알 수 없는 Pilot에서는 `internal-bge-m3-unversioned`로 명시한다.

Endpoint URL은 배포 위치이므로 logical identity에는 넣지 않는다.

### 3.2 Deterministic ID

```text
embedding_contract_hash
= ec_ + SHA256(canonical contract JSON)

embedding_id
= emb_ + SHA256({
    knowledge_item_id,
    embedding_text_hash,
    embedding_contract_hash
  })
```

M6 ID와 같은 `id_schema_version=1 + kind + canonical JSON + full SHA-256` 규칙을 재사용한다.

Vector 값과 FAISS position은 identity material이 아니다.

---

## 4. BGE-M3 API Contract

확인된 사내 API 계약:

```text
Model              BAAI/bge-m3
Serving            TEI / OpenAI-compatible embeddings API
Request max batch  64
Dense dimension    1024
Usage limit        200 requests/min
```

OpenAI-compatible request baseline:

```json
{
  "model": "BAAI/bge-m3",
  "input": ["text1", "text2"]
}
```

Endpoint와 인증정보는 코드에 하드코딩하지 않는다.

```text
.env
BGE_M3_ENDPOINT=<OpenAI-compatible embeddings 전체 URL>
BGE_M3_API_KEY=<필요한 경우만>
```

일반 계약값은 `config/settings.yaml`의 `embedding:` 블록에서 관리한다.

---

## 5. Batch / Mapping Contract

기본 batch size:

```text
64
```

Pilot 285 corpus:

```text
64 + 64 + 64 + 64 + 29
→ 5 HTTP requests
```

64를 초과하는 batch 설정은 시작 전에 거부한다.

응답 배열의 물리 순서에 의존하지 않고 OpenAI-compatible `data[].index`를 authoritative mapping으로 사용한다.

검증:

```text
index 누락 없음
index 중복 없음
index 범위 오류 없음
response count = request count
모든 vector dimension = 1024
```

---

## 6. Retry / Failure Contract

재시도:

```text
network / timeout
HTTP 429
HTTP 500 / 502 / 503 / 504
```

기본 총 시도 횟수:

```text
3
```

즉시 실패:

```text
HTTP 400 / 401 / 403 / 404 등 request/auth/config 오류
response schema 오류
response index mapping 오류
vector dimension 오류
```

잘못된 응답을 retry로 덮어 성공 처리하지 않는다.

---

## 7. Atomic Publish

Pilot에서는 partial vector artifact를 final 결과로 남기지 않는다.

```text
Batch 1~5 전부 성공
→ count / index / dimension 검증
→ temp JSONL 작성
→ atomic replace
→ final embedding artifact publish

중간 실패
→ final artifact publish하지 않음
```

Resume/checkpoint는 M8에서 과설계하지 않고 후속 orchestration 단계에서 다룬다.

---

## 8. Embedding Artifact v0.1

M8-03에서 생성할 row:

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

따라서 M9가 FAISS index를 다시 만들어도 `embedding_id → knowledge_item_id → Evidence` 경로를 복원할 수 있다.

---

## 9. 구현 위치

```text
src/jira_collector/embedding/
├─ corpus.py       active accepted corpus + JSONL validation
├─ contract.py     ec_ / emb_ deterministic identity
├─ client.py       OpenAI-compatible API / retry / index / dimension
├─ config.py       Jira 인증과 독립된 embedding runtime settings
├─ artifact.py     Knowledge ↔ vector artifact + atomic publish
└─ runner.py       batch/rate-limit/end-to-end orchestration

tools/jira_knowledge/
├─ export_embedding_corpus.py
└─ embed_bge_m3.py
```

`.env.example`과 `config/settings.yaml`에도 BGE-M3 runtime contract를 반영했다.

Synthetic tests에서 다음을 확인했다.

```text
285 → [64,64,64,64,29] batch
response index 순서 복원
index 중복/누락 차단
잘못된 dimension 차단
429/5xx retry
400 즉시 실패
deterministic ec_/emb_ ID
corpus JSONL hash 재검증
atomic final publish
Jira credential 없이 embedding settings load
```

GitHub Actions pytest: **PASS**

---

## 10. M8 Gate

### M8-01 · Corpus Baseline

```text
[x] active accepted corpus query/contract
[x] Knowledge Item = Embedding Unit
[x] baseline Chunk 없음
[x] statement_v1
[x] corpus exporter
[x] synthetic filtering/order/hash
[x] 실제 M7 DB corpus row = 285

M8-01 PASS
```

### M8-02 · BGE-M3 Contract / Adapter

```text
[x] deterministic embedding contract / ec_ / emb_
[x] OpenAI-compatible client
[x] batch <= 64
[x] response index mapping
[x] dimension 검증
[x] retry/non-retry 정책
[x] atomic artifact publish
[x] independent runtime config
[x] CI PASS

M8-02 IMPLEMENTED
```

### M8-03 · Real Embedding Gate

```text
[ ] 실제 사내 endpoint 연결
[ ] corpus 285개 embedding 성공
[ ] embedding_rows = 285
[ ] batch_count = 5
[ ] 모든 output dimension = 1024
[ ] Knowledge Item ↔ Embedding mapping 무결성
[ ] 동일 input/contract 재실행 identity 재현
[ ] 작은 quality sanity check
[ ] 문서/HTML 동기화
```

---

## 11. M8-03 실행 준비

`.env`에 실제 사내 값을 넣는다.

```dotenv
BGE_M3_ENDPOINT=<사내 OpenAI-compatible embeddings endpoint>
BGE_M3_API_KEY=<필요한 경우>
```

그다음:

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

실제 endpoint/token은 공개 문서나 Git에 기록하지 않는다.

---

## 12. M9와의 경계

```text
M8
→ validated embedding JSONL
→ deterministic emb_ ↔ ki_ mapping

M9
→ FAISS
→ active Retrieval
→ Top-k
```

**M8 Real Embedding Gate가 끝나기 전에는 M9로 이동하지 않는다.**
