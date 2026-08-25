# M6 DB Logical Schema Decision Log

기준일: 2026-08-25  
상태: **M6 CURRENT**

이 문서는 M6 DB Logical Schema를 논의하면서 확정되는 결정을 순서대로 누적 보존한다.

> 문서 보존 원칙: 이전 초안이 당시의 검토 과정으로서 의미가 있으면 삭제하지 않는다. 최종 설계에서 변경된 내용은 `Superseded`로 명시하고, 왜 변경했는지 함께 남긴다.

---

## M6-01 · Issue Identity / Version / Active Retrieval

상태: **DECIDED**

### 1. 최초 초안

M6 v0.1 초안에서는 다음 구조를 검토했다.

```text
issue
  1
  └── N issue_snapshot
          └── Run마다 관찰한 Issue 상태
```

즉 각 Pipeline Run마다 Issue snapshot을 추가하는 방식이었다.

### 2. 발견한 문제

Run이 새로 생겼다는 이유만으로 변경되지 않은 Issue까지 전부 snapshot으로 복제하면 다음 문제가 있다.

- 동일한 Issue 내용이 Run마다 반복 저장된다.
- Jira Issue가 수천/수만 건으로 늘어날수록 변경 없는 데이터의 중복이 커진다.
- 실제 의미 변화와 단순 재수집을 구분하기 어렵다.
- Knowledge 재생성 여부를 판단하는 기준이 불명확해진다.

따라서 **Run 발생 자체와 Issue 의미 변경을 분리**한다.

### 3. 확정 구조

```text
issue
  = Jira Issue의 안정적인 Identity

issue_version
  = Knowledge Input의 의미 내용이 변경될 때만 생성되는 불변 Version
```

핵심 판단 기준은 Knowledge Input의 `source_hash`다.

```text
기존 latest source_hash == 새 source_hash
→ 의미 변경 없음
→ 새 issue_version 생성하지 않음
→ 기존 Version 재사용

기존 latest source_hash != 새 source_hash
→ 의미 변경 발생
→ 새 issue_version 생성
```

`source_hash`는 Issue core뿐 아니라 Knowledge Input에 포함되는 comments, attachments metadata, relationships, custom fields의 의미 데이터까지 반영하므로, **OpenCode Knowledge Extraction의 실제 입력 단위에 대응하는 Version 기준**으로 사용한다.

### 4. Run과 Version은 같은 개념이 아니다

예:

```text
Run A → ISSUE-100 source_hash=AAA → Version V1 생성
Run B → ISSUE-100 source_hash=AAA → V1 재사용
Run C → ISSUE-100 source_hash=BBB → Version V2 생성
```

필요하면 향후 다음과 같은 Observation mapping으로 "어느 Run에서 어느 Version을 관찰했는가"를 별도로 기록할 수 있다.

```text
issue_version_observation
  run_id
  issue_key
  issue_version_id
```

이 mapping은 같은 내용의 Version 자체를 복제하지 않으면서 Run 추적성을 유지한다.
M7은 단일 Run materialization부터 시작하므로 물리 구현 필요성은 M7 DDL에서 최종 판단한다.

### 5. Knowledge Generation과의 관계

Issue Version이 새로 생기면 그 Version에 대한 Knowledge Generation도 새로 수행한다.

```text
Issue V1 (source_hash=AAA)
└── Knowledge Generation G1

Issue V2 (source_hash=BBB)
└── Knowledge Generation G2
```

변경되지 않은 Issue는 OpenCode를 다시 실행하지 않는 것이 목표다.

```text
source_hash unchanged
→ 기존 issue_version 재사용
→ 기존 active Knowledge 재사용
→ Knowledge/Chunk/Embedding/Vector 재생성 생략 후보
```

이 증분 실행은 M11~M13에서 운영 기능으로 구현한다.

### 6. 같은 Issue Version에도 Knowledge Generation은 여러 개 존재할 수 있다

