# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-26  
현재 단계: **M8 · Embedding Unit / Chunk + BGE-M3 — CURRENT / READY TO START**

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
Embedding Unit / Chunk + BGE-M3        M8 · CURRENT
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

LLM이 개입하지 않는 경계:

```text
Jira → RAW → ANALYSIS → KNOWLEDGE INPUT
```

LLM 의미 해석:

```text
KNOWLEDGE INPUT → KNOWLEDGE
```

Validator, 집계, Profiling, DB materialization, Evidence resolver, embedding orchestration의 구조 검증은 deterministic code 책임이다.

### 2.3 Knowledge는 사실 원장이 아니다

```text
Knowledge Item
    ↓ exact evidence_ref
Knowledge Evidence
    ↓
Issue Version / Source Entity
    ↓ source_path
ANALYSIS / RAW
```

### 2.4 Identity와 Version 분리

```text
jira_id
= authoritative Jira identity

issue_key
= human-readable locator
= 변경 가능
```

Issue 의미 상태는 Knowledge Input `source_hash`로 Versioning한다.

```text
same source_hash
→ existing issue_version

different source_hash
→ new issue_version
```

Run이 바뀌었다는 이유만으로 Version을 복제하지 않는다.

### 2.5 Generation과 Attempt 분리

```text
Issue Version
└── Knowledge Generation
    ├── Attempt 1
    ├── Attempt 2
    └── Attempt N
```

Generation은 **Issue Version + Knowledge Contract의 retry lineage**, Attempt는 실제 생성/재생성 회차다.

### 2.6 History Storage와 Active Retrieval 분리

```text
DB
→ Current + Historical Version/Generation/Attempt 보존

기본 Retrieval
→ active Generation의 accepted Attempt만

History Retrieval
→ 감사 · 재현 · 변화 분석 · temporal query
```

### 2.7 Historical drift는 원본을 고쳐 쓰지 않는다

실데이터 Gate에서 과거 artifact가 계약을 벗어난 경우:

```text
historical JSON 수정 X
DB contract 완화 X
compatibility layer로 history 보존
future validator 강화
```

### 2.8 문서는 구현과 같이 움직인다

Milestone 상태, Entity/Cardinality, ID 계약이 바뀌면 Current Source of Truth를 같은 작업 단위에서 갱신한다.

기준: `docs/DOCUMENTATION_POLICY.md`

---

## 3. RAW / ANALYSIS · M0

RAW:

```text
data/raw/runs/<run_id>/...
```

ANALYSIS:

```text
data/analysis/<run_id>/
├─ issues.jsonl
├─ comments.jsonl
├─ attachments.jsonl
├─ issue_relationships.jsonl
├─ custom_field_catalog.jsonl
├─ custom_field_values.jsonl
└─ summary.json
```

실환경 aggregate:

```text
Issue                         30
Comment                      278
Attachment metadata           79
Canonical Relationship         6
Custom Field Catalog         220
Custom Field Value           447
```

---

## 4. KNOWLEDGE INPUT · M1

```text
data/knowledge_input/runs/<run_id>/
├─ issues/<ISSUE_KEY>.json
├─ package_warnings.jsonl
└─ manifest.json
```

한 Issue package:

```text
issue
comments[]
attachments[]
relationships[]
custom_fields[]
counts
source_hash
```

`source_hash`는 의미 데이터 기반 canonical SHA-256이며 Issue Version 변경 판단 기준이다.

---

## 5. KNOWLEDGE / REVIEW · M2~M4

Knowledge Schema v0.1:

```text
issue_summary
problem_or_goal[]
key_findings[]
actions_and_decisions[]
outcomes[]
open_items[]
```

각 item:

```text
statement
evidence_refs[]
```

Quality Loop:

```text
Orchestrator
  ↓
Fresh Worker
  ↓
Validator
  ↓
Fresh Reviewer
  ↓
PASS / REGENERATE
  ↓
max 3 Attempts
```

실제 M4 결과:

```text
30/30 final PASS
1차 PASS 24
2차 PASS 5
3차 PASS 1
Review files 37
```

---

## 6. M5 Profiling

