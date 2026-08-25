# M6 DB Logical Schema Decision Log

기준일: 2026-08-25  
상태: **M6 DONE / DECISIONS FROZEN**

이 문서는 M6 DB Logical Schema를 논의하면서 검토한 초안, 발견한 문제, 변경 이유, 최종 결정을 순서대로 보존한다.

> 보존 원칙: 이전 아이디어를 결과에 맞춰 지우지 않는다. 최종 설계에서 바뀐 구조는 `Superseded`로 표시하고, 현재 authoritative 계약은 `docs/DB_LOGICAL_SCHEMA.md`를 따른다.

현재 프로젝트 위치:

```text
M0~M6   DONE
M7      IMPLEMENTED / REAL-RUN VALIDATION PENDING
M8      BLOCKED UNTIL M7 REAL-RUN GATE
```

---

## M6-01 · Issue Identity / Version / Active Retrieval

상태: **DECIDED**

### 1. 최초 초안 · Run별 Issue Snapshot

M6 v0.1에서는 다음 구조를 검토했다.

```text
issue
  1
  └── N issue_snapshot
          └── Run마다 관찰한 Issue 상태
```

즉 Pipeline Run이 생길 때마다 같은 Issue 내용도 새 snapshot으로 저장하는 방식이었다.

### 2. 문제 발견

- 변경되지 않은 Issue까지 Run마다 중복 저장된다.
- Run 발생과 실제 업무 의미 변경을 구분하기 어렵다.
- Jira 규모가 커질수록 불필요한 중복이 커진다.
- Knowledge 재생성 여부의 기준이 애매해진다.

따라서 **Run과 Issue semantic state를 분리**하기로 했다.

### 3. 확정 · Issue Version

```text
issue
= Jira Issue identity

issue_version
= Knowledge Input의 의미 상태가 변경될 때만 생기는 immutable Version
```

Version 판단 기준:

```text
old source_hash == new source_hash
→ 기존 issue_version 재사용

old source_hash != new source_hash
→ 새 issue_version 생성
```

`source_hash`는 Knowledge Input의 다음 의미 데이터를 반영한다.

```text
issue
comments
attachments
relationships
custom_fields
```

따라서 Issue core가 그대로여도 Comment/Relationship/Custom Field 등이 바뀌어 실제 Worker 입력 의미가 달라지면 새 Version이 될 수 있다.

### 4. Run과 Version은 다른 개념

```text
Run A → Issue state A → V_A
Run B → Issue state A → V_A 재사용
Run C → Issue state B → V_B
Run D → Issue state A → V_A 재사용
```

마지막 `A → B → A` chronology를 표현하기 위해 `issue_version_observation` 개념을 두기로 했다.

```text
issue_version_observation
  run_id
  jira identity
  observed issue_key
  issue_version_id
```

Version 자체는 content-addressed state이고 시간 순서는 Observation이 담당한다.

### 5. Knowledge Generation

Issue Version이 달라지면 Knowledge도 새로운 Generation 대상이다.

```text
V_A → Generation G1
V_B → Generation G2
```

하지만 원문은 같아도 extraction contract가 바뀌면 같은 Version에 새로운 Generation을 만들 수 있다.

```text
V_A
├── G1 · old contract
└── G2 · new contract
```

### 6. History Storage ≠ Active Retrieval

Historical Version/Knowledge는 삭제하지 않는다.

보존 목적:

- 당시 Evidence 재현
- Skill/Schema/Model 변경 전후 비교
- 판단 변화 분석
- LLM 품질 디버깅
- temporal/history query

하지만 기본 Vector Retrieval에는 승인된 현재 Knowledge만 사용한다.

```text
[DB]
Current + Historical 보존

[기본 RAG / FAISS]
active Current Knowledge only

[History Retrieval]
명시적인 감사/재현/변화 분석에서만 historical 포함
```

### 7. Active publish

새 Generation이 생겼다는 이유만으로 기존 active를 제거하지 않는다.

```text
G1 active
G2 candidate

G2 PASS 전
→ G1 active 유지

G2 PASS
→ G1 historical
→ G2 active
```

### 8. M6-01 최종 결정

```text
DECISION M6-01

1. Run마다 전체 Issue snapshot을 복제하지 않는다.
2. source_hash 변경 시에만 새 issue_version을 만든다.
3. 변경 없는 상태는 기존 Version을 재사용한다.
4. issue_version 1개에 여러 knowledge_generation을 허용한다.
5. Historical Version/Knowledge는 DB에 보존한다.
6. 기본 RAG/FAISS는 active Current Knowledge만 사용한다.
7. 새 Knowledge는 PASS 후 publish한다.
8. Run chronology는 Version Observation으로 분리한다.
```

### 9. M6-01 당시 Cardinality에 대한 주의

M6-01 단계에서는 아래처럼 단순화해 표현한 적이 있다.

