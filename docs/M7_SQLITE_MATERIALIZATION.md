# M7 SQLite Materialization

기준일: 2026-08-25  
상태: **IMPLEMENTED / REAL-RUN VALIDATION PENDING**

M7은 M6에서 확정한 Logical Schema를 실제 SQLite DB로 materialize하는 단계다.

현재 구현과 synthetic integration test는 완료했다. 다만 실제 Jira 30건 Run의 원본/Knowledge 데이터는 Git에 포함되지 않으므로 **실데이터 Gate는 사용자 로컬 환경에서 1회 검증한 뒤 PASS 처리한다.**

---

## 1. 구현 범위

```text
src/jira_collector/knowledge_db/
├─ ids.py        deterministic logical ID
├─ schema.py     SQLite schema v1
├─ loader.py     single-run materializer
├─ evidence.py   Evidence resolver / integrity
└─ models.py     error / result model
```

실행 도구:

```text
tools/jira_knowledge/materialize_knowledge_db.py
```

테스트:

```text
tests/knowledge_db/test_ids.py
tests/knowledge_db/test_schema.py
tests/knowledge_db/test_materializer.py
```

---

## 2. 현재 M7 경계

M7은 **지정 Run 하나를 정확히 SQLite로 materialize**하는 Functional MVP다.

포함:

- ANALYSIS source Entity 적재
- Knowledge Input `source_hash` 기반 Issue Version
- deterministic ID
- `issue_version_observation`
- Generation / Attempt 분리
- 최종 Knowledge Item / Evidence 적재
- 과거 failed Attempt Review 보존
- Review Finding materialization
- idempotent same-run reload
- active Generation partial UNIQUE constraint
- Evidence round-trip validation
- transaction rollback on integrity failure

아직 포함하지 않음:

- 여러 Run의 자동 chronology/current 계산
- 변경분 자동 수집
- source_hash 기반 incremental orchestration
- Chunk / Embedding / FAISS
- M14 수준 atomic publish/rollback orchestration

여러 Run 운영은 M11~M14 책임이다. M7에서 미리 구현하지 않는다.

---

## 3. SQLite Schema v1

주요 table:

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

핵심 제약:

```text
issue.jira_id
→ authoritative identity

issue_version
→ UNIQUE(jira_id, source_hash)

issue_version_observation
→ PRIMARY KEY(run_id, jira_id)

knowledge_attempt
→ UNIQUE(knowledge_generation_id, attempt_no)

knowledge_item
→ UNIQUE(knowledge_attempt_id, category, ordinal)

knowledge_evidence
→ UNIQUE(knowledge_item_id, ordinal)
→ UNIQUE(knowledge_item_id, evidence_ref)

knowledge_review
→ UNIQUE(knowledge_attempt_id)
```

Active Generation:

```sql
CREATE UNIQUE INDEX ux_knowledge_generation_active_issue
ON knowledge_generation(jira_id)
WHERE state = 'active';
```

따라서 application bug가 있어도 한 Jira Issue에 `active` Generation이 두 개 존재할 수 없다.

---

## 4. Deterministic ID

공통 규칙:

```text
canonical JSON
+ id_schema_version=1
+ entity kind
→ UTF-8
→ SHA-256 full lowercase hex
```

Prefix:

```text
iv_  Issue Version
kc_  Knowledge Contract
kg_  Knowledge Generation
ka_  Knowledge Attempt
ki_  Knowledge Item
ke_  Knowledge Evidence
```

동일 입력을 다시 materialize하면 같은 logical ID를 얻는다.

---

## 5. Legacy M4 Attempt 처리

현재 M4 artifact 구조:

```text
issues/<ISSUE_KEY>.json
reviews/<ISSUE_KEY>.review.attempt<N>.json
```

최종 Knowledge만 남고 failed Attempt 당시 Knowledge body는 남지 않는다.

따라서 M7은 다음처럼 정직하게 적재한다.

```text
Attempt 1 FAIL
→ Attempt row
→ Review / Finding row
→ content_available = false

Attempt 2 PASS
→ Attempt row
→ Review / Finding row
→ Knowledge Item / Evidence
→ content_available = true
→ accepted_attempt_id
→ Generation active
```

없는 과거 Knowledge를 추정 복원하지 않는다.

---

## 6. Evidence resolver

Accepted Attempt에 대해 6개 Evidence type을 모두 실제 source와 연결한다.

