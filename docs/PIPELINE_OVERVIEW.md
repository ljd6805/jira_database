# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-26  
현재 단계: **M9 · FAISS + Active Retrieval — M9-01 DESIGN FROZEN / M9-02 IMPLEMENTED / M9-03 REAL BUILD PASS · REBUILD NEXT**

## 1. 전체 흐름

```text
Jira REST API
    ↓
[RAW]                                  M0 DONE
    ↓
[ANALYSIS]                             M0 DONE
    ↓
[KNOWLEDGE INPUT]                      M1 DONE
    ↓
[KNOWLEDGE] + [REVIEW]                M2~M4 DONE
    ↓
Knowledge / Review Profiling           M5 DONE
    ↓
Logical Identity / Version Model       M6 DONE
    ↓
SQLite Materialization                 M7 DONE · REAL-RUN PASS
    ↓
Active Accepted Corpus                 M8-01 DONE · PASS
    ↓
Embedding Contract / Adapter           M8-02 DONE · PASS
    ↓
Real BGE-M3 Validation                 M8-03 DONE · PASS
    ↓
Retrieval Contract                     M9-01 DESIGN FROZEN
    ↓
FAISS Build / Search                   M9-02 IMPLEMENTED · CI PASS
    ↓
Real Index / Query Validation          M9-03 CURRENT · REAL BUILD PASS
    ↓
Evidence Builder + MCP                 M10 Functional MVP Gate
```

## 2. 핵심 불변 원칙

### RAW가 Source of Truth

```text
RAW → ANALYSIS → KNOWLEDGE INPUT → KNOWLEDGE → DB → EMBEDDING → RETRIEVAL
```

뒤 계층은 앞 계층에서 다시 만들 수 있는 파생물이어야 한다.

### History와 Active Retrieval 분리

```text
DB
→ Current + Historical Version/Generation/Attempt 보존

기본 Retrieval / Embedding corpus
→ active Generation의 accepted Attempt만
```

### Knowledge identity 보존

```text
jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_
```

`knowledge_attempt_id(ka_)`는 `knowledge_generation_id + attempt_no`로 결정되며 실제 재생성 회차 identity를 보존한다.

Embedding/FAISS는 별도 artifact 계층이다.

```text
Embedding Contract   ec_
Embedding Artifact   emb_
Retrieval Contract   rc_
FAISS Index Artifact fi_
```

```text
FAISS position ≠ embedding_id ≠ knowledge_item_id
```

M9에서도 최종 역참조는 반드시:

```text
faiss_position
→ embedding_id (emb_)
→ knowledge_item_id (ki_)
→ M10 Evidence resolve
```

경로를 유지한다.

## 3. Pilot 근거

```text
Issue                         30
Knowledge Item               285
Statement mean             114.01 chars
Statement p95              206.4 chars
Statement max                447 chars
M5 Raw Evidence Ref          503
M7 Canonical Evidence Row    502
Review Attempt                37
M8 Validated Embedding       285
Embedding dimension         1024
M9 FAISS vector_count        285
```

M8는 **Knowledge Item 1개 = Embedding Unit 1개**, 기본 Chunk 없음으로 완료했다.

## 4. M6/M7 Authoritative DB

```text
pipeline_run
    │
    └── issue_version_observation
                │
issue ── 1:N issue_version
                │
                └── 1:N knowledge_generation
                         │
                         └── 1:N knowledge_attempt
                                  ├── 1:N knowledge_item
                                  │        └── 1:N knowledge_evidence
                                  └── 0..1 knowledge_review
                                           └── 1:N review_finding
```

M7 Real-run:

```text
Issue / Generation      30 / 30
Attempt / Review        37 / 37
Knowledge Item         285
Evidence raw/canonical 503 / 502
Active Generation       30
Evidence Failure         0
FK Failure               0
Integrity               OK
Idempotent              true
```

```text
M7_REAL_RUN = PASS
```

## 5. M8 Embedding — DONE / PASS

### M8-01 · Corpus

```text
knowledge_generation.state = active
AND accepted_attempt_id IS NOT NULL
    ↓
accepted knowledge_attempt
AND content_available = 1
    ↓
knowledge_item
```

```text
M7 active accepted Knowledge Item 285
→ M8 corpus_rows: 285
```

### M8-02 · Contract / Adapter

```text
model              BAAI/bge-m3
model_profile      internal-bge-m3-unversioned
text_profile       statement_v1
dimension          1024
batch max          64
API                TEI / OpenAI-compatible
custom headers     runtime supported
```

### M8-03 · Real Gate

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

Artifact integrity:

