# M6 DB Logical Schema

기준일: 2026-08-25  
상태: **M6 CURRENT / Logical Design Draft v0.2**

이 문서는 M5 실제 Profiling 결과를 바탕으로 Jira Knowledge DB의 논리 Entity, 관계, 식별자, 버전, Evidence round-trip 계약을 정의한다.

> 문서 보존 원칙: M0~M5의 기존 입력·프롬프트·문제·해결·완료 기록은 삭제하지 않는다. M6는 기존 데이터 계약을 바꾸기보다 그 위에 DB 논리 모델을 얹는다. M6 내부에서 초안이 변경된 경우에는 변경 전 아이디어와 변경 이유를 `docs/M6_DECISION_LOG.md`에 보존한다.

---

## 1. M6 목적

M6는 SQLite DDL을 작성하는 단계가 아니다.
M7에서 물리 DB를 만들기 전에 다음 질문에 답한다.

```text
무엇을 Entity로 저장할 것인가?
각 Entity를 무엇으로 식별할 것인가?
Knowledge가 어느 Issue/원문 Evidence에서 왔는가?
Review Attempt를 어떻게 감사할 것인가?
Run이 바뀌어도 재현성과 추적성을 어떻게 유지할 것인가?
현재 Knowledge와 Historical Knowledge를 어떻게 분리할 것인가?
```

M6 Gate가 통과한 뒤 M7에서 SQLite DDL, loader, index, FK/unique constraint를 구현한다.

---

## 2. M5가 M6에 준 실제 근거

M5 실제 30건 Profiling 요약:

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

M6 설계 제약:

1. Issue → Knowledge Item은 자연스러운 1:N이다.
2. Knowledge Item → Evidence도 1:N이다.
3. Evidence의 약 80%가 Comment이므로 Comment round-trip이 핵심이다.
4. Category별 별도 테이블을 만들 필요는 없다.
5. Empty category는 정상이다.
6. `issue_summary`는 Issue-level representation 성격을 가진다.
7. statement 길이/개수의 현재 max를 DB 하드 상한으로 사용하지 않는다.
8. Review Attempt와 historical defect 이력을 보존해야 한다.
9. Historical Knowledge는 감사/재현 가치가 있지만 기본 Retrieval에 섞으면 노이즈가 될 수 있다.

---

## 3. 기존 데이터 계약을 그대로 사용한다

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

Attempt별 Review JSON의 Audit/Score/Verdict를 보존한다.

M6는 위 계약을 다시 정의하지 않는다.
DB는 이 산출물을 질의 가능한 형태로 materialize한다.

---

## 4. 전체 논리 구조

M6-01에서 `Run마다 모든 Issue snapshot을 추가`하는 초안을 폐기하고, **의미가 변경될 때만 `issue_version`을 추가**하는 구조로 바꿨다.

```text
Pipeline Run
   │
   └── Issue Version Observation ──────────────┐
                                               │
Issue                                          │
   │                                           │
   └── Issue Version ◀─────────────────────────┘
          │
          ├── source_run_id
          ├── source_hash
          │
          └── Knowledge Generation
                 │
                 ├── Knowledge Item
                 │      │
                 │      └── Evidence
                 │             ├── Issue.summary
                 │             ├── Issue.description
                 │             ├── Comment
                 │             ├── Attachment
                 │             ├── Relationship
                 │             └── Custom Field Value
                 │
                 └── Knowledge Review Attempt
                        └── Review Finding
```

원본 Entity는 여전히 ANALYSIS Run에서 추적한다.

```text
source_run_id
├── Comment
├── Attachment
├── Relationship
└── Custom Field Value
```

핵심은 두 가지다.

```text
Knowledge → Evidence → ANALYSIS/RAW
```

round-trip을 잃지 않는 것과:

```text
History Storage ≠ Active Retrieval Corpus
```

를 명확히 분리하는 것이다.

---

## 5. Entity 목록

### 5.1 `pipeline_run`

