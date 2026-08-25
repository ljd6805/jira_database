# M6 DB Logical Schema

기준일: 2026-08-25  
상태: **M6 Gate PASS / Logical Design v0.3**

이 문서는 M5 실제 Profiling과 M6-01~03 의사결정을 바탕으로 Jira Knowledge DB의 최종 논리 모델을 정의한다.

> 이전 초안과 변경 이유는 `docs/M6_DECISION_LOG.md`에 보존한다. M6는 SQLite DDL을 작성하는 단계가 아니라 M7에서 구현할 논리 계약을 고정하는 단계다.

---

## 1. M6 목적

M6는 다음 질문에 답한다.

```text
무엇을 Entity로 저장하는가?
각 Entity의 authoritative identity는 무엇인가?
Jira 원문 변경과 단순 재수집을 어떻게 구분하는가?
Retry Attempt와 Review 이력을 어떻게 감사하는가?
Knowledge Item에서 Jira 원문까지 어떻게 round-trip 하는가?
현재 검색 대상과 Historical Knowledge를 어떻게 분리하는가?
```

M6가 고정하는 핵심 경계:

```text
History Storage ≠ Active Retrieval Corpus
Vector ID ≠ Knowledge Identity
Pipeline Run ≠ Issue Version
Knowledge Generation ≠ Retry Attempt
```

---

## 2. M5가 준 실제 근거

기준 Run: `20260804T043628Z`

```text
Issue                           30
Knowledge item                285
Issue당 item mean             9.5
Issue당 item p95              16.1
Issue당 item max              19
Statement p50                 104 chars
Statement p95                 206.4 chars
Statement max                 447 chars
Evidence refs                 503
Evidence/item mean            1.76
Evidence/item max             13
Comment Evidence              79.92%
Review files                  37
Final PASS                    30 / 30
```

설계 제약:

1. Issue → Knowledge Item은 1:N이다.
2. Knowledge Item → Evidence도 1:N이다.
3. Evidence의 약 80%가 Comment이므로 Comment round-trip이 핵심이다.
4. Knowledge 6 category를 별도 table로 나누지 않는다.
5. Empty category는 정상이다.
6. 현재 p95/max를 DB hard limit로 사용하지 않는다.
7. 모든 Review Attempt와 historical defect를 보존해야 한다.
8. Historical Knowledge는 DB에 남기되 기본 RAG corpus에는 섞지 않는다.

---

## 3. 기존 데이터 계약

### ANALYSIS

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

### KNOWLEDGE INPUT

```text
package_schema_version
run_id
project_key
issue_key
generated_at
source_hash
issue
comments[]
attachments[]
relationships[]
custom_fields[]
counts
```

`source_hash`는 이미 다음 canonical 의미 데이터를 기반으로 한 SHA-256이다.

```text
issue
comments
attachments
relationships
custom_fields
```

생성 시각과 source path는 hash에서 제외된다.

### KNOWLEDGE

```text
knowledge_schema_version
issue_key
issue_summary
problem_or_goal[]
key_findings[]
actions_and_decisions[]
outcomes[]
open_items[]
```

### REVIEW

```text
reviews/<ISSUE_KEY>.review.attempt<N>.json
```

현재 M4 Runtime은 최종 Knowledge 파일은 Issue당 하나만 남기고 Review는 Attempt별로 남긴다.

---

## 4. 최종 논리 구조

```text
Pipeline Run
   │
   └── Issue Version Observation ──────────────────┐
                                                   │
Issue                                              │
   │                                               │
   └── Issue Version ◀─────────────────────────────┘
          │
          └── Knowledge Generation
                 │
                 ├── Attempt 1
                 │     ├── Knowledge Item
                 │     │      └── Evidence
                 │     └── Review
                 │            └── Review Finding
                 │
                 ├── Attempt 2
                 │     ├── Knowledge Item
                 │     └── Review
                 │
                 └── Attempt N
                       ├── Knowledge Item
                       └── Review
```

Run-scoped source Entity:

```text
Pipeline Run
├── Comment
├── Attachment
├── Relationship
├── Custom Field Catalog
└── Custom Field Value
```

핵심 provenance:

```text
Knowledge Item
  ↓
Evidence
  ↓
Issue Version 또는 Run-scoped Source Entity
  ↓
source_path
  ↓
ANALYSIS / RAW
```

