# M8 Embedding Unit / Chunk + BGE-M3

기준일: 2026-08-26  
상태: **DONE / REAL-RUN PASS**

M8은 M7 SQLite의 **active accepted Knowledge**를 검증된 embedding artifact로 변환하는 단계다.

M8에서는 FAISS를 구현하지 않는다. M8의 출력은 M9 FAISS + Active Retrieval의 입력이 되는 validated embedding JSONL이다.

상세 결정 이력: `docs/M8_DECISION_LOG.md`  
실환경 검증 이력: `docs/M8_REAL_EMBEDDING_LOG.md`

---

## 1. M8 입력 경계

기본 embedding corpus:

```text
knowledge_generation.state = active
AND accepted_attempt_id IS NOT NULL
    ↓
accepted knowledge_attempt
AND content_available = 1
    ↓
knowledge_item
```

Historical / candidate / review_required Generation과 accepted되지 않은 Attempt는 기본 corpus에서 제외한다.

---

## 2. M8-01 · Corpus Baseline — PASS

기본 Embedding Unit:

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

따라서 baseline에서는 선제 Chunk하지 않는다.

```text
text_profile = statement_v1
embedding_text = knowledge_item.statement.strip()
embedding_text_hash = SHA-256(UTF-8 embedding_text)
```

실데이터 Gate:

```text
corpus_schema_version: 0.1
text_profile: statement_v1
corpus_rows: 285
```

```text
M7 active accepted Knowledge Item 285
→ M8 corpus 285
→ 누락/중복 없음
```

**M8-01 = PASS / DONE**

---

## 3. M8-02 · Embedding Contract / Adapter — PASS

Knowledge identity와 Embedding artifact identity를 분리한다.

```text
Knowledge Item       ki_
Embedding Contract   ec_
Embedding Artifact   emb_
```

Embedding Contract v0.1:

```text
embedding_contract_version = 0.1
text_profile               = statement_v1
embedding_model            = BAAI/bge-m3
embedding_model_profile    = internal-bge-m3-unversioned
embedding_dimension        = 1024
```

Deterministic identity:

```text
ec_ = H(contract version, text profile, model, model profile, dimension)
emb_ = H(knowledge_item_id, embedding_text_hash, ec_)
```

Endpoint, API key, custom header, vector 값, FAISS position은 embedding identity material이 아니다.

---

## 4. BGE-M3 API Contract

실환경에서 검증된 계약:

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

사내 runtime은 custom header를 지원한다.

```text
BGE_M3_ENDPOINT      required
BGE_M3_API_KEY       optional
BGE_M3_HEADERS_JSON  optional generic custom headers
```

Secret/header 값은 Git, stdout, embedding artifact, public 문서에 기록하지 않는다.

---

## 5. Batch / Mapping / Failure Contract

Pilot 285 corpus:

```text
64 + 64 + 64 + 64 + 29
→ 5 HTTP requests
```

응답 mapping은 배열의 물리 순서가 아니라 `data[].index`를 사용한다.

검증:

```text
index 누락 없음
index 중복 없음
index 범위 오류 없음
response count = request count
모든 vector dimension = 1024
```

재시도:

```text
network / timeout / 429 / 500 / 502 / 503 / 504
```

즉시 실패:

```text
400 / 401 / 403 / 404
response schema 오류
index mapping 오류
dimension 오류
```

모든 batch가 성공한 뒤에만 final JSONL을 atomic publish한다.

---

## 6. Embedding Artifact v0.1

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

---

## 7. M8-03 · Real Embedding Gate — PASS

### 7.1 Smoke

```text
API call: PASS
vectors : 1
dimension: 1024
```

### 7.2 Full Pilot

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

### 7.3 Artifact Integrity

```text
validation: PASS
corpus_rows: 285
embedding_rows: 285
unique_knowledge_item_ids: 285
unique_embedding_ids: 285
contract_count: 1
mapping_failure_count: 0
identity_failure_count: 0
dimension_failure_count: 0
non_finite_vector_count: 0
zero_norm_vector_count: 0
temp_artifact_exists: false
```

즉:

```text
ki_ 285
↕ 1:1
emb_ 285

mapping failure      0
identity failure     0
dimension failure    0
invalid vector       0
```

### 7.4 Semantic Sanity

3개 샘플을 brute-force cosine similarity로 확인했다.

```text
Sample 1  PASS
Sample 2  PASS · 매우 양호
Sample 3  PASS · Top-3가 모두 의미상 타당
```

Sample 3의 Top-3 score:

```text
0.5918 / 0.5908 / 0.5900
```

점수 margin은 작지만 후보가 모두 의미상 타당했다. 이를 embedding 실패로 보지 않고 **dense semantic neighborhood** 관찰로 기록한다.

M9에서는 Top-1만 과신하지 않고 Top-k 후보군 + Evidence 사용을 검토한다.

---

## 8. Troubleshooting

실환경 연결 과정에서 확인된 주요 문제:

```text
T01 legacy SQLite Viewer query 오류
T02 python-dotenv multi-line parse 오류
T03 JSON 안의 Python 표현식 오류
T04 사내 custom header 지원
T05 endpoint path 오류로 HTTP 404
T06 corpus_rows 28 전달 오류
```

상세 문서:

```text
docs/status/M8_REAL_EMBEDDING_TROUBLESHOOTING.html
```

---

## 9. 구현 위치

```text
src/jira_collector/embedding/
├─ corpus.py
├─ contract.py
├─ client.py
├─ config.py
├─ artifact.py
├─ runner.py
└─ validation.py

tools/jira_knowledge/
├─ export_embedding_corpus.py
├─ embed_bge_m3.py
├─ validate_m8_embedding_artifact.py
└─ inspect_m8_embedding_similarity.py
```

Synthetic/unit/documentation regression tests: **CI PASS**

---

## 10. M8 Final Gate

```text
[x] active accepted corpus = 285
[x] Knowledge Item = Embedding Unit
[x] baseline no-chunk / statement_v1
[x] deterministic ec_ / emb_
[x] OpenAI-compatible BGE-M3 adapter
[x] custom header runtime support
[x] batch <= 64
[x] full real embedding = 285
[x] batch_count = 5
[x] dimension = 1024
[x] unique ki_ = 285
[x] unique emb_ = 285
[x] mapping failure = 0
[x] identity failure = 0
[x] invalid vector = 0
[x] atomic publish verified
[x] semantic quality sanity PASS
[x] troubleshooting documented

M8 = DONE / PASS
```

---

## 11. M9와의 경계

```text
M8 output
→ validated embedding artifact
→ deterministic emb_ ↔ ki_ mapping

M9 NEXT
→ FAISS index 설계
→ active Retrieval
→ Top-k / mapping / search sanity
```

**M8에서는 FAISS를 구현하지 않았다.** M9는 먼저 설계 문서와 Gate를 확정한 뒤 구현한다.
