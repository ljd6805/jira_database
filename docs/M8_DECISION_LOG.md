# M8 Decision Log

기준일: 2026-08-26  
상태: **CLOSED / M8 DONE**

M8 · Embedding Unit / Chunk + BGE-M3 단계에서 합의한 결정과 실데이터 검증 결과를 보존한다.

---

## M8-01 · Active Accepted Corpus / Embedding Unit Baseline

상태: **PASS / DONE**

### 결정

M8 기본 corpus:

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

따라서 baseline에서는 Chunk를 사용하지 않는다. Chunk는 tokenizer 길이 문제, 복합 검색 의도, Retrieval 품질 개선 근거가 확인될 때만 추가 검토한다.

Baseline text:

```text
text_profile = statement_v1
embedding_text = knowledge_item.statement.strip()
embedding_text_hash = SHA-256(UTF-8 embedding_text)
```

Real DB Gate:

```text
corpus_schema_version: 0.1
text_profile: statement_v1
corpus_rows: 285
```

```text
M8-01 = PASS / DONE
```

---

## M8-02 · Deterministic Embedding Contract / BGE-M3 Adapter

상태: **PASS / DONE**

### Embedding identity

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

Deterministic ID:

```text
ec_ = H(contract version, text profile, model, model profile, dimension)
emb_ = H(knowledge_item_id, embedding_text_hash, ec_)
```

Endpoint URL, API key, custom header, vector 값, FAISS position은 logical identity에 넣지 않는다.

### API / batch

```text
Model              BAAI/bge-m3
Serving            TEI / OpenAI-compatible
Request max batch  64
Dense dimension    1024
Usage limit        200 requests/min
```

```text
285 → 64 + 64 + 64 + 64 + 29 → 5 requests
```

응답 배열의 물리 순서가 아니라 `data[].index`를 authoritative input mapping으로 사용한다.

### Custom header

사내 runtime의 custom HTTP header를 generic하게 지원한다.

```text
BGE_M3_ENDPOINT      required
BGE_M3_API_KEY       optional
BGE_M3_HEADERS_JSON  optional
```

Secret/header 값은 HTTP runtime에만 사용하고 identity/artifact/stdout/public docs에는 기록하지 않는다.

### Retry / failure

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

### Publish

```text
모든 batch 성공
→ validation
→ temp JSONL
→ atomic replace
→ final artifact

중간 batch 실패
→ final artifact publish 금지
```

Synthetic/unit test와 CI가 PASS했다.

```text
M8-02 = PASS / DONE
```

---

## M8-03 · Real BGE-M3 Gate

상태: **PASS / DONE**

### 1. Runtime preflight

```text
endpoint configured : true
api_key configured  : false
custom_headers      : 6
model               : BAAI/bge-m3
dimension           : 1024
```

### 2. 1-row smoke

```text
API call: PASS
vectors : 1
dimension: 1024
```

초기 HTTP 404는 endpoint path 설정 오류였으며 실제 embeddings route로 수정한 뒤 PASS했다.

### 3. Full Pilot embedding

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

### 4. Artifact integrity

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

따라서 `ki_ ↔ emb_`는 285:285로 1:1이고, deterministic identity와 lineage mapping 실패가 없다.

### 5. Semantic sanity

3개 샘플을 brute-force cosine similarity로 검토했다.

```text
Sample 1  PASS
Sample 2  PASS · 매우 양호
Sample 3  PASS
```

Sample 3 Top-3:

```text
0.5918 / 0.5908 / 0.5900
```

Top-3 margin은 작지만 후보 모두 의미상 타당했다. 이를 실패가 아니라 **dense semantic neighborhood**로 기록한다.

M9 설계 시 이 관찰을 다음처럼 사용한다.

```text
Top-1만 과신하지 않음
→ Top-k 후보군 유지 검토
→ Knowledge + Evidence를 함께 사용
→ threshold/reranking은 M9 이후 근거를 보고 결정
```

### 6. Troubleshooting 결정

실환경에서 확인한 문제를 별도 기록으로 보존한다.

```text
T01 legacy SQLite Viewer 오류
T02 dotenv multi-line parse 오류
T03 JSON 안의 Python 표현식 오류
T04 custom header 지원 필요
T05 endpoint path 404
T06 corpus count 전달 오류
```

상세:

```text
docs/M8_REAL_EMBEDDING_LOG.md
docs/status/M8_REAL_EMBEDDING_TROUBLESHOOTING.html
```

### Final Gate

```text
[x] corpus 285
[x] embedding 285
[x] 5 batches
[x] 1024 dimension
[x] unique ki_ 285
[x] unique emb_ 285
[x] mapping failure 0
[x] identity failure 0
[x] invalid vector 0
[x] atomic publish
[x] semantic sanity PASS
[x] troubleshooting documented

M8-03 = PASS / DONE
M8 = DONE
```

---

## M9로 넘기는 관찰사항

M9는 아직 구현 시작 전이다. 다음 내용은 M9 설계 입력으로 넘긴다.

```text
1. M8 validated embedding JSONL만 FAISS 입력으로 사용
2. FAISS position은 emb_ 또는 ki_ identity가 아님
3. emb_ ↔ ki_ mapping을 별도로 보존
4. active Retrieval만 기본 search 대상
5. Sample 3에서 Top-3 score margin이 작았으므로 Top-1 단독 확정은 피하는 방향 검토
6. Top-k / threshold / metric / normalization은 M9에서 실측 후 결정
```

**M8에서는 FAISS를 구현하지 않았다.**