---

## 5. Source / Version Entity

### 5.1 `pipeline_run`

한 번의 수집/분석 관찰 범위다.

```text
run_id                         authoritative Run ID
status
created_at / generated_at
analysis_schema_version
knowledge_input_schema_version
```

```text
Pipeline Run 생성
≠
Issue Version 생성
```

Run은 관찰 시점이고 Version은 의미 상태다.

### 5.2 `issue`

Jira Issue의 장기 identity다.

```text
jira_id                        authoritative Jira identity
issue_key                      현재 human-readable locator
project_key                    현재 project locator
```

원칙:

```text
jira_id
= authoritative identity

issue_key
= human-readable / cross-layer locator
= 변경 가능
```

`issue_key`는 파일명, Evidence, 관계, 사용자 질의에서 계속 중요하므로 버리지 않는다.

### 5.3 `issue_version`

Knowledge Input의 의미 상태가 바뀔 때만 생성되는 immutable content-addressed state다.

```text
issue_version_id               deterministic logical ID
jira_id                        FK → issue
source_hash                    Knowledge Input semantic hash
source_run_id                  이 Version의 canonical source Run
source_issue_key               canonical source Run에서 관찰한 issue_key
summary
description
description_format
issue_type
status
priority
created_at
updated_at
source_path

UNIQUE(jira_id, source_hash)
```

Version 생성 규칙:

```text
기존 source_hash == 새 source_hash
→ 기존 issue_version 재사용

기존 source_hash와 다름
→ 새 issue_version 생성
```

`A → B → A`라면 마지막 A는 새 Version을 만들지 않고 최초 A Version을 재사용한다.
시간 순서는 Observation이 담당한다.

### 5.4 `issue_version_observation`

Run에서 어떤 Version을 관찰했는지 기록하는 temporal mapping이다.

```text
run_id                         FK → pipeline_run
jira_id                        FK → issue
observed_issue_key             해당 Run에서 관찰한 key
issue_version_id               FK → issue_version

UNIQUE(run_id, jira_id)
```

예:

```text
Run A → Jira 10001 / KEY-1 → V_A
Run B → Jira 10001 / KEY-1 → V_A
Run C → Jira 10001 / KEY-1 → V_B
Run D → Jira 10001 / KEY-9 → V_A
```

본문을 복제하지 않으면서 Run chronology, key 변경, A→B→A를 표현한다.

### 5.5 `comment`

특정 Run에서 관찰된 Comment다.

```text
run_id
issue_key
comment_id
sequence
author_name
author_key
created_at
updated_at
body
body_format
source_path
source_page

UNIQUE(run_id, issue_key, comment_id)
UNIQUE(run_id, issue_key, sequence)
```

### 5.6 `attachment`

현재는 metadata만 저장한다.

```text
run_id
issue_key
attachment_id
filename
author_name
author_key
created_at
size_bytes
mime_type
content_available
source_path

UNIQUE(run_id, attachment_id)
```

Attachment binary/content가 DB에 있다고 가정하지 않는다.

### 5.7 `relationship`

canonical source → target graph edge를 보존한다.

```text
run_id
relationship_id
relationship_category
relationship_type
relationship_text
source_issue_key
target_issue_key
derived
source_path

UNIQUE(run_id, relationship_id)
```

incoming/outgoing은 endpoint 기준으로 계산한다.

### 5.8 `custom_field_catalog`

```text
run_id
field_id
field_name
schema_type
schema_items
schema_custom
schema_custom_id

UNIQUE(run_id, field_id)
```

### 5.9 `custom_field_value`

Issue에 실제 값이 있는 Custom Field만 저장한다.

```text
run_id
issue_key
field_id
actual_type
value_kind
display_value
display_values_json
value_id
value_ids_json
user_keys_json
value_shape_json
source_path

UNIQUE(run_id, issue_key, field_id)
```

M7에서는 multi-value를 child table로 추가 normalize하지 않는다.
실제 element-level SQL 질의 요구가 생길 때만 분리한다.

---

## 6. Knowledge Entity

### 6.1 `knowledge_generation`

한 Issue Version + 한 Knowledge Contract에 대한 deterministic retry lineage다.