```text
issue_version
  └── knowledge_generation
        ├── knowledge_item
        └── knowledge_review
```

**이 직접 연결은 M6-02에서 Superseded되었다.**

최종 authoritative 구조는 반드시 다음이다.

```text
knowledge_generation
  └── knowledge_attempt
        ├── knowledge_item
        └── knowledge_review
```

---

## M6-02 · Deterministic ID / Generation-Attempt Model

상태: **DECIDED**

M4 실제 Runtime은 한 Issue를 최대 3 Attempt까지 재생성할 수 있다.

```text
Attempt 1 → Review REGENERATE
Attempt 2 → Review REGENERATE
Attempt 3 → Review PASS
```

M6-01의 `Generation → Item/Review` 직접 모델로는 **어느 재생성 회차의 Knowledge와 Review인지** 정확히 표현할 수 없었다.

따라서 Generation과 Attempt를 분리한다.

### 1. Jira identity

```text
jira_id
= authoritative Jira identity

issue_key
= human-readable / cross-layer locator
= 변경 가능
```

M0~M5 파일 계약에서 `issue_key`가 널리 사용되지만, 장기 DB identity는 `jira_id`를 우선한다.

### 2. Canonical ID 공통 규칙

```text
id_schema_version = 1
kind = <entity kind>
JSON UTF-8
sort_keys = true
ensure_ascii = false
separators = (",", ":")
SHA-256
full lowercase 64 hex
```

Hash는 자르지 않는다.
SQLite INTEGER surrogate key를 내부 저장 최적화에 사용할 수 있어도 외부 logical identity를 대체하지 않는다.

### 3. Issue Version ID

```text
issue_version_id
= iv_ + H({
    jira_id,
    source_hash
  })
```

따라서 A → B → A에서 마지막 A는 기존 `iv_`를 재사용한다.

### 4. Knowledge Contract

Generation identity에 포함할 최소 contract:

```text
knowledge_schema_version
skill_version
runtime_version
model_profile
```

```text
knowledge_contract_hash
= kc_ + H(contract)
```

M6/M7에서는 Agent 파일 전체 Git SHA나 Prompt 파일 hash까지 넣지 않는다. 실제 운영에서 필요성이 확인될 때 M11~M13 재현성 강화 범위에서 확장한다.

### 5. Knowledge Generation ID

Generation은 **Issue Version + Knowledge Contract에 대한 retry lineage**다.

```text
knowledge_generation_id
= kg_ + H({
    issue_version_id,
    knowledge_contract_hash
  })
```

```text
same Version + same Contract
→ same kg_

Contract changed
→ new kg_
```

Timestamp는 Generation identity에 넣지 않는다.

### 6. Knowledge Attempt 추가

실제 재생성 회차는 별도 immutable Entity다.

```text
knowledge_generation
  1
  └── N knowledge_attempt
          ├── N knowledge_item
          └── 0..1 knowledge_review
```

핵심 필드:

```text
knowledge_attempt_id
knowledge_generation_id
attempt_no
knowledge_content_hash
content_available
generated_at
validator_status
```

ID:

```text
knowledge_attempt_id
= ka_ + H({
    knowledge_generation_id,
    attempt_no
  })
```

따라서:

```text
Attempt 1 ≠ Attempt 2 ≠ Attempt 3
```

재생성 회차 identity는 유실되지 않는다.

### 7. Knowledge Item ID

```text
knowledge_item_id
= ki_ + H({
    knowledge_attempt_id,
    category,
    ordinal
  })
```

`statement`는 ID material에서 제외한다.

이유:

- Attempt는 immutable하다.
- statement가 바뀌면 새로운 Attempt여야 한다.
- Item identity와 content integrity를 분리한다.

### 8. Evidence ID

```text
knowledge_evidence_id
= ke_ + H({
    knowledge_item_id,
    ordinal,
    exact evidence_ref
  })
```

`evidence_ref` 문자열 자체도 원문 그대로 별도 보존한다.

### 9. Review 연결

Superseded:

```text
knowledge_review
→ knowledge_generation + attempt number
```

Final:

```text
knowledge_review
→ knowledge_attempt_id
```

Generation은 최종 승인 Attempt를 빠르게 찾기 위해:

```text
accepted_attempt_id
```

를 가진다.

### 10. M4 legacy artifact 처리

현재 M4 파일 구조는:

```text
issues/<ISSUE_KEY>.json
reviews/<ISSUE_KEY>.review.attempt<N>.json
```

Review는 Attempt별로 남지만 실패 Attempt 당시 Knowledge 본문은 저장되지 않았다.

따라서 M7에서:

```text
failed historical Attempt
→ Attempt / Review / Finding 보존
→ content_available=false
→ 없는 Knowledge Item은 추정하지 않음

accepted final Attempt
→ content_available=true
→ Knowledge Item / Evidence materialize
```