원문이 바뀌지 않아도 extraction contract가 바뀌면 새 Knowledge를 생성할 수 있다.

예:

```text
Issue Version V1
├── G1 · Skill 0.9 / Schema 0.1 / Model Profile A
└── G2 · Skill 1.0 / Schema 0.2 / Model Profile B
```

따라서 Cardinality는 다음이 맞다.

```text
issue             1 ── N issue_version
issue_version     1 ── N knowledge_generation
knowledge_generation 1 ── N knowledge_item
```

### 7. History 저장과 Retrieval 대상은 분리한다

**과거 Version과 Knowledge를 보존하는 이유는 일반 RAG 검색 품질을 높이기 위해서가 아니다.**

보존 목적:

- 당시 Knowledge가 어떤 원문 Evidence로 생성됐는지 재현
- LLM/Skill/Schema 변경 전후 비교
- 원인 판단과 문제 해결 과정의 변화 분석
- 감사와 디버깅
- 향후 temporal/history query

반대로 과거 Knowledge를 현재 Knowledge와 함께 기본 Vector 검색에 넣으면 서로 다른 시점의 판단이 동시에 검색되어 노이즈가 될 수 있다.

따라서 기본 정책은 다음과 같다.

```text
[DB]
Current + Historical Version/Knowledge 모두 보존

[기본 RAG / FAISS]
Active Current Knowledge만 포함

[History Retrieval]
명시적인 감사·변화 분석·temporal query에서만 사용
```

### 8. Active Knowledge 원칙

일반 서비스 검색에는 Issue별로 **승인된 현재 Knowledge Generation 하나**만 노출한다.

개념적으로:

```text
G1  historical
G2  historical
G3  active
```

새 Generation을 생성하는 동안 기존 active Knowledge를 즉시 제거하지 않는다.

```text
새 Generation 생성
→ Validator / Reviewer Gate
→ PASS
→ active 전환
→ 이전 Generation은 historical
```

이 원칙은 향후 M14의 atomic publish / rollback과도 연결된다.

M6에서는 `active`를 boolean/status/pointer 중 어떤 물리 표현으로 구현할지는 아직 확정하지 않는다. M7 DDL에서 가장 단순하고 무결성을 보장하기 쉬운 방식을 선택한다.

### 9. 일반 Retrieval과 History Retrieval

기본 인터페이스 개념:

```text
search_current(...)
→ active Knowledge만 검색

search_history(...)
→ 필요할 때만 historical Version/Knowledge 포함
```

M9에서 실제 Retriever API를 설계할 때 이 경계를 유지한다.

### 10. M6-01 최종 결정

```text
DECISION M6-01

1. issue는 안정적인 Jira Identity다.
2. Run마다 전체 snapshot을 복제하지 않는다.
3. source_hash가 바뀔 때만 새 issue_version을 생성한다.
4. 변경 없는 Issue는 기존 Version과 Knowledge를 재사용한다.
5. issue_version 1개에 여러 knowledge_generation이 존재할 수 있다.
6. Historical Version/Knowledge는 DB에 보존한다.
7. 기본 FAISS/RAG corpus에는 active Current Knowledge만 포함한다.
8. History는 감사·재현·변화 분석·temporal query 용도로 분리한다.
9. 새 Knowledge는 PASS 후 active로 전환하고 이전 Generation은 historical로 보존한다.
```

---

## M6-02 · Deterministic ID / Generation-Attempt Model

상태: **DECIDED**

M6-01에서 Version과 Generation의 큰 관계를 고정했지만, 실제 M4 Runtime은 한 Issue를 최대 3 Attempt까지 재생성할 수 있다. Review 파일은 Attempt별로 보존되지만 최종 Knowledge 파일은 Issue별 한 파일이므로, DB 논리 모델이 `knowledge_generation → knowledge_item`만 갖는다면 과거 Attempt가 실제로 어떤 Knowledge 후보를 만들었는지 표현할 수 없다.