```text
knowledge_generation_id       deterministic logical ID
issue_version_id              FK → issue_version
jira_id                       FK → issue
source_run_id                 Evidence 복원용 canonical Run
source_issue_key              canonical source Run의 issue_key
source_hash                   Knowledge Input semantic hash
knowledge_contract_hash
knowledge_schema_version
skill_version
runtime_version
model_profile
accepted_attempt_id           nullable logical pointer
state                         candidate / active / historical / review_required
created_at
```

Cardinality:

```text
issue_version 1 ── N knowledge_generation
```

원문은 같아도 extraction contract가 바뀌면 새 Generation이 가능하다.

```text
same issue_version
+ different knowledge contract
→ new knowledge_generation
```

### 6.2 `knowledge_attempt`

Generation 내부의 실제 Worker → Validator → Reviewer retry 단위다.

```text
knowledge_attempt_id          deterministic logical ID
knowledge_generation_id       FK
attempt_no                     1..N
knowledge_content_hash         nullable when legacy content unavailable
content_available              boolean
validator_status               nullable
created_at / generated_at      nullable

UNIQUE(knowledge_generation_id, attempt_no)
```

Attempt는 immutable이다.
같은 Attempt ID를 다시 materialize했는데 content hash가 다르면 update하지 않고 integrity error로 처리한다.

현재 M4 legacy artifact 처리:

```text
최종 PASS Attempt
→ content_available=true
→ 현재 issues/<ISSUE_KEY>.json을 해당 Attempt의 Knowledge로 적재

과거 failed Attempt
→ Review / Finding은 보존
→ 당시 Knowledge snapshot 파일이 없으므로 content_available=false
→ Knowledge Item을 추정 생성하지 않음
```

향후 Runtime에서 Attempt별 Knowledge snapshot을 저장하면 같은 모델에 그대로 적재한다.

### 6.3 `knowledge_item`

Knowledge 6 category를 하나의 generic table에 저장한다.

```text
knowledge_item_id              deterministic logical ID
knowledge_attempt_id           FK
category
ordinal
statement                      TEXT

UNIQUE(knowledge_attempt_id, category, ordinal)
```

허용 category:

```text
issue_summary
problem_or_goal
key_findings
actions_and_decisions
outcomes
open_items
```

`issue_summary`:

```text
category = issue_summary
ordinal = 0
```

빈 Array는 row가 없는 정상 상태다.

---

## 7. Evidence Entity

### 7.1 `knowledge_evidence`

```text
knowledge_evidence_id          deterministic logical ID
knowledge_item_id              FK
ordinal                        원래 evidence_refs 순서
evidence_ref                   exact 원문 문자열
evidence_type
source_run_id
source_issue_key
source_entity_key

UNIQUE(knowledge_item_id, ordinal)
UNIQUE(knowledge_item_id, evidence_ref)
```

예:

```text
summary
description
comment:5001
attachment:7001
relationship:9001
custom_field:customfield_12345
```

Exact `evidence_ref`를 반드시 그대로 보존한다.

### 7.2 Evidence round-trip

Issue Version 자체를 가리키는 Evidence:

```text
summary
→ knowledge_item
→ knowledge_attempt
→ knowledge_generation.issue_version_id
→ issue_version.summary

description
→ knowledge_generation.issue_version_id
→ issue_version.description
```

Run-scoped source:

```text
comment:<comment_id>
→ comment(source_run_id, source_issue_key, comment_id)

attachment:<attachment_id>
→ attachment(source_run_id, attachment_id)

relationship:<relationship_id>
→ relationship(source_run_id, relationship_id)

custom_field:<field_id>
→ custom_field_value(source_run_id, source_issue_key, field_id)
```

SQLite에서 서로 다른 source table을 한 polymorphic FK로 억지로 연결하지 않는다.

M7 integrity는 다음 조합으로 보장한다.

```text
FK / CHECK / UNIQUE
+
exact evidence_ref
+
type-specific resolver validator
```

Accepted Attempt의 Evidence 하나라도 source로 복원되지 않으면 integrity failure다.

---

## 8. Review Entity

### 8.1 `knowledge_review`

현재 Runtime 기준 Attempt당 Defect Reviewer 결과 0..1개를 저장한다.

```text
knowledge_review_id
knowledge_attempt_id          FK
review_schema_version
score
verdict
critical_error
major_issue_count

factual_fidelity_score
evidence_coverage_score
certainty_preservation_score
classification_score
retrieval_value_score
language_quality_score

UNIQUE(knowledge_attempt_id)
```

