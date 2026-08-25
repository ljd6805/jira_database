# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-25  
현재 단계: **M7 · SQLite Materialization — IMPLEMENTED / REAL-RUN VALIDATION PENDING**

## 1. 문서 목적

이 문서는 Jira 원본에서 검색 가능한 업무지식 시스템과 MCP까지 이어지는 **전체 데이터 계층, identity, lifecycle, 책임 경계**를 설명하는 Current Source of Truth입니다.

현재 진행 상태:

```text
M0  Jira 수집 · ANALYSIS 정규화          DONE
M1  Issue Knowledge Input              DONE
M2  Knowledge Schema · Skill           DONE
M3  Quality Loop                       DONE
M4  실제 Jira Knowledge Pilot          DONE
M5  Knowledge / Review Profiling       DONE
M6  DB Logical Schema                  DONE
M7  SQLite Materialization             CURRENT · IMPLEMENTED
                                          real 30-issue validation pending
M8  Chunk · BGE-M3                     BLOCKED
M9  FAISS · Active Retrieval
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
SQLite Materialization                 M7
    ├─ deterministic ID
    ├─ Generation / Attempt history
    ├─ Active / Historical state
    └─ Evidence round-trip integrity
            ↓
Chunk + BGE-M3                         M8
            ↓
FAISS + Active Retrieval               M9
            ↓
Evidence Builder + MCP                 M10
```

---

## 2. 핵심 불변 원칙

### 2.1 RAW가 Source of Truth

```text
RAW → ANALYSIS → KNOWLEDGE INPUT → KNOWLEDGE → DB → VECTOR
```

뒤 계층은 모두 앞 계층에서 다시 만들 수 있는 파생물이어야 합니다.

### 2.2 Deterministic processing과 LLM interpretation 분리

LLM이 개입하지 않는 경계:

```text
Jira → RAW → ANALYSIS → KNOWLEDGE INPUT
```

LLM 의미 해석:

```text
KNOWLEDGE INPUT → KNOWLEDGE
```

Validator, 집계, Profiling, DB materialization, Evidence resolver는 deterministic Python/SQLite 책임입니다.

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

### 2.4 Issue identity와 Version을 분리한다

```text
jira_id
= authoritative Jira identity

issue_key
= human-readable locator
= 변경 가능
```

Issue 의미 상태는 Knowledge Input `source_hash`로 Versioning합니다.

```text
same source_hash
→ existing issue_version

different source_hash
→ new issue_version
```

Run이 바뀌었다는 이유만으로 Version을 복제하지 않습니다.

### 2.5 Generation과 Attempt를 분리한다

```text
Issue Version
└── Knowledge Generation
    ├── Attempt 1
    ├── Attempt 2
    └── Attempt N
```

Generation은 **Issue Version + Knowledge Contract의 retry lineage**, Attempt는 실제 생성/재생성 회차입니다.

### 2.6 History Storage와 Active Retrieval을 분리한다

```text
[DB]
Current + Historical Version/Generation/Attempt 보존

[기본 RAG / FAISS]
active Generation의 accepted Attempt만

[History Retrieval]
감사 · 재현 · 변화 분석 · temporal query
```

### 2.7 문서는 구현과 같이 움직인다

Milestone 상태, Entity/Cardinality, ID 계약이 바뀌면 Current Source of Truth를 같은 작업 단위에서 갱신합니다.

기준: `docs/DOCUMENTATION_POLICY.md`

---

## 3. [RAW] 계층 · M0

경로:

```text
data/raw/runs/<run_id>/...
```

역할:

- Jira API 응답 보존
- 재파싱/재검증 기준
- read-only 사실 계층
- SHA-256 무결성
- Run별 source snapshot

핵심 운영 제약:

```text
Jira API requests_per_minute = 20
max_concurrency = 1
```

Comment는 embedded response에 의존하지 않고 전용 API에서 전체 pagination 수집합니다.

---

## 4. [ANALYSIS] 계층 · M0

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

주요 처리:

- HTML → text
- 타입 검증
- Comment sequence
- Relationship canonicalization
- Attachment metadata
- Custom Field Catalog / Value 분리
- 개인정보 불필요 복제 최소화
- `source_path` 유지

실환경 기준:

```text
Issue                         30
Comment                      278
Attachment                    79
Canonical Relationship         6
Custom Field Catalog         220
Custom Field Value           447
```

---

## 5. [KNOWLEDGE INPUT] 계층 · M1

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

`source_hash`는 다음 의미 데이터의 canonical SHA-256입니다.

```text
issue + comments + attachments + relationships + custom_fields
```

생성시각과 경로 정보는 제외합니다.

---

## 6. [KNOWLEDGE] / [REVIEW] · M2~M4

Knowledge:

```text
data/knowledge/runs/<run_id>/issues/<ISSUE_KEY>.json
```

Review:

```text
data/knowledge/runs/<run_id>/reviews/<ISSUE_KEY>.review.attempt<N>.json
```

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
Human Validation 5/5
```

---

## 7. M5 Profiling

실제 DB 설계 근거:

```text
Knowledge Item               285
Issue당 item mean            9.5
Statement p95              206.4 chars
Evidence Ref                 503
Evidence / item mean        1.76
Comment Evidence           79.92%
Review JSON                   37
```

이 수치를 하드 컬럼 상한으로 쓰지는 않습니다.

---

## 8. M6 최종 Logical Schema

M6-01~03의 최종 구조:

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

M6-01 초기에 검토했던 `knowledge_generation → knowledge_item` 직접 연결은 **M6-02에서 superseded**되었습니다.
현재 authoritative 구조는 반드시 `generation → attempt → item/review`입니다.

---

## 9. M6-02 Deterministic ID

ID ladder:

```text
jira_id
  ↓
issue_version_id           iv_
  = H(jira_id, source_hash)

knowledge_contract_hash    kc_
  = H(knowledge_schema_version,
      skill_version,
      runtime_version,
      model_profile)

knowledge_generation_id    kg_
  = H(issue_version_id, knowledge_contract_hash)

knowledge_attempt_id       ka_
  = H(knowledge_generation_id, attempt_no)

knowledge_item_id          ki_
  = H(knowledge_attempt_id, category, ordinal)

knowledge_evidence_id      ke_
  = H(knowledge_item_id, ordinal, exact evidence_ref)
```

공통 규칙:

```text
id_schema_version=1
kind 포함
canonical JSON UTF-8
sort_keys=true
separators=(",", ":")
SHA-256 full lowercase 64 hex
```

Timestamp는 logical ID material이 아닙니다.

중요:

```text
Attempt 1 ≠ Attempt 2 ≠ Attempt 3
```

`attempt_no`가 `knowledge_attempt_id`에 들어가므로 generation 내부 재생성 회차 identity가 유실되지 않습니다.

---

## 10. M7 SQLite Materialization

현재 구현 위치:

```text
src/jira_collector/knowledge_db/
├─ ids.py
├─ schema.py
├─ loader.py
├─ evidence.py
└─ models.py
```

실행:

```text
tools/jira_knowledge/materialize_knowledge_db.py
```

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

### Active constraint

Issue마다 active Generation은 최대 1개입니다.

```sql
CREATE UNIQUE INDEX ...
ON knowledge_generation(jira_id)
WHERE state = 'active';
```

### Legacy failed Attempt

현재 M4 artifact는 failed Attempt 당시 Knowledge body를 보존하지 않았습니다.

```text
failed Attempt
→ attempt/review/finding 저장
→ content_available=false

accepted final Attempt
→ item/evidence 저장
→ content_available=true
```

없는 과거 Knowledge는 추정하지 않습니다.

---

## 11. Evidence round-trip

Accepted Attempt의 Evidence는 모두 resolver를 통과해야 합니다.

```text
summary
→ issue_version.summary

description
→ issue_version.description

comment:<id>
→ comment(run_id, issue_key, comment_id)

attachment:<id>
→ attachment(run_id, attachment_id)
→ owner issue 확인

relationship:<id>
→ relationship(run_id, relationship_id)
→ source/target endpoint 확인

custom_field:<id>
→ custom_field_value(run_id, issue_key, field_id)
```

Resolver 실패 하나라도 있으면 transaction 전체를 rollback합니다.

---

## 12. M7 자동 검증 완료 범위

Synthetic integration test + GitHub Actions에서 확인:

```text
same Run 2회 materialize
→ duplicate 없음

Attempt history
→ failed Attempt content unavailable
→ accepted Attempt content available

6 Evidence types
→ 모두 round-trip

broken Evidence
→ integrity failure + rollback

active Generation 2개
→ SQLite IntegrityError

historical + active
→ 허용
```

따라서 M7 코드는 구현됐지만 **실제 30건 Gate는 아직 닫지 않았습니다.**

---

## 13. M7 Real-run Gate

대상:

```text
run_id = 20260804T043628Z
```

기대 regression count:

```text
Issue               30
Generation          30
Attempt             37
Knowledge Item     285
Evidence            503
Review               37
```

필수 확인:

```text
동일 명령 2회 실행 후 row count 불변
active Generation = 30
review_required = 0
Evidence resolver failures = 0
```

이 검증 전에는 M8로 이동하지 않습니다.

---

## 14. M8~M10

M7 Gate 이후:

```text
M8
Knowledge Item을 기본 embedding unit 후보로 검증
→ 필요할 때만 Chunk 추가
→ BGE-M3

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

M10이 Functional MVP 완료선입니다.

---

## 15. Phase 2 · M11~M16

```text
M11 Incremental Jira Sync
M12 Pipeline Orchestration
M13 Incremental Rebuild
M14 Recovery / Atomic Publish / Rollback
M15 Observability
M16 Production Lifecycle Gate
```

다중 Run chronology와 증분 운영은 M7에서 과설계하지 않고 M11~M14에서 구현합니다.

---

## 16. Current Source of Truth

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/architecture/jira_data_relationship_map.*
```

설계/구현 계약:

```text
docs/DB_LOGICAL_SCHEMA.md
docs/M6_DECISION_LOG.md
docs/status/M6_DB_LOGICAL_SCHEMA_COMPLETION.md
docs/M7_SQLITE_MATERIALIZATION.md
```

문서 유지 규칙:

```text
docs/DOCUMENTATION_POLICY.md
```