한 번의 수집/분석 관찰 범위를 나타낸다.

핵심 속성:

```text
run_id                  PK / 기존 Run ID
status
created_at / generated_at
analysis_schema_version
knowledge_input_schema_version
```

중요:

```text
Pipeline Run 생성
≠
모든 Issue Version 생성
```

Run은 관찰 시점이고 Version은 의미 변경 단위다.

### 5.2 `issue`

Jira Issue의 안정적인 identity를 나타낸다.

```text
issue_key               PK 또는 UNIQUE business key
jira_id
project_key
```

`issue_key`는 현재 시스템의 주요 cross-layer key다.

Issue의 의미 변경 이력은 `issue_version`으로 분리한다.

### 5.3 `issue_version`

**Knowledge Input의 의미 내용이 변경될 때만 생성되는 불변 Version**이다.

```text
issue_version_id        logical stable ID
issue_key               FK → issue
source_hash              Knowledge Input semantic hash
source_run_id            이 Version의 canonical source Run
summary
description
description_format
issue_type
status
priority
created_at
updated_at
source_path

UNIQUE(issue_key, source_hash)
```

Version 생성 규칙:

```text
latest source_hash == new source_hash
→ 의미 변경 없음
→ 새 issue_version 생성하지 않음
→ 기존 Version 재사용

latest source_hash != new source_hash
→ 의미 변경
→ 새 issue_version 생성
```

`source_hash`는 Knowledge Input의 다음 의미 데이터에 기반한다.

```text
issue
comments
attachments
relationships
custom_fields
```

따라서 Jira Issue core가 그대로라도 Comment/Relationship/Custom Field 등 OpenCode 입력 의미가 바뀌면 새 Issue Version으로 간주할 수 있다.

왜 Version을 보존하는가:

- 과거 Knowledge가 실제로 어떤 입력을 보고 생성됐는지 재현
- 현재 Jira 내용으로 과거 Knowledge를 잘못 검증하는 문제 방지
- source_hash 기반 증분 Knowledge Extraction
- Skill/Schema/Model 변경 전후 비교
- 감사와 temporal/history 분석

#### v0.1 초안과의 차이

v0.1에서는 `issue_snapshot(run_id, issue_key)`를 기본안으로 검토했다.
M6-01 논의에서 변경 없는 Issue까지 Run마다 중복 복제하는 문제를 확인해 이 개념을 `issue_version`으로 대체했다.

변경 이유와 당시 논의는 다음 문서에 보존한다.

```text
docs/M6_DECISION_LOG.md
```

### 5.4 `issue_version_observation`

같은 Version을 여러 Run에서 관찰했음을 기록할 필요가 있을 때 사용하는 mapping이다.

```text
run_id                  FK → pipeline_run
issue_key               FK → issue
issue_version_id        FK → issue_version

UNIQUE(run_id, issue_key)
```

예:

```text
Run A → ISSUE-100 → V1
Run B → ISSUE-100 → V1   # 변경 없음, Version 재사용
Run C → ISSUE-100 → V2   # 의미 변경
```

이 mapping은 Version 본문을 복제하지 않으면서 Run 추적성을 유지한다.

M7은 단일 Run materialization부터 시작하므로 물리 테이블로 반드시 구현할지는 M7 DDL에서 판단한다. **논리적으로는 Run과 Version이 서로 다른 개념임을 고정한다.**

### 5.5 `comment`

특정 source Run에서 관찰된 Jira Comment다.

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

M5에서 Evidence의 79.92%가 Comment였으므로 핵심 원본 Entity다.

M7에서는 한 Run만 materialize하므로 현재 계약을 그대로 사용할 수 있다.
향후 Comment 자체의 중복 저장 최적화/Versioning은 M11~M13 운영 단계에서 실제 필요가 확인될 때 검토한다.

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

Attachment binary/content를 현재 DB에 있다고 가정하지 않는다.

### 5.7 `relationship`