따라서 M6-02에서 **Generation과 Attempt를 분리**하고 ID 규칙을 함께 확정한다.

### 1. Jira Issue의 authoritative identity

`issue_key`는 현재 파일명, Evidence, 관계, 사용자 질의에서 매우 중요한 locator지만 Jira Issue의 장기 identity로는 `jira_id`를 우선한다.

```text
jira_id
  = authoritative Jira identity

issue_key
  = human-readable / cross-layer locator
  = 변경될 수 있는 business key
```

따라서 M7의 논리/물리 모델은 `jira_id`를 잃지 않아야 하며, `issue_key`는 조회와 Evidence round-trip을 위해 계속 보존한다.

이 결정은 M6-01의 "issue는 안정적인 Jira Identity"를 구체화한 것이다.

### 2. Canonical serialization 공통 규칙

파생 logical ID는 다음 규칙을 공통 사용한다.

```text
canonical_json
= JSON UTF-8
+ object key sort
+ no insignificant whitespace
+ ensure_ascii=false

hash
= SHA-256(canonical_json UTF-8 bytes)

encoding
= lowercase hexadecimal full 64 chars
```

Python 표현 기준:

```python
json.dumps(
    value,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

해시는 자르지 않는다. SQLite 내부에서 INTEGER surrogate key를 추가할 수는 있지만 외부 logical identity는 아래 prefix가 붙은 SHA-256 ID를 사용한다.

각 hash material에는 `id_schema_version=1`과 entity kind를 명시하여 향후 ID 직렬화 규칙 변경을 구분할 수 있게 한다.

### 3. `issue_version_id`

```text
issue_version_id
= "iv_" + sha256(canonical({
    id_schema_version: 1,
    kind: "issue_version",
    jira_id: <jira_id>,
    source_hash: <source_hash>
  }))
```

따라서 같은 Jira Issue가 같은 의미 상태로 다시 관찰되면 같은 `issue_version_id`를 재사용한다.

예:

```text
A → B → A

A 최초 관찰 → V_A
B 관찰      → V_B
A 재관찰    → 기존 V_A 재사용
```

시간 순서는 `issue_version_observation`이 담당하고, `issue_version` 자체는 content-addressed immutable state로 취급한다.

### 4. Knowledge contract

같은 Issue Version이라도 Knowledge 생성 계약이 바뀌면 새로운 Generation이 가능해야 한다.

M6 Functional MVP에서 Generation identity에 포함할 최소 contract는 다음으로 고정한다.

```text
knowledge_schema_version
skill_version
runtime_version
model_profile
```

```text
knowledge_contract_hash
= "kc_" + sha256(canonical({
    id_schema_version: 1,
    kind: "knowledge_contract",
    knowledge_schema_version: ...,
    skill_version: ...,
    runtime_version: ...,
    model_profile: ...
  }))
```

현재 M4 기준 Runtime/Skill은 v0.9이고 Knowledge Schema는 0.1이다. 향후 Agent/Skill/Model 동작을 의미 있게 바꾸면 대응 version/profile을 반드시 갱신한다.

M6에서는 Agent 파일 전체의 Git SHA나 Prompt file hash까지 contract에 넣지 않는다. 실제 운영에서 필요성이 확인되면 M11~M13 재현성 강화 단계에서 추가한다.

### 5. `knowledge_generation_id`

`knowledge_generation`은 **한 Issue Version + 한 Knowledge Contract에 대한 retry lineage**다.

```text
knowledge_generation_id
= "kg_" + sha256(canonical({
    id_schema_version: 1,
    kind: "knowledge_generation",
    issue_version_id: <issue_version_id>,
    knowledge_contract_hash: <knowledge_contract_hash>
  }))
```

같은 Version + 같은 Contract를 다시 materialize하면 같은 Generation을 재사용한다.

```text
same issue_version + same contract
→ same knowledge_generation_id
→ idempotent load / resume

