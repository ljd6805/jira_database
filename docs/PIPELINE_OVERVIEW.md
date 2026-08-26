# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-26  
현재 단계: **M8 · Embedding Unit / Chunk + BGE-M3 — M8-01 PASS / M8-02 IMPLEMENTED / M8-03 REAL API NEXT**

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
Active Accepted Corpus                 M8-01 PASS
    ↓
Embedding Contract / Adapter           M8-02 IMPLEMENTED
    ↓
Real BGE-M3 Validation                 M8-03 CURRENT
    ↓
FAISS + Active Retrieval               M9 PLAN
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

`knowledge_attempt_id(ka_)`는 `knowledge_generation_id + attempt_no`로 결정되며 실제 1차/2차/3차 재생성 회차 identity를 보존한다.

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

Source:

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

## 6. M8-02 · Embedding Contract / Adapter — IMPLEMENTED

Contract:

```text
embedding_contract_version = 0.1
model                       = BAAI/bge-m3
model_profile               = runtime supplied
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
OpenAI-compatible request
{ model, input[] }

response data[].index
→ request input 위치와 다시 연결
```

Batch:

```text
max = 64
285 → 64 + 64 + 64 + 64 + 29
→ 5 requests
```

Validation:

```text
index 누락/중복/범위 오류 차단
모든 vector dimension = 1024
```

Retry:

```text
retry    network / timeout / 429 / 500 / 502 / 503 / 504
no retry request/auth 오류 / schema 오류 / index 오류 / dimension 오류
```

Publish:

```text
모든 batch 성공
→ temp JSONL
→ atomic replace
→ final artifact

중간 실패
→ final artifact publish 금지
```

구현:

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

GitHub Actions pytest: **PASS**

## 7. M8-03 · Real Embedding Gate — CURRENT

Runtime secret/config:

```text
.env
BGE_M3_ENDPOINT=<사내 OpenAI-compatible embeddings endpoint>
BGE_M3_API_KEY=<필요한 경우>
```

일반 설정은 `config/settings.yaml`의 `embedding:` 블록에서 관리한다.

실행:

```powershell
python tools/jira_knowledge/embed_bge_m3.py --corpus data/embedding/runs/20260804T043628Z/corpus.statement_v1.jsonl --output data/embedding/runs/20260804T043628Z/embeddings.statement_v1.bge_m3.jsonl --expected-count 285
```

Gate:

```text
[ ] corpus_rows = 285
[ ] embedding_rows = 285
[ ] batch_count = 5
[ ] embedding_dimension = 1024
[ ] emb_ ↔ ki_ mapping 무결성
[ ] 동일 input/contract 재실행 identity 재현
[ ] 작은 quality sanity check
```

## 8. M9와의 경계

**M8에서는 FAISS를 구현하지 않는다.**

```text
M8
→ validated embedding artifact
→ deterministic emb_ ↔ ki_ mapping

M9
→ FAISS index
→ active Retrieval
→ Top-k
```

M8 Real Embedding Gate가 끝나기 전에는 M9로 이동하지 않는다.

## 9. Current Source of Truth

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/architecture/jira_data_relationship_map.*
```

M8 contract:

```text
docs/M8_EMBEDDING_CHUNK_BGE_M3.md
docs/M8_DECISION_LOG.md
docs/status/M8_EMBEDDING_CHUNK_BGE_M3.html
```