canonical graph edge를 보존한다.

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

방향은 기존 ANALYSIS 계약처럼 canonical source → target을 유지한다.
`incoming/outgoing`은 질의 시 endpoint 기준으로 계산할 수 있다.

### 5.8 `custom_field_catalog`

Run에서 관찰한 Custom Field 정의.

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

Issue에 실제 값이 존재하는 Custom Field만 저장한다.

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

Custom Field마다 DB 컬럼을 추가하지 않는다.

---

## 6. Knowledge Entity

### 6.1 `knowledge_generation`

한 Issue Version에 대해 생성된 Knowledge 결과 한 세대를 나타낸다.

```text
knowledge_generation_id     logical stable ID
issue_version_id            FK → issue_version
issue_key                   query 편의를 위한 key
source_run_id               Evidence를 복원할 canonical source Run
source_hash                  Knowledge Input semantic hash
knowledge_schema_version
skill_version
model_profile                예: Pro
final_attempt
final_score
final_verdict
created_at
active_state                 logical state; 물리 표현은 M7에서 결정
```

기존 v0.1의 `run_id + issue_key` 중심 Generation보다 `issue_version_id` 중심으로 바꾼다.

원문 변경:

```text
source_hash changed
→ 새 issue_version
→ 새 knowledge_generation
```

원문은 같지만 extraction contract 변경:

```text
same issue_version
+ Skill / Knowledge Schema / Model Profile 변경
→ 같은 Version에 새 knowledge_generation 가능
```

따라서:

```text
issue_version 1 ── N knowledge_generation
```

이다.

#### Active / Historical

DB에는 과거 Generation을 삭제하지 않는다.
하지만 일반 RAG/FAISS 검색에는 승인된 현재 Generation만 노출한다.

개념 상태:

```text
candidate
active
historical
```

새 Generation publish 흐름:

```text
새 Generation 생성
→ Validator
→ Reviewer
→ PASS
→ active로 전환
→ 이전 active는 historical
```

M6에서는 `active_state`를 boolean, status column, 별도 pointer 중 어떤 물리 구조로 만들지는 아직 확정하지 않는다.
M7에서 무결성을 가장 단순하게 보장할 수 있는 표현을 선택한다.

### 6.2 `knowledge_item`

M5 결과를 반영해 6개 category를 하나의 generic item table에 저장한다.

```text
knowledge_item_id           logical stable ID
knowledge_generation_id     FK
issue_key                   query 편의를 위한 FK/denormalized key
category                    enum-like text
ordinal                     category 내부 순서
statement                   TEXT

UNIQUE(knowledge_generation_id, category, ordinal)
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

`issue_summary`도 같은 table에 두되:

```text
category = issue_summary
ordinal = 0
```

로 저장하는 것을 기본안으로 한다.

장점:

- category별 table 남발 방지
- Empty Array를 별도 row 없이 자연스럽게 표현
- 이후 Chunk 후보 생성 시 동일 interface 사용
- Issue-level summary와 fine-grained item을 category로 구분 가능

---

## 7. Evidence Entity

### 7.1 `knowledge_evidence`

Knowledge Item 한 개는 Evidence 1개 이상을 가진다.

```text
knowledge_evidence_id
knowledge_item_id          FK
ordinal                    evidence_refs 원래 순서
evidence_ref               원래 문자열 보존
evidence_type
source_run_id
source_issue_key
source_entity_key

UNIQUE(knowledge_item_id, ordinal)
UNIQUE(knowledge_item_id, evidence_ref)
```

`evidence_ref` 원문을 반드시 보존한다.

예:

```text
description
comment:5001
attachment:7001
relationship:9001
custom_field:customfield_12345
```

### 7.2 Evidence type별 round-trip

`summary`와 `description`은 Knowledge Generation이 연결된 `issue_version` 자체로 복원한다.

```text
summary
→ knowledge_generation.issue_version_id
→ issue_version.summary