contract changed
→ new knowledge_generation_id
```

Timestamp는 Generation identity에 넣지 않는다.

### 6. `knowledge_attempt` 추가

Retry를 Generation 내부의 별도 immutable Entity로 둔다.

```text
knowledge_generation
  1
  └── N knowledge_attempt
          ├── N knowledge_item
          └── 0..N knowledge_review
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

UNIQUE(knowledge_generation_id, attempt_no)
```

ID:

```text
knowledge_attempt_id
= "ka_" + sha256(canonical({
    id_schema_version: 1,
    kind: "knowledge_attempt",
    knowledge_generation_id: <knowledge_generation_id>,
    attempt_no: <attempt_no>
  }))
```

Attempt는 생성 후 immutable이다. 같은 Attempt ID를 다시 읽었는데 `knowledge_content_hash`가 다르면 update하지 않고 integrity error로 취급한다.

### 7. 현재 M4 legacy artifact 처리

현재 M4 파일 구조는:

```text
issues/<ISSUE_KEY>.json
reviews/<ISSUE_KEY>.review.attempt<N>.json
```

으로 최종 Knowledge만 남고 Review는 Attempt별로 남는다.

따라서 M7에서 기존 M4 Run을 materialize할 때:

```text
최종 accepted Attempt
→ content_available = true
→ Knowledge Item / Evidence materialize

과거 failed Attempt
→ Attempt / Review / Finding은 materialize
→ 과거 Knowledge 후보 파일이 없으므로 content_available = false
→ 존재하지 않는 Knowledge Item을 추정 생성하지 않음
```

향후 Runtime 개선 시 Attempt별 Knowledge snapshot을 보존하면 같은 Logical Schema에 그대로 적재할 수 있다.

### 8. `knowledge_item_id`

Knowledge Item은 Generation이 아니라 Attempt에 속한다.

```text
knowledge_item_id
= "ki_" + sha256(canonical({
    id_schema_version: 1,
    kind: "knowledge_item",
    knowledge_attempt_id: <knowledge_attempt_id>,
    category: <category>,
    ordinal: <ordinal>
  }))
```

`statement` 본문은 ID material에서 제외한다.

이유:

- Attempt는 immutable이므로 같은 Attempt 안에서 statement를 수정하지 않는다.
- statement가 변경되면 새 Attempt여야 한다.
- 본문을 ID에 넣으면 item identity와 content hash의 책임이 섞인다.

본문 무결성은 Attempt의 `knowledge_content_hash`와 별도로 검증한다.

### 9. `knowledge_evidence_id`

Evidence도 동일 원칙으로 deterministic ID를 사용할 수 있다.

```text
knowledge_evidence_id
= "ke_" + sha256(canonical({
    id_schema_version: 1,
    kind: "knowledge_evidence",
    knowledge_item_id: <knowledge_item_id>,
    ordinal: <ordinal>,
    evidence_ref: <exact evidence_ref>
  }))
```

원래 `evidence_ref` 문자열은 ID와 별개로 반드시 원문 그대로 저장한다.

### 10. Review 연결 변경

기존 초안:

```text
knowledge_review
→ knowledge_generation_id + attempt
```

M6-02 이후:

```text
knowledge_review
→ knowledge_attempt_id
```

Attempt 번호는 `knowledge_attempt.attempt_no`에서 얻는다. Review 상세 Finding은 그대로 `knowledge_review → review_finding` 1:N을 유지한다.

Generation에는 최종 승인 결과를 빠르게 찾기 위한 logical pointer를 둔다.

```text
accepted_attempt_id   nullable
```

PASS 전에는 null이고, Reviewer Gate PASS 후 해당 Attempt를 가리킨다.

### 11. M6-02 최종 결정

```text
DECISION M6-02