```text
Knowledge Item               285
Issue당 item mean            9.5
Statement p95              206.4 chars
Raw Evidence Ref             503
Evidence / item mean        1.76
Review JSON                   37
```

M5 수치는 historical artifact의 raw 관찰값이다.

---

## 7. M6 Logical Schema

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

Authoritative 구조는 반드시 `generation → attempt → item/review`다.

---

## 8. Deterministic ID

```text
jira_id
  ↓
issue_version_id           iv_
  = H(jira_id, source_hash)

knowledge_contract_hash    kc_
  = H(schema, skill, runtime, model_profile)

knowledge_generation_id    kg_
  = H(issue_version_id, knowledge_contract_hash)

knowledge_attempt_id       ka_
  = H(knowledge_generation_id, attempt_no)

knowledge_item_id          ki_
  = H(knowledge_attempt_id, category, ordinal)

knowledge_evidence_id      ke_
  = H(knowledge_item_id, ordinal, exact evidence_ref)
```

---

## 9. M7 SQLite Materialization · DONE

SQLite table:

```text
pipeline_run
issue
issue_version
issue_version_observation
comment
attachment
relationship
custom_field_catalog
custom_field_value
knowledge_generation
knowledge_attempt
knowledge_item
knowledge_evidence
knowledge_review
review_finding
```

Active constraint:

```text
Issue당 active Generation 최대 1개
→ SQLite partial UNIQUE
```

Evidence resolver:

```text
summary
description
comment:<id>
attachment:<id>
relationship:<id>
custom_field:<id>
```

Accepted Attempt의 모든 Evidence는 source까지 round-trip해야 하며 실패 시 transaction을 rollback한다.

### 9.1 Final Real-run Gate

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

### 9.2 raw 503 vs canonical 502

실데이터 30건 중 한 Item에서 동일 Evidence ref가 한 번 중복됐다.

```text
M5 raw count       503
M7 canonical rows 502
Duplicate refs       1
Duplicate items      1
```

Historical JSON은 수정하지 않고 첫 occurrence만 DB에 materialize한다. M6의 `UNIQUE(knowledge_item_id, evidence_ref)` 계약은 유지한다.

### 9.3 Review historical compatibility

Review Schema v0.3의 `critical_issues: string[]` 계약과 다른 object 형태가 historical Review 2개에서 발견됐다. 원본은 수정하지 않고 compatibility layer로 `review_finding`에 보존한다.

실제 Jira 식별자와 본문은 공개 문서에 기록하지 않는다.

---

## 10. M8 · CURRENT

M8의 입력은 M7 SQLite의 **active accepted Knowledge**다.

M8 책임:

```text
1. Embedding unit contract 확정
2. Knowledge Item을 기본 embedding unit 후보로 검증
3. Chunk가 필요한 조건 정의
4. BGE-M3 API contract 고정
5. Embedding 생성 / 저장 구조 결정
6. 실데이터 소규모 embedding 검증
7. M8 Gate 정의 / 통과
```

BGE-M3 현재 제약:

```text
OpenAI-compatible embeddings API
model = BAAI/bge-m3
request max batch = 64
dense dimension = 1024
```

축소 dimension 지원 여부는 아직 확정하지 않는다.

M8에서는 FAISS를 구현하지 않는다.

---

## 11. M9~M10

```text
M9
FAISS
→ active accepted corpus만 index
→ Top-k Retrieval

M10
Evidence Builder + MCP
→ 질문
→ retrieval
→ deterministic Evidence
→ Agent answer
```

M10이 Functional MVP 완료선이다.

---

## 12. Phase 2 · M11~M16

```text
M11 Incremental Jira Sync
M12 Pipeline Orchestration
M13 Incremental Rebuild
M14 Recovery / Atomic Publish / Rollback
M15 Observability
M16 Production Lifecycle Gate
```

---

## 13. Current Source of Truth

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/architecture/jira_data_relationship_map.*
```

M6/M7 계약 및 완료 근거:

```text
docs/DB_LOGICAL_SCHEMA.md
docs/M6_DECISION_LOG.md
docs/M7_SQLITE_MATERIALIZATION.md
docs/M7_REAL_RUN_LOG.md
docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md
```
