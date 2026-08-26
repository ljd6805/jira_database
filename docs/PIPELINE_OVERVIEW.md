# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-26  
현재 단계: **M8 · Embedding Unit / Chunk + BGE-M3 — M8-01 CORPUS IMPLEMENTED / REAL DB VALIDATION PENDING**

## 1. 문서 목적

이 문서는 Jira 원본에서 검색 가능한 업무지식 시스템과 MCP까지 이어지는 **전체 데이터 계층, identity, lifecycle, 책임 경계**를 설명하는 Current Source of Truth다.

현재 진행 상태:

```text
M0  Jira 수집 · ANALYSIS 정규화          DONE
M1  Issue Knowledge Input              DONE
M2  Knowledge Schema · Skill           DONE
M3  Quality Loop                       DONE
M4  실제 Jira Knowledge Pilot          DONE
M5  Knowledge / Review Profiling       DONE
M6  DB Logical Schema                  DONE
M7  SQLite Materialization             DONE · REAL-RUN PASS
M8  Embedding Unit / Chunk · BGE-M3    CURRENT
    └─ M8-01 corpus exporter           IMPLEMENTED
M9  FAISS · Active Retrieval           PLAN
M10 Evidence Builder · MCP             Functional MVP Gate
```

전체 흐름:

```text
Jira REST API
    ↓
[RAW]                                  M0
    ↓ deterministic parser/exporter
[ANALYSIS]                             M0
    ↓ deterministic issue join
[KNOWLEDGE INPUT]                      M1
    ↓ Worker + Skill
[KNOWLEDGE]                            M2~M4
    ├─ Python Validator
    └─ [REVIEW] Attempt history        M3~M4
            ↓
Knowledge / Review Profiling           M5
            ↓
Logical Identity / Version Model       M6
            ↓
SQLite Materialization                 M7 · DONE
    ├─ deterministic ID
    ├─ Generation / Attempt history
    ├─ Active / Historical state
    └─ Evidence round-trip integrity
            ↓
Active Accepted Corpus                 M8-01 · IMPLEMENTED
    ├─ Knowledge Item 1 = Unit 1
    ├─ statement_v1
    ├─ deterministic order/hash
    └─ JSONL corpus
            ↓
BGE-M3 Embedding Contract              M8-02
            ↓
Real Embedding Validation              M8-03
            ↓
FAISS + Active Retrieval               M9
            ↓
Evidence Builder + MCP                 M10
```

---

## 2. 핵심 불변 원칙

### 2.1 RAW가 Source of Truth

```text
RAW → ANALYSIS → KNOWLEDGE INPUT → KNOWLEDGE → DB → EMBEDDING → VECTOR
```

뒤 계층은 모두 앞 계층에서 다시 만들 수 있는 파생물이어야 한다.

### 2.2 Deterministic processing과 LLM interpretation 분리

LLM 의미 해석:

```text
KNOWLEDGE INPUT → KNOWLEDGE
```

그 외의 Validator, 집계, Profiling, DB materialization, Evidence resolver, corpus export, embedding orchestration 구조 검증은 deterministic code 책임이다.

### 2.3 History Storage와 Active Retrieval 분리

```text
DB
→ Current + Historical Version/Generation/Attempt 보존

기본 Retrieval / Embedding corpus
→ active Generation의 accepted Attempt만
```

Historical/candidate/review_required는 기본 corpus에 섞지 않는다.

### 2.4 Identity 계층을 섞지 않는다

Knowledge identity:

```text
jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_
```

`knowledge_attempt_id(ka_)`는 `knowledge_generation_id + attempt_no`로 결정되며 1차/2차/3차 재생성 회차 identity를 보존한다.

Embedding/Vector identity는 별도 계층이며 반드시 `knowledge_item_id`로 역참조 가능해야 한다.

```text
FAISS position ≠ Knowledge identity
```

### 2.5 Historical drift는 원본을 고쳐 쓰지 않는다

```text
historical JSON 수정 X
DB contract 완화 X
compatibility layer로 history 보존
future validator 강화
```

### 2.6 문서는 구현과 같이 움직인다

기준: `docs/DOCUMENTATION_POLICY.md`

---

## 3. M0~M5 데이터 근거

실환경 aggregate:

```text
Issue                         30
Comment                      278
Attachment metadata           79
Canonical Relationship         6
Custom Field Catalog         220
Custom Field Value           447

Knowledge Item               285
Statement mean             114.01 chars
Statement p95              206.4 chars
Statement max                447 chars
M5 Raw Evidence Ref          503
Review JSON                   37
```