description
→ knowledge_generation.issue_version_id
→ issue_version.description
```

Run-scoped source Entity는 Generation의 `source_run_id`를 사용한다.

```text
comment:<comment_id>
→ comment(source_run_id, issue_key, comment_id)

attachment:<attachment_id>
→ attachment(source_run_id, attachment_id)

relationship:<relationship_id>
→ relationship(source_run_id, relationship_id)

custom_field:<field_id>
→ custom_field_value(source_run_id, issue_key, field_id)
```

M6 Gate에서 최소한 이 6가지 경로가 모두 논리적으로 표현 가능해야 한다.

### 7.3 `source_entity_key`

Evidence type별 ID를 하나의 generic text key로 저장하되, 물리 FK를 억지로 하나의 polymorphic FK로 만들지 않는다.

M7에서는:

- exact `evidence_ref` 보존
- type별 resolver query
- integrity validator

조합을 우선 검토한다.

이유:

SQLite에서 서로 다른 6개 table을 하나의 FK 컬럼이 직접 참조하도록 만드는 것은 자연스럽지 않다.

---

## 8. Review Entity

### 8.1 `knowledge_review`

Attempt별 Reviewer 결과를 보존한다.

```text
knowledge_review_id
knowledge_generation_id
issue_key
attempt
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

UNIQUE(knowledge_generation_id, attempt)
```

최종 PASS Review만 저장하지 않고 모든 Attempt를 보존한다.

M5에서:

```text
30 Issue
37 Review files
Historical Critical Issue 2
Historical Major Issue 4
```

가 확인됐기 때문에 중간 Review 이력은 감사 가치가 있다.

### 8.2 `review_finding`

Review JSON의 상세 Audit/Critical/Major/Improvement를 generic finding table로 보존한다.

```text
review_finding_id
knowledge_review_id
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

Review JSON 전체를 DB에 그대로 문자열 복제하는 것보다 query 가능한 구조를 우선한다.
원본 Review JSON은 파일 산출물로 계속 보존한다.

---

## 9. ID 원칙

### 9.1 Source ID를 우선한다

이미 존재하는 식별자를 버리고 DB 전용 ID로 대체하지 않는다.

```text
run_id
issue_key
jira_id
comment_id
attachment_id
relationship_id
field_id
```

은 원본/ANALYSIS 식별 계약을 유지한다.

### 9.2 DB surrogate key는 내부 편의를 위한 것

SQLite에서 `INTEGER PRIMARY KEY`를 사용하더라도 그것은 storage optimization용이다.
외부 API/MCP/Evidence/Vector mapping의 authoritative ID로 사용하지 않는다.

### 9.3 Version / Knowledge stable ID

Jira가 제공하지 않는 파생 Entity에는 deterministic logical ID가 필요하다.

M6-01 이후 기본 개념:

```text
issue_version_id
= deterministic hash/logical key(
    issue_key,
    source_hash
  )

knowledge_generation_id
= deterministic hash/logical key(
    issue_version_id,
    extraction contract
  )

knowledge_item_id
= deterministic hash/logical key(
    knowledge_generation_id,
    category,
    ordinal,
    statement
  )
```

`extraction contract`의 정확한 canonical serialization은 **M6-02**에서 확정한다.

### 9.4 Vector ID 금지

FAISS position/vector index는 Knowledge의 identity가 아니다.

```text
Vector ID → knowledge_item_id
```

mapping은 가능하지만 반대 방향의 authoritative identity로 사용하지 않는다.

---

## 10. Run / Version 원칙

최소 추적 대상:

```text
source run_id
Knowledge Input source_hash
package_schema_version
knowledge_schema_version
skill_version
review schema version
model profile / extraction contract
```

M6-01의 핵심 판단:

```text
source_hash unchanged
→ 새 issue_version 없음
→ 기존 active Knowledge 재사용
→ Knowledge/Chunk/Embedding/Vector 재생성 생략 후보

source_hash changed
→ 새 issue_version
→ 새 Knowledge Generation
→ downstream invalidation
```