### 11. M6-02 최종 결정

```text
DECISION M6-02

1. jira_id를 authoritative Issue identity로 사용한다.
2. issue_key는 locator로 계속 보존한다.
3. 파생 logical ID는 versioned canonical JSON + full SHA-256을 사용한다.
4. iv_ = jira_id + source_hash.
5. kc_ = schema + skill + runtime + model profile.
6. kg_ = Issue Version + Knowledge Contract lineage.
7. retry/re-generation 회차는 별도 knowledge_attempt로 보존한다.
8. ka_에는 attempt_no가 포함된다.
9. Knowledge Item과 Review는 Attempt에 연결한다.
10. ki_는 Attempt + category + ordinal이다.
11. ke_는 Item + ordinal + exact evidence_ref이다.
12. accepted_attempt_id가 최종 PASS Attempt를 가리킨다.
13. legacy failed Attempt의 없는 Knowledge는 추정하지 않는다.
```

---

## M6-03 · Logical Schema Simplification / Integrity

상태: **DECIDED**

목적은 M7 직전 정규화 수준과 SQLite 무결성 표현을 닫는 것이었다.

### 1. Custom Field multi-value

M7에서는 다음 array 값을 JSON text로 유지한다.

```text
display_values_json
value_ids_json
user_keys_json
value_shape_json
```

Element-level SQL 질의 요구가 생기기 전까지 child table로 나누지 않는다.

### 2. Review score

현재 Review Schema의 category score는 고정된 소수 항목이므로 `knowledge_review`의 명시적 column으로 둔다.

```text
score
factual_fidelity_score
evidence_coverage_score
certainty_preservation_score
classification_score
retrieval_value_score
language_quality_score
critical_error
major_issue_count
verdict
```

Generic EAV table을 만들지 않는다.

### 3. Evidence integrity

SQLite에서 서로 다른 source table을 하나의 polymorphic FK로 억지로 연결하지 않는다.

```text
DB
→ FK / CHECK / UNIQUE

Application integrity
→ exact evidence_ref
→ type-specific resolver
→ source existence / endpoint ownership 검증
```

Accepted Attempt의 Evidence 하나라도 source로 round-trip하지 못하면 materialization failure다.

### 4. Observation 실제 table 구현

M6-01에서 논리 개념으로 열어뒀던 `issue_version_observation`을 M7에서 실제 table로 구현하기로 결정했다.

```text
run_id
jira_id
observed_issue_key
issue_version_id

UNIQUE(run_id, jira_id)
```

이 table은 A→B→A chronology와 issue_key 변경을 Version 본문 중복 없이 보존한다.

### 5. Active Generation state

```text
candidate
active
historical
review_required
```

SQLite partial UNIQUE index로 Issue당 active Generation 최대 1개를 강제한다.

```sql
UNIQUE knowledge_generation(jira_id)
WHERE state = 'active'
```

### 6. M6-03 최종 결정

```text
DECISION M6-03

1. Custom Field multi-value는 JSON text 유지.
2. Review score는 고정 column.
3. Evidence polymorphic source는 type-specific resolver validator.
4. accepted Evidence round-trip 실패는 integrity failure.
5. issue_version_observation을 실제 table로 구현.
6. Generation state는 candidate/active/historical/review_required.
7. partial UNIQUE index로 Issue당 active 최대 1개.
8. 새 candidate가 생겨도 PASS 전에는 기존 active 유지.
```

---

## M6-04 · Consolidation / Gate Review

상태: **DECIDED / M6 GATE PASS**

M6-01~03을 `docs/DB_LOGICAL_SCHEMA.md` v0.3에 통합했다.

최종 authoritative 구조:

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

최종 ID ladder:

```text
jira_id
  ↓
iv_
  ↓
kc_
  ↓
kg_
  ↓
ka_ + attempt_no
  ↓
ki_
  ↓
ke_
```

M6 Gate 확인:

- [x] Entity / Cardinality 합의
- [x] jira_id authoritative identity
- [x] source_hash Versioning
- [x] Run / Version Observation 분리
- [x] deterministic ID 규칙
- [x] Generation / Attempt 분리
- [x] 재생성 회차 `ka_` identity
- [x] 6 Evidence type round-trip
- [x] Review historical audit
- [x] Active / Historical 경계
- [x] M7 field contract
- [x] 과도한 정규화 제거

## **M6 Gate: PASS / DONE**

M6 완료 기록:

```text
docs/status/M6_DB_LOGICAL_SCHEMA_COMPLETION.md
```

M7 인계:

```text
SQLite Schema v1
→ deterministic ID utility
→ loader / idempotent materialization
→ Generation / Attempt history
→ Evidence resolver
→ integrity tests
→ actual 30-issue validation
```

현재 M7 구현 계약은 `docs/M7_SQLITE_MATERIALIZATION.md`를 따른다.