Review category score는 고정 column을 사용한다.
현재 실제 category가 작고 명확하므로 key/value EAV table을 만들지 않는다.

### 8.2 `review_finding`

```text
review_finding_id
knowledge_review_id           FK
finding_group
severity
audit_category
ordinal
finding_type
location
message
```

`finding_group` 예:

```text
audit
critical
major
improvement
```

`audit_category` 예:

```text
fact_audit
causal_claim_audit
evidence_audit
classification_audit
missing_knowledge_audit
duplication_audit
```

Review JSON 원본 파일은 그대로 보존하고 DB에서는 질의 가능한 finding 구조를 materialize한다.

---

## 9. Deterministic ID 규칙

### 9.1 Canonical serialization

모든 파생 logical ID는 다음 규칙을 사용한다.

```text
JSON UTF-8
sort_keys=true
separators=(",", ":")
ensure_ascii=false
SHA-256
lowercase full 64 hex
```

Hash material에는 항상 다음을 넣는다.

```text
id_schema_version = 1
kind = <entity kind>
```

Hash는 자르지 않는다.

### 9.2 `issue_version_id`

```text
iv_ + sha256({
  id_schema_version: 1,
  kind: "issue_version",
  jira_id,
  source_hash
})
```

### 9.3 `knowledge_contract_hash`

M6 Functional MVP의 최소 contract:

```text
knowledge_schema_version
skill_version
runtime_version
model_profile
```

```text
kc_ + sha256(canonical contract)
```

Agent file Git SHA / Prompt file hash는 M6/M7에 넣지 않는다.
운영 재현성에서 실제 필요가 확인되면 M11~M13에서 확장한다.

### 9.4 `knowledge_generation_id`

```text
kg_ + sha256({
  id_schema_version: 1,
  kind: "knowledge_generation",
  issue_version_id,
  knowledge_contract_hash
})
```

Timestamp는 ID에 넣지 않는다.

```text
same Version + same Contract
→ same Generation lineage
```

### 9.5 `knowledge_attempt_id`

```text
ka_ + sha256({
  id_schema_version: 1,
  kind: "knowledge_attempt",
  knowledge_generation_id,
  attempt_no
})
```

### 9.6 `knowledge_item_id`

```text
ki_ + sha256({
  id_schema_version: 1,
  kind: "knowledge_item",
  knowledge_attempt_id,
  category,
  ordinal
})
```

`statement`는 ID material에 넣지 않는다.
Attempt는 immutable이므로 statement가 바뀌면 새 Attempt여야 한다.

### 9.7 `knowledge_evidence_id`

```text
ke_ + sha256({
  id_schema_version: 1,
  kind: "knowledge_evidence",
  knowledge_item_id,
  ordinal,
  evidence_ref
})
```

### 9.8 Vector ID 금지

```text
FAISS position / vector id
≠
Knowledge canonical identity
```

향후:

```text
Vector ID → knowledge_item_id 또는 chunk_id
```

mapping은 가능하지만 Vector ID를 authoritative key로 사용하지 않는다.

---

## 10. Generation Lifecycle / Active Retrieval

Generation 상태:

```text
candidate
active
historical
review_required
```

Publish 흐름:

```text
candidate Generation
→ Attempt 1..N
→ Validator
→ Reviewer PASS
→ accepted_attempt_id 설정
→ active publish
→ 이전 active Generation은 historical
```

핵심:

```text
새 Issue Version 발견
≠
기존 active Knowledge 즉시 제거
```

예:

```text
V1 / G1 active
V2 / G2 candidate

G2 PASS 전
→ G1 active 유지

G2 PASS
→ transaction 안에서 G1 historical
→ G2 active
```

M7 SQLite에서는 Issue당 active Generation을 최대 하나로 제한하는 partial UNIQUE index를 사용한다.

개념적으로:

```sql
CREATE UNIQUE INDEX ...
ON knowledge_generation(jira_id)
WHERE state = 'active';
```

기본 Retrieval:

```text
search_current(...)
→ active Generation의 accepted Attempt만
```

History Retrieval:

```text
search_history(...)
→ historical Version / Generation / Attempt 포함 가능
```

Historical Knowledge는 기본 FAISS corpus에 넣지 않는다.