원문은 같아도 extraction contract가 바뀌면:

```text
same issue_version
→ new knowledge_generation 가능
```

M6에서는 lifecycle 알고리즘을 구현하지 않지만 DB가 이 판단에 필요한 정보를 잃지 않게 한다.

---

## 11. History / Active / 재실행 원칙

### 11.1 History는 삭제하지 않는다

과거 `issue_version`, `knowledge_generation`, Review 이력은 감사와 재현을 위해 보존한다.

```text
Issue
├── V1 → G1 historical
├── V2 → G2 historical
└── V3 → G3 active
```

과거 Version을 보존하는 이유:

- 당시 Knowledge와 Evidence 재현
- 원인/판단 변화 과정 분석
- Skill/Schema/Model 변경 전후 비교
- LLM 품질 디버깅
- temporal/history query

### 11.2 기본 Retrieval은 Active만 사용한다

Historical Knowledge를 기본 Vector corpus에 함께 넣지 않는다.

```text
[DB]
Current + Historical 모두 보존

[기본 RAG / FAISS]
active Knowledge만 포함

[History Retrieval]
명시적인 감사/변화 분석/temporal query에서만 historical 포함
```

이 원칙은 M8/M9에 넘기는 설계 제약이다.

개념적 Retriever:

```text
search_current(...)
→ active Knowledge만

search_history(...)
→ historical Version/Knowledge 포함 가능
```

### 11.3 새 Knowledge publish

새 Generation이 생성됐다는 이유만으로 즉시 current를 교체하지 않는다.

```text
candidate 생성
→ Validator / Reviewer
→ PASS
→ active publish
→ previous active → historical
```

이후 M14 atomic publish / rollback 설계와 연결된다.

### 11.4 M7 범위

M7 Functional MVP에서는 지정 Run 하나를 DB로 materialize한다.

그러나 Logical Schema는 다음을 막지 않아야 한다.

- 같은 Issue의 새로운 Version 추가
- 변경 없는 Run에서 기존 Version 재사용
- Comment 수정본/새 댓글 반영
- Knowledge source_hash 변경
- 같은 Version에 새로운 Knowledge Generation 추가
- 이전 Generation의 Review audit 보존
- active/historical 전환

초기 구현 편의를 이유로 `issue_key` 하나에 과거/현재 데이터를 덮어써서 감사 정보를 잃지 않는다.

---

## 12. 주요 Cardinality

```text
pipeline_run             1 ── N issue_version_observation
issue                    1 ── N issue_version
issue_version            1 ── N issue_version_observation
issue_version            1 ── N knowledge_generation

pipeline_run             1 ── N comment
pipeline_run             1 ── N attachment
pipeline_run             1 ── N custom_field_value
pipeline_run             1 ── N relationship

knowledge_generation     1 ── N knowledge_item
knowledge_item           1 ── N knowledge_evidence
knowledge_generation     1 ── N knowledge_review
knowledge_review         1 ── N review_finding
```

`relationship`은 source/target 양쪽 `issue_key`를 가진 graph edge다.

`issue_version_observation`은 Run과 Version의 관찰 관계를 표현하지만 M7에서 별도 물리 테이블로 구현할지는 아직 미정이다.

---

## 13. M6에서 하지 않는 것

- SQLite DDL 확정
- 실제 DB 파일 생성
- index/PRAGMA 튜닝
- Chunk table 확정
- Embedding table 확정
- FAISS index 설계
- 검색 ranking 정책 확정
- Historical Knowledge를 기본 검색에 섞기
- current 30건의 max 길이를 컬럼 hard limit로 사용
- Custom Field마다 컬럼 추가
- Evidence를 JSON 문자열 하나로 묻고 round-trip을 포기
- 변경 없는 Issue의 Version을 Run마다 강제로 복제

---

## 14. M6 검증 시나리오

Logical Schema는 최소 다음 질의를 표현할 수 있어야 한다.