이 분포는 M8에서 `Knowledge Item`을 기본 embedding unit으로 선택한 실측 근거다.

---

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

Source entities:

```text
comment
attachment
relationship
custom_field_catalog
custom_field_value
```

Authoritative 구조는 `generation → attempt → item/review`다.

---

## 5. M7 SQLite Materialization · DONE

최종 Gate:

```text
M5 raw expected
Issue              30
Generation         30
Attempt            37
Knowledge Item    285
Evidence raw      503
Review             37

M7 canonical DB
Issue              30
Generation         30
Attempt            37
Knowledge Item    285
Evidence           502
Review             37

Active Generation  30
Review Required      0
Evidence Failure     0
FK Failure           0
Integrity           OK
Idempotent          true
Failures            []
```

판정:

```text
M7_REAL_RUN = PASS
M7 = DONE
```

M5의 raw 503과 M7 canonical 502의 차이는 historical duplicate Evidence 1회다. 원본은 수정하지 않고 M6 `UNIQUE(knowledge_item_id, evidence_ref)` 계약을 유지한다.

실제 Jira 식별자와 본문은 공개 문서에 기록하지 않는다.

---

## 6. M8-01 · Active Accepted Corpus

### 6.1 Source Query

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

### 6.2 Embedding Unit

M8 Pilot baseline:

```text
Knowledge Item 1개
→ Embedding Unit 1개
```

현재 285 Item은 statement max 447자 수준이라 모든 Item을 선제 Chunk하지 않는다.

Chunk는 다음 근거가 생길 때만 추가한다.

- BGE-M3 tokenizer 기준 길이 문제
- 하나의 statement에 여러 검색 의도 혼재
- Retrieval sanity test에서 분할이 일관되게 우수

### 6.3 Text Profile

Baseline:

```text
text_profile = statement_v1
embedding_text = knowledge_item.statement.strip()
embedding_text_hash = SHA-256(UTF-8 embedding_text)
```

후속 실험 후보:

```text
category_statement_v1
issue_summary_category_statement_v1
```

### 6.4 Corpus Artifact v0.1

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

Vector는 아직 넣지 않는다.

### 6.5 구현

```text
src/jira_collector/embedding/
├─ __init__.py
└─ corpus.py

tools/jira_knowledge/export_embedding_corpus.py

tests/embedding/test_corpus.py
```

Synthetic filtering/order/hash test는 CI PASS다.

현재 남은 M8-01 Gate:

```text
실제 M7 SQLite
→ corpus export
→ corpus_rows = 285 확인
```

---

## 7. M8-02 · BGE-M3 Contract

M8-01 real DB Gate 통과 후 시작한다.

현재 확인된 사내 API 제약:

```text
Model              BAAI/bge-m3
Serving            TEI / OpenAI-compatible embeddings API
Request max batch  64
Dense dimension    1024
```

M8-02에서 결정할 것:

```text
embedding_contract_version
embedding_id
model profile
request/response mapping
batch partition
retry / partial failure
1024-dim validation
vector artifact 저장 형식
```

축소 dimension 지원 여부는 확인 전까지 미확정으로 둔다.

---

## 8. M8-03 · Real Embedding Gate

```text
[ ] 실제 285 corpus embedding 성공
[ ] batch <= 64
[ ] 모든 output dimension = 1024
[ ] Knowledge Item ↔ Embedding mapping 무결성
[ ] 같은 input/contract 재실행 identity 재현
[ ] 작은 quality sanity check
[ ] 문서/HTML 동기화
```

---

## 9. M9와의 경계

```text
M8
→ 검증된 embedding artifact
→ Knowledge mapping
→ model/contract metadata

M9
→ FAISS index
→ active Retrieval
→ Top-k
```

M8에서는 FAISS를 구현하지 않는다.

---

## 10. Current Source of Truth

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/architecture/jira_data_relationship_map.*
```

M8 current contract:

```text
docs/M8_EMBEDDING_CHUNK_BGE_M3.md
docs/M8_DECISION_LOG.md
docs/status/M8_EMBEDDING_CHUNK_BGE_M3.html
```

M6/M7 근거:

```text
docs/DB_LOGICAL_SCHEMA.md
docs/M6_DECISION_LOG.md
docs/M7_SQLITE_MATERIALIZATION.md
docs/M7_REAL_RUN_LOG.md
docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md
```