```text
summary
→ issue_version

description
→ issue_version

comment:<id>
→ comment(run_id, issue_key, comment_id)

attachment:<id>
→ attachment(run_id, attachment_id)
→ 소유 issue_key까지 확인

relationship:<id>
→ relationship(run_id, relationship_id)
→ 현재 issue_key가 source/target endpoint인지 확인

custom_field:<field_id>
→ custom_field_value(run_id, issue_key, field_id)
```

하나라도 실패하면 전체 materialization transaction을 rollback한다.

---

## 7. 자동 테스트 결과

Synthetic integration test에서 다음을 검증한다.

```text
동일 Run 2회 materialize
→ row count 증가 없음
→ logical ID 유지

2 Attempt
→ Attempt 1 content_available=false
→ Attempt 2 content_available=true
→ final Generation active

Evidence 6종
→ summary PASS
→ description PASS
→ comment PASS
→ attachment PASS
→ relationship PASS
→ custom_field PASS

잘못된 comment:<id>
→ Evidence round-trip failure
→ transaction rollback

같은 Jira Issue에 active Generation 2개 INSERT
→ SQLite IntegrityError

historical + active
→ 허용
```

GitHub Actions의 전체 `pytest`로 검증한다.

---

## 8. 실제 Run 실행

현재 Pilot Run:

```text
20260804T043628Z
```

실행 예:

```bash
python tools/jira_knowledge/materialize_knowledge_db.py \
  --run-id 20260804T043628Z \
  --data-root data \
  --database data/knowledge_db/jira_knowledge.sqlite3 \
  --skill-version 0.9 \
  --runtime-version 0.9 \
  --model-profile <실제-M4-모델-프로필>
```

`model_profile`은 Generation identity 일부이므로 자동 추정하지 않는다.

당시 정확한 profile이 artifact에 기록되지 않았다면 역사적 baseline임을 명시해서 다음처럼 사용할 수 있다.

```text
legacy-m4-unrecorded
```

이는 모델을 추측한다는 뜻이 아니라 **당시 model profile metadata가 보존되지 않았음**을 identity에 명시하는 값이다.

---

## 9. 정상 출력 예

```json
{
  "run_id": "20260804T043628Z",
  "database": ".../data/knowledge_db/jira_knowledge.sqlite3",
  "issue_count": 30,
  "generation_count": 30,
  "attempt_count": 37,
  "knowledge_item_count": 285,
  "evidence_count": 503,
  "review_count": 37,
  "status": "completed"
}
```

위 숫자는 M5 Profile과 일치해야 한다.

특히 다음은 강한 regression check다.

```text
Issue              30
Generation         30
Attempt            37
Knowledge Item    285
Evidence           503
Review              37
```

---

## 10. 실제 Run 검증 절차

첫 실행:

```text
materialize
→ completed
→ M5 count와 비교
```

두 번째 동일 실행:

```text
같은 명령 재실행
→ completed
→ row count 변화 없음
→ immutable drift 없음
```

DB 확인:

```sql
SELECT COUNT(*) FROM issue;
SELECT COUNT(*) FROM issue_version;
SELECT COUNT(*) FROM knowledge_generation;
SELECT COUNT(*) FROM knowledge_attempt;
SELECT COUNT(*) FROM knowledge_item;
SELECT COUNT(*) FROM knowledge_evidence;
SELECT COUNT(*) FROM knowledge_review;
```

기대 핵심:

```text
active Generation = 30
review_required = 0
Evidence resolver failure = 0
```

---

## 11. M7 Gate

자동 검증:

- [x] SQLite schema v1 구현
- [x] deterministic ID utility
- [x] source / version loader
- [x] Generation / Attempt loader
- [x] Knowledge / Review loader
- [x] same-run idempotency test
- [x] Evidence 6종 round-trip integration test
- [x] broken Evidence rollback test
- [x] active Generation DB-level uniqueness test
- [x] GitHub Actions 전체 pytest PASS

실데이터 검증:

- [ ] `20260804T043628Z` 30 Issue materialize 성공
- [ ] M5 count `30 / 37 / 285 / 503 / 37` 일치
- [ ] 동일 명령 2회 실행 후 row count 불변
- [ ] active Generation 30 / review_required 0
- [ ] Evidence round-trip failure 0

## **M7 Gate: PENDING REAL-RUN VALIDATION**

실데이터 Gate가 통과하면 M7을 DONE으로 닫고 다음은 **M8 · Chunk + BGE-M3**로 이동한다.