1. Jira Issue의 authoritative identity는 jira_id를 우선한다.
2. issue_key는 human-readable / cross-layer locator로 계속 보존한다.
3. 파생 logical ID는 versioned canonical JSON + SHA-256 full lowercase hex를 사용한다.
4. issue_version_id는 jira_id + source_hash로 결정한다.
5. Knowledge Contract는 schema/skill/runtime/model profile 최소 집합으로 hash한다.
6. knowledge_generation은 Issue Version + Contract에 대한 deterministic retry lineage다.
7. retry는 별도 knowledge_attempt Entity로 보존한다.
8. knowledge_item과 knowledge_review는 Generation이 아니라 Attempt에 연결한다.
9. knowledge_item_id에는 statement를 넣지 않고 attempt/category/ordinal로 결정한다.
10. Attempt 본문 변경은 새 Attempt로 표현하며 기존 Attempt는 immutable이다.
11. 기존 M4 failed Attempt의 Knowledge 본문은 추정하지 않고 content_available=false로 명시한다.
12. 최종 PASS Attempt는 knowledge_generation.accepted_attempt_id가 가리킨다.
```

---

## M6-03 · Logical Schema Simplification / Integrity

상태: **DECIDED**

M6-03은 M7 SQLite 구현 직전에 남아 있던 정규화 수준과 무결성 표현을 결정한다. 원칙은 **현재 질의에 필요한 구조는 명시적으로 만들되, 아직 필요하지 않은 일반화는 하지 않는다**이다.

### 1. Custom Field array는 JSON text로 유지

현재 `custom_field_value`의 multi-value 속성은 다음처럼 유지한다.

```text
display_value
display_values_json
value_id
value_ids_json
user_keys_json
value_shape_json
```

M7에서는 `display_values`, `value_ids`, `user_keys`를 child table로 추가 normalize하지 않는다.

이유:

- 현재 주요 목적은 Knowledge Evidence round-trip과 Issue 단위 원문 복원이다.
- Custom Field 개별 array element를 SQL aggregation/filter 대상으로 삼아야 한다는 요구가 아직 없다.
- 이미 ANALYSIS 단계에서 타입/형태가 정규화되어 있다.
- EAV/child table을 미리 늘리면 loader와 migration만 복잡해진다.

향후 실제 질의에서 "특정 multi-user 값이 포함된 Issue" 같은 element-level filter가 필요해질 때만 분리한다.

### 2. Review category score는 고정 column 사용

현재 Review Schema의 점수는 의미가 고정된 소수 항목이므로 `knowledge_review`에 명시적 column으로 둔다.

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

Key/value child table로 만들지 않는다.

이유:

- 현재 category가 명확하고 개수가 작다.
- SQL에서 직접 비교/집계하기 쉽다.
- 타입과 nullability를 명확히 표현할 수 있다.
- 스키마가 실제로 바뀔 때 migration하는 편이 generic EAV를 미리 도입하는 것보다 단순하다.

### 3. Evidence integrity는 DB FK + resolver validator 혼합

`knowledge_evidence → knowledge_item` 관계는 일반 FK로 강제한다.

하지만 하나의 `source_entity_key`가 Comment/Attachment/Relationship/Custom Field/Issue Version 등 서로 다른 table을 가리키는 polymorphic FK는 만들지 않는다.

대신 M7은 다음 계약을 사용한다.

```text
DB constraint
- knowledge_evidence.knowledge_item_id FK
- evidence_type CHECK
- ordinal / uniqueness constraint

Resolver validator
- exact evidence_ref parse
- evidence_type과 reference 형식 일치 확인
- type별 source entity 존재 확인
- source_run_id / source_issue_key 조합 확인
- accepted Attempt의 모든 Evidence가 실제 source로 round-trip 되는지 확인
```

예:

```text
comment:5001
→ comment(source_run_id, source_issue_key, 5001)

custom_field:customfield_12345
→ custom_field_value(source_run_id, source_issue_key, field_id)