---

## 11. Cardinality

```text
pipeline_run               1 ── N issue_version_observation
issue                      1 ── N issue_version
issue_version              1 ── N issue_version_observation
issue_version              1 ── N knowledge_generation

pipeline_run               1 ── N comment
pipeline_run               1 ── N attachment
pipeline_run               1 ── N relationship
pipeline_run               1 ── N custom_field_catalog
pipeline_run               1 ── N custom_field_value

knowledge_generation       1 ── N knowledge_attempt
knowledge_attempt          1 ── N knowledge_item
knowledge_item             1 ── N knowledge_evidence
knowledge_attempt          1 ── 0..1 knowledge_review
knowledge_review           1 ── N review_finding
```

`knowledge_generation.accepted_attempt_id`는 해당 Generation 내부의 PASS Attempt를 가리킨다.

---

## 12. M6 검증 시나리오

### A. Issue → Current Knowledge

```text
jira_id 또는 현재 issue_key
→ state=active Generation
→ accepted_attempt_id
→ issue_summary + fine-grained Knowledge Item
```

### B. Knowledge → Comment Evidence

```text
Knowledge Item
→ Evidence comment:<id>
→ Generation source_run_id/source_issue_key
→ Comment body/author/sequence
→ source_path
→ RAW
```

### C. Knowledge → Description

```text
Knowledge Item
→ Attempt
→ Generation
→ Issue Version
→ description
→ source_run_id/source_path
```

### D. Relationship Evidence

```text
Knowledge Item
→ relationship:<id>
→ source_run_id
→ canonical source/target edge
```

### E. Review Audit

```text
Issue
→ Issue Version
→ Generation
→ Attempt 1..N
→ Review
→ Critical/Major/Audit Finding
→ accepted PASS Attempt
```

### F. 변경 없음

```text
새 package source_hash == 기존 source_hash
→ 기존 issue_version 재사용
→ 기존 active Knowledge 재사용 가능
```

### G. 의미 변경

```text
source_hash changed
→ new issue_version
→ new generation candidate
→ downstream regeneration
```

### H. 같은 Version 재분석

```text
same issue_version
+ different contract
→ new knowledge_generation
```

### I. A → B → A

```text
Observation chronology
A → V_A
B → V_B
A → V_A 재사용
```

### J. Legacy failed Attempt

```text
Attempt 1 Review FAIL
+ 당시 Knowledge snapshot 없음
→ Attempt/Review/Finding 저장
→ content_available=false
→ Knowledge Item은 추정하지 않음
```

---

## 13. M7 인계 계약

M7은 지정 Run 하나부터 SQLite materialization을 구현한다.

필수 구현 범위:

```text
DDL / migration
loader / idempotent upsert
FK / UNIQUE / CHECK
issue_version_observation
Generation state + partial UNIQUE active index
Attempt / Review history
accepted Attempt Knowledge Item / Evidence
Evidence round-trip resolver validator
Deterministic ID utility
Integrity tests
```

M7에서 하지 않을 것:

- Chunk 정책 확정
- Embedding table 확정
- FAISS index 설계
- Ranking 정책
- Historical Knowledge 기본 검색 포함
- Custom Field array child normalization
- Prompt/Git artifact hash 기반 완전 재현성
- Comment 자체의 content-addressed versioning

---

## 14. M6 Gate

- [x] 주요 Entity와 Cardinality 합의
- [x] Jira/source ID와 Knowledge logical ID 원칙 합의
- [x] `jira_id` authoritative / `issue_key` locator 경계 확정
- [x] Issue Version 생성/재사용 원칙 합의
- [x] Run과 Version Observation 분리
- [x] Generation과 Retry Attempt 분리
- [x] 6개 Evidence type round-trip 표현 가능
- [x] Issue → Knowledge → Evidence → source query path 명확
- [x] Review Attempt / Historical defect audit 보존 방식 합의
- [x] Active / Historical Retrieval 경계 합의
- [x] M7에서 구현 가능한 logical field contract 확정
- [x] Custom Field / Review score / polymorphic FK 과도한 일반화 제거

## **M6 Gate: PASS / DONE**

다음 단계:

```text
M7 · SQLite Materialization
→ DDL
→ deterministic ID utility
→ loader/upsert
→ integrity constraints
→ Evidence round-trip tests
```
