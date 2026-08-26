# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-26  
현재 단계: **M8 DONE / M9 NEXT · DESIGN NOT STARTED**

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
FAISS + Active Retrieval               M9 NEXT · DESIGN NOT STARTED
    ↓
Evidence Builder + MCP                 M10 Functional MVP Gate
```

## 2. 핵심 불변 원칙

### RAW가 Source of Truth

```text
RAW → ANALYSIS → KNOWLEDGE INPUT → KNOWLEDGE → DB → EMBEDDING → VECTOR
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

Embedding은 별도 artifact 계층이다.

```text
Embedding Contract  ec_
Embedding Artifact  emb_

emb_ = H(knowledge_item_id, embedding_text_hash, ec_)
```

```text
FAISS position ≠ embedding_id ≠ knowledge_item_id
```

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
```

이 분포를 근거로 M8 baseline은 **Knowledge Item 1개 = Embedding Unit 1개**, 기본 Chunk 없음으로 결정했다.

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

## 5. M8-01 · Active Accepted Corpus — PASS

```text
knowledge_generation.state = active
AND accepted_attempt_id IS NOT NULL
    ↓
accepted knowledge_attempt
AND content_available = 1
    ↓
knowledge_item
```

Baseline:

```text
Knowledge Item 1개 = Embedding Unit 1개
text_profile = statement_v1
embedding_text = statement.strip()
embedding_text_hash = SHA-256(UTF-8 text)
```

실데이터 Gate:

```text
M7 active accepted Knowledge Item 285
→ M8 corpus_rows: 285
```

**M8-01 PASS**

## 6. M8-02 · Embedding Contract / Adapter — PASS

Contract:

```text
embedding_contract_version = 0.1
model                       = BAAI/bge-m3
model_profile               = internal-bge-m3-unversioned
text_profile                = statement_v1
dimension                   = 1024
```

Identity:

```text
ec_ = deterministic Embedding Contract ID
emb_ = deterministic Embedding Artifact ID
```

API:

```text
TEI / OpenAI-compatible embeddings
Request max batch = 64
Dense dimension = 1024
Custom header runtime 지원
```

Batch:

```text
285 → 64 + 64 + 64 + 64 + 29
→ 5 requests
```

Response mapping:

```text
data[].index
→ request input 위치와 다시 연결
```

Failure / publish:

```text
network / timeout / 429 / 5xx → 제한 재시도
400 / 401 / 403 / 404        → 즉시 실패
schema / index / dim 오류     → 즉시 실패
모든 batch 성공               → atomic final publish
```

**M8-02 PASS**

## 7. M8-03 · Real Embedding Gate — PASS

Smoke:

```text
API call: PASS
vectors : 1
dimension: 1024
```

Full Pilot:

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

Artifact integrity:

```text
validation: PASS
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
Sample 1  PASS
Sample 2  PASS · 매우 양호
Sample 3  PASS · 후보 모두 의미상 타당
```

Sample 3의 Top-3 cosine score는 `0.5918 / 0.5908 / 0.5900`으로 margin이 작았다. 이는 embedding 실패가 아니라 dense semantic neighborhood 관찰로 기록한다.

M9에는 다음 설계 힌트를 넘긴다.

```text
Top-1 단독 확정 과신 금지
Top-k 후보군 유지 검토
Knowledge + Evidence 함께 사용
threshold / reranking은 실측 후 결정
```

```text
M8 = DONE / PASS
```

## 8. M9 · FAISS + Active Retrieval — NEXT

M9는 아직 구현하지 않았다.

M8 출력:

```text
validated embedding artifact
+ deterministic emb_ ↔ ki_ mapping
```

M9 설계 대상:

```text
FAISS index type
similarity metric / normalization
active-only index policy
embedding_id ↔ knowledge_item_id mapping
query embedding contract
Top-k baseline
index rebuild / reproducibility
retrieval sanity / quality Gate
```

**M9는 설계 문서를 먼저 확정한 뒤 구현한다.**

## 9. Current Source of Truth

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