```text
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

Semantic sanity:

```text
Sample 1 PASS
Sample 2 PASS · 매우 양호
Sample 3 PASS · dense semantic neighborhood 관찰
```

```text
M8 = DONE / PASS
```

## 6. M9-01 · Retrieval Contract — DESIGN FROZEN

현재 exact baseline:

```text
Index       IndexFlatIP
Metric      cosine similarity
Normalize   DB/query 모두 L2
Order       embedding_id ascending
Top-k       3
Threshold   none
Reranker    none
Update      full rebuild
Publish     index + mapping + manifest-last
```

Cosine은 FAISS에서:

```text
L2 normalize(database vector)
+ L2 normalize(query vector)
+ inner product search
```

로 구현한다.

Query:

```text
query_text_profile = raw_query_v1
query_text = user_query.strip()
model/profile/dimension = M8 source와 동일
```

### Scaling

`IndexFlatIP`는 영구 고정이 아니라 exact test oracle이다.

```text
Pilot → Flat exact
규모 증가 → latency / RAM / QPS / rebuild benchmark
필요 시 → HNSW / IVF benchmark
전환 판단 → recall@k + latency + memory
```

ANN으로 바뀌어도 `emb_ → ki_ → Evidence` 계약은 유지한다.

## 7. M9-02 · FAISS Build / Search — IMPLEMENTED / CI PASS

구현 구조:

```text
src/jira_collector/retrieval/
├─ contract.py
├─ source.py
├─ artifact.py
├─ validation.py
├─ search.py
└─ query.py

tools/jira_knowledge/
├─ build_faiss_index.py
├─ validate_m9_retrieval_artifact.py
└─ search_faiss.py
```

Artifact set:

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

Build:

```text
M8 corpus + embedding integrity re-validation
→ embedding_id ascending canonical sort
→ float32 copy
→ L2 normalize
→ IndexFlatIP.add
→ temp index / mapping
→ load + normalization validation
→ index / mapping replace
→ manifest LAST publish
```

Manifest는 다음을 보존한다.

```text
rc_ / fi_
source embedding SHA-256
source embedding contract hash
mapping SHA-256
FAISS binary SHA-256
FAISS version
vector_count / dimension
query profile / Top-k policy
```

Search loader는 manifest/hash/mapping Gate가 실패한 artifact를 거부한다.

Synthetic CI Gate:

```text
IndexFlatIP exact cosine search
canonical embedding_id order
L2 normalization
rc_ / fi_ deterministic identity
same source rebuild → same mapping / logical IDs
mapping corruption → hash/mapping failure
query model/profile/dimension mismatch → API 전 차단
```

```text
M9-02 = IMPLEMENTED / CI PASS
```

## 8. M9-03 · Real Index / Retrieval Gate — CURRENT

### First Real Build · PASS

실제 M8 Pilot 285 embeddings로 첫 FAISS build를 완료했다.

```text
validation: PASS
vector_count: 285
dimension: 1024
retrieval_contract_hash: rc_6b9fc7222abbf08ff5861fbb73ab31cc37a12cd78585313d05e2645e7603dd77
faiss_index_id: fi_b544c57a560cec99069be46b6ee8f2047841b522ddf81681d3cd6027baa65b2d
source_embedding_artifact_sha256: 45c363194defbb0e7095c32ecd462e749c943d4524ec7dd6acda093260abe2f8
mapping_sha256: 9e546845b97307d095dd1ff3ec3ab3e4262dcf9b0a1444cbcd4391e0837e947b
mapping_failure_count: 0
hash_failure_count: 0
normalization_failure_count: 0
```

### Rebuild Gate · NEXT

같은 M8 source + 같은 retrieval contract에서:

```text
[ ] same rc_
[ ] same fi_
[ ] same source embedding SHA-256
[ ] same mapping SHA-256
```

FAISS binary SHA는 같은 환경에서 동일하면 좋은 신호지만 logical identity의 필수 조건으로 두지 않는다.

### Real Query Gate · AFTER REBUILD

```text
[ ] same BGE-M3 query embedding
[ ] query L2 normalization
[ ] Top-3 exact cosine retrieval
[ ] emb_ ↔ ki_ mapping integrity
[ ] same query ranking reproducibility
[ ] representative query semantic sanity
[ ] dense-neighborhood case observation
```

## 9. M10과의 경계

M9 output은 candidate identity + score까지만 제공한다.

```text
rank
score
faiss_position
embedding_id
knowledge_item_id
category
```

M10에서:

```text
ki_ → Knowledge statement
ke_ → Evidence source
→ Evidence Builder
→ MCP
```

를 구현한다.

## 10. Current Source of Truth

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/architecture/jira_data_relationship_map.*
```

M8 final records:

```text
docs/M8_EMBEDDING_CHUNK_BGE_M3.md
docs/M8_DECISION_LOG.md
docs/M8_REAL_EMBEDDING_LOG.md
docs/status/M8_EMBEDDING_CHUNK_BGE_M3.html
docs/status/M8_REAL_EMBEDDING_TROUBLESHOOTING.html
```

M9 current records:

```text
docs/M9_FAISS_ACTIVE_RETRIEVAL.md
docs/M9_DECISION_LOG.md
docs/M9_REAL_RETRIEVAL_LOG.md
docs/status/M9_FAISS_ACTIVE_RETRIEVAL.html
```