description
→ knowledge_generation.issue_version_id
→ issue_version.description
```

Accepted Knowledge에서 resolver가 하나라도 실패하면 M7 materialization/integrity test 실패로 처리한다.

### 4. `issue_version_observation`은 M7에서 실제 table로 구현

M6-01에서는 논리 Entity만 고정하고 M7 물리 구현 여부를 열어두었다. M6-02에서 `issue_version`을 content-addressed immutable state로 확정했으므로 Observation은 실제 temporal/run mapping에 필요하다.

따라서 M7에서 다음 table을 만든다.

```text
issue_version_observation
  run_id
  jira_id
  observed_issue_key
  issue_version_id

UNIQUE(run_id, jira_id)
```

이유:

- 같은 Version을 여러 Run에서 관찰한 사실을 중복 본문 없이 기록
- `A → B → A`처럼 기존 Version으로 돌아온 chronology 표현
- issue_key가 바뀌어도 당시 관찰된 key 보존
- 향후 증분 수집에서 current Version 계산 가능
- table 자체가 작고 loader 복잡도 증가가 매우 낮음

즉 이 table은 미래 기능을 위한 장식이 아니라 현재 Version 모델의 시간축을 담당한다.

### 5. Active Knowledge는 status column으로 표현

Boolean `is_active`만 두면 candidate/historical/review_required의 의미를 별도 컬럼으로 다시 만들어야 하고, 별도 current pointer table은 M7 MVP에 비해 구조가 늘어난다.

따라서 `knowledge_generation.state`를 사용한다.

허용 상태:

```text
candidate
active
historical
review_required
```

의미:

```text
candidate
  아직 publish Gate를 통과하지 않은 Generation

active
  일반 Retrieval에 노출되는 승인된 현재 Generation

historical
  과거에 active였거나 새 Generation에 의해 supersede된 Generation

review_required
  최대 Attempt 이후에도 자동 PASS하지 못한 Generation
```

Generation에는 authoritative Issue identity인 `jira_id`도 보존한다.

M7 SQLite에서는 부분 UNIQUE index로 Issue별 active Generation을 최대 하나로 제한한다.

개념적으로:

```sql
CREATE UNIQUE INDEX ...
ON knowledge_generation(jira_id)
WHERE state = 'active';
```

새 Version이 들어왔다고 기존 active를 즉시 내리지 않는다.

```text
기존 active G1
+ 새 Issue Version V2
+ candidate G2

G2 PASS 전
→ G1 active 유지

G2 PASS
→ 한 transaction에서 G1 historical
→ G2 active
```

따라서 DB의 "최신 source version"과 서비스의 "현재 승인 Knowledge"는 동일 개념이 아니다.

### 6. M6-03 최종 결정

```text
DECISION M6-03

1. Custom Field multi-value는 M7에서 JSON text로 유지한다.
2. Review category score는 knowledge_review의 고정 column으로 둔다.
3. polymorphic Evidence는 억지 FK 대신 exact ref + type-specific resolver validator로 검증한다.
4. accepted Attempt의 Evidence round-trip 실패는 integrity failure다.
5. issue_version_observation은 M7에서 실제 table로 구현한다.
6. Observation은 run_id + jira_id 기준으로 한 Run의 관찰 Version을 기록한다.
7. active Knowledge는 knowledge_generation.state로 표현한다.
8. state는 candidate / active / historical / review_required를 사용한다.
9. SQLite partial UNIQUE index로 Jira Issue당 active Generation 최대 1개를 보장한다.
10. 새 Version candidate가 생성돼도 PASS 전에는 기존 active Knowledge를 유지한다.
```

---

## 다음 결정

다음 단계는 **M6-04 · Logical Schema Consolidation / Gate Review**다.

해야 할 일:

- `docs/DB_LOGICAL_SCHEMA.md`를 M6-01~03 결정으로 v0.3에 통합
- 기존 `knowledge_generation → knowledge_item` 구조를 `generation → attempt → item/review`로 수정
- `issue_key` 중심 identity 표현을 `jira_id authoritative + issue_key locator`로 정리
- Entity/Cardinality/round-trip 검증 시나리오 재검토
- M6 Gate 항목을 실제로 체크하고 M7 인계 계약 확정