### A. Issue → Current Knowledge

```text
Issue Key
→ active Knowledge Generation
→ issue_summary + fine-grained items
```

### B. Knowledge → Evidence → Comment

```text
Knowledge Item
→ evidence_ref=comment:<id>
→ knowledge_generation.source_run_id
→ Comment body/author/sequence
→ RAW source_path
```

### C. Knowledge → Description

```text
Knowledge Item
→ Knowledge Generation
→ Issue Version
→ description
→ source_run_id / RAW source_path
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
→ Knowledge Generation
→ Attempt 1..N
→ Critical/Major/Audit findings
→ Final PASS
```

### F. 변경 판단

```text
Issue A latest source_hash
vs
Issue A new source_hash

same
→ Version 재사용

different
→ 새 Version
```

### G. 같은 Version 재분석

```text
Issue Version V1
├── Generation G1 · old extraction contract
└── Generation G2 · new extraction contract
```

### H. Current vs History Retrieval

```text
일반 질문
→ active Generation only

"판단이 어떻게 변했나?"
→ historical Generation 포함
```

---

## 15. 현재 결정과 열린 항목

### M6-01 · 확정

- `issue`는 Jira Issue의 안정적인 identity다.
- Run마다 모든 Issue snapshot을 복제하지 않는다.
- `source_hash`가 바뀔 때만 새 `issue_version`을 만든다.
- 변경 없는 Issue는 기존 Version과 active Knowledge를 재사용한다.
- 같은 `issue_version`에 여러 `knowledge_generation`이 존재할 수 있다.
- Historical Version/Knowledge는 DB에 보존한다.
- 기본 RAG/FAISS corpus에는 active Current Knowledge만 포함한다.
- History는 감사/재현/변화 분석/temporal query 용도로 분리한다.
- 새 Knowledge는 PASS 후 active로 publish하고 이전 Generation은 historical로 보존한다.

상세 의사결정 이력:

```text
docs/M6_DECISION_LOG.md
```

### 기존 기본안 중 유지

- Knowledge 6 category는 generic `knowledge_item` 한 table
- `issue_summary`도 category=`issue_summary`로 같은 table에 저장
- Evidence는 별도 1:N Entity
- exact `evidence_ref`를 보존하고 type별 resolver로 source Entity에 연결
- 모든 Review Attempt 보존
- detailed Review finding은 generic `review_finding` Entity
- source ID와 deterministic Knowledge logical ID를 authoritative key로 사용

### M6에서 추가 검토할 항목

1. **M6-02** `issue_version_id` / `knowledge_generation_id` deterministic hash의 canonical serialization
2. `custom_field_value`의 array 값을 JSON text로 둘지 child table로 더 normalize할지
3. Review category score를 column으로 둘지 child key/value table로 둘지
4. Evidence integrity를 SQLite FK 대신 validator로 어디까지 보장할지
5. M7은 단일 Run materialization으로 시작하되 `issue_version_observation`을 물리화할지
6. active Knowledge 표현을 status/boolean/pointer 중 무엇으로 구현할지

---

## 16. M6 Gate

M6 완료 조건:

- [ ] 주요 Entity와 Cardinality 합의
- [ ] Source ID / Knowledge ID 원칙 합의
- [ ] 6개 Evidence type round-trip 표현 가능
- [ ] Issue → Knowledge → Evidence → source query path 명확
- [ ] Review Attempt/Defect audit 보존 방식 합의
- [x] Issue identity / Version 생성 원칙 합의 · **M6-01**
- [x] History 보존 / Active Retrieval 분리 원칙 합의 · **M6-01**
- [ ] M7에서 구현 가능한 수준으로 logical field contract 확정
- [ ] 과도한 정규화/미래 기능 과설계를 제거

Gate 통과 후:

```text
M7 SQLite Materialization
→ DDL
→ Loader/Upsert
→ Index/FK/Unique
→ Integrity / Evidence round-trip tests
```
