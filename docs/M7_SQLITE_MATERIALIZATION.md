# M7 SQLite Materialization

기준일: 2026-08-25  
상태: **IMPLEMENTED / REAL-RUN VALIDATION PENDING**

M7은 M6에서 확정한 Logical Schema를 실제 SQLite DB로 materialize하는 단계다.

현재 SQLite 구현, synthetic integration test, **실데이터 Gate 자동 검증 명령**까지 준비했다. 실제 Jira 30건 데이터는 Git에 포함되지 않으므로 최종 Gate만 사용자 로컬 환경에서 실행한다.

> M7의 expected count를 문서에 다시 하드코딩해 판단하지 않는다. M5 `profile.json`을 machine-readable baseline으로 읽어 M7 DB 결과와 비교한다.

---

## 1. 구현 범위

```text
src/jira_collector/knowledge_db/
├─ ids.py          deterministic logical ID
├─ schema.py       SQLite schema v1
├─ loader.py       single-run materializer
├─ evidence.py     Evidence resolver / integrity
├─ validation.py   M5 profile → expected / DB Gate snapshot
└─ models.py       error / result model
```

실행 도구:

```text
tools/jira_knowledge/materialize_knowledge_db.py
tools/jira_knowledge/validate_m7_real_run.py
```

테스트:

```text
tests/knowledge_db/test_ids.py
tests/knowledge_db/test_schema.py
tests/knowledge_db/test_materializer.py
tests/knowledge_db/test_validation.py
```

---

## 2. 현재 M7 경계

M7은 **지정 Run 하나를 정확히 SQLite로 materialize하고 검증**하는 Functional MVP다.

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
- M5 profile 기반 expected count 검증
- SQLite `foreign_key_check` / `integrity_check`
- 동일 Run 2회 DB snapshot 비교
- Gate 결과 JSON report

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

ID ladder:

```text
jira_id
  ↓
iv_  Issue Version
  ↓
kc_  Knowledge Contract
  ↓
kg_  Knowledge Generation
  ↓
ka_  Knowledge Attempt + attempt_no
  ↓
ki_  Knowledge Item
  ↓
ke_  Knowledge Evidence
```

같은 Generation의 재생성 회차는 `knowledge_attempt_id`로 분리한다.

```text
kg_...
├─ ka_(attempt_no=1)
├─ ka_(attempt_no=2)
└─ ka_(attempt_no=3)
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

따라서 M7은 다음처럼 적재한다.

```text
Attempt 1 FAIL
→ Attempt row
→ Review / Finding row
→ content_available = false

Attempt N PASS
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

Accepted Attempt에 대해 6개 Evidence type을 실제 source와 연결한다.

```text
summary
→ issue_version

description
→ issue_version

comment:<id>
→ comment(run_id, issue_key, comment_id)

attachment:<id>
→ attachment(run_id, attachment_id)
→ 소유 issue_key 확인

relationship:<id>
→ relationship(run_id, relationship_id)
→ 현재 issue_key가 source/target endpoint인지 확인

custom_field:<field_id>
→ custom_field_value(run_id, issue_key, field_id)
```

하나라도 실패하면 materialization transaction을 rollback한다.

---

## 7. M5 → M7 baseline 연결

M7 Gate는 다음 파일을 기본 baseline으로 사용한다.

```text
data/knowledge/runs/<run_id>/profile.json
```

M5 profile에서 자동으로 읽는 값:

```text
knowledge.issue_count
review.review_file_count
knowledge.total_statement_item_count
knowledge.evidence.total_evidence_ref_count
integrity.ok
```

M7 expected mapping:

```text
Issue       = M5 issue_count
Generation  = M5 issue_count
Attempt     = M5 review_file_count
Item        = M5 total_statement_item_count
Evidence    = M5 total_evidence_ref_count
Review      = M5 review_file_count
```

현재 Pilot M5 profile 기준 결과는 결과적으로 다음과 같다.

```text
Issue               30
Generation          30
Attempt             37
Knowledge Item     285
Evidence            503
Review               37
```

중요한 것은 숫자를 코드에 다시 적는 것이 아니라 **M5 profile contract를 M7이 직접 소비한다는 점**이다.

---

## 8. 자동 테스트 결과

Synthetic test에서 다음을 검증한다.

```text
동일 Run 2회 materialize
→ row count 증가 없음
→ logical ID 유지

Generation / Attempt
→ failed Attempt content_available=false
→ accepted Attempt content_available=true
→ final Generation active

Evidence 6종
→ 모두 source round-trip PASS

잘못된 Evidence
→ Evidence round-trip failure
→ transaction rollback

같은 Jira Issue에 active Generation 2개
→ SQLite IntegrityError

historical + active
→ 허용

M5 profile
→ expected count로 변환

DB snapshot
→ FK / SQLite integrity / active / review_required / Evidence 상태 확인
```

GitHub Actions 전체 `pytest` PASS를 유지한다.

---

## 9. 권장 실데이터 Gate 실행

현재 Pilot Run:

```text
20260804T043628Z
```

이제 수동으로 materialize 명령을 두 번 실행하고 SQL 숫자를 비교할 필요가 없다.

프로젝트 루트에서 한 번 실행한다.

```bash
python tools/jira_knowledge/validate_m7_real_run.py \
  --run-id 20260804T043628Z \
  --data-root data \
  --skill-version 0.9 \
  --runtime-version 0.9 \
  --model-profile <실제-M4-모델-프로필> \
  --reset
```

당시 정확한 model profile metadata가 보존되지 않았다면:

```bash
--model-profile legacy-m4-unrecorded
```

를 사용한다.

이는 모델을 추측하는 값이 아니라 **당시 model profile metadata가 기록되지 않았음**을 contract에 명시하는 값이다.

기본 검증 DB:

```text
data/knowledge_db/validation/20260804T043628Z.sqlite3
```

기본 결과 report:

```text
data/knowledge_db/validation/20260804T043628Z.gate.json
```

기존 validation DB가 있으면 실수로 이전 상태를 재사용하지 않도록 기본적으로 실패한다. 새로운 Gate 실행은 `--reset`으로 명시한다.

---

## 10. Gate 명령이 자동 수행하는 것

```text
1. M5 profile.json 읽기
2. integrity.ok 확인
3. expected count 계산
4. 전용 validation SQLite 생성
5. Run 1차 materialize
6. DB snapshot / FK / Evidence / SQLite integrity 검사
7. 같은 Run 2차 materialize
8. DB snapshot 재검사
9. 1차 == 2차 snapshot 확인
10. active Generation == Issue count 확인
11. review_required == 0 확인
12. Gate JSON report 저장
```

검증 snapshot에는 다음이 포함된다.

```text
issue_count
generation_count
attempt_count
knowledge_item_count
evidence_count
review_count
active_generation_count
review_required_count
accepted_evidence_failure_count
foreign_key_failure_count
integrity_ok
```

---

## 11. PASS 출력의 핵심

성공 시:

```json
{
  "gate": "M7_REAL_RUN",
  "run_id": "20260804T043628Z",
  "status": "PASS",
  "idempotent": true,
  "failures": []
}
```

그리고 expected / first_snapshot / second_snapshot 상세가 함께 출력 및 report 파일에 저장된다.

실패 시 `failures[]`에 사람이 바로 볼 수 있는 차이를 남긴다.

예:

```text
knowledge_item_count: expected=285, actual=284
active_generation_count: expected=30, actual=29
accepted_evidence_failure_count: expected=0, actual=1
same-run idempotency failure: first/second DB snapshot differs
```

M7 Gate 결과를 대화에 전달할 때는 가능하면 **전체 stdout 또는 `.gate.json` 내용**을 사용한다.

---

## 12. 저수준 materialize 명령

Gate 디버깅이나 DB 직접 확인이 필요할 때만 사용한다.

```bash
python tools/jira_knowledge/materialize_knowledge_db.py \
  --run-id 20260804T043628Z \
  --data-root data \
  --database data/knowledge_db/jira_knowledge.sqlite3 \
  --skill-version 0.9 \
  --runtime-version 0.9 \
  --model-profile <실제-M4-모델-프로필>
```

일반 M7 완료 판정에는 `validate_m7_real_run.py`를 우선한다.

---

## 13. M7 Gate

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
- [x] M5 profile → M7 expected count validator
- [x] DB FK / SQLite integrity / active state snapshot validator
- [x] one-command real-run Gate tool
- [x] GitHub Actions 전체 pytest PASS

실데이터 검증:

- [ ] `validate_m7_real_run.py` status = PASS
- [ ] M5 baseline과 DB count 일치
- [ ] 동일 Run 2회 snapshot 동일
- [ ] active Generation = Issue count
- [ ] review_required = 0
- [ ] Evidence failure = 0
- [ ] foreign key failure = 0
- [ ] SQLite integrity = ok

## **M7 Gate: PENDING REAL-RUN VALIDATION**

실데이터 Gate가 통과하면 결과를 기록하고 M7을 DONE으로 닫는다. 그 뒤에만 **M8 · Knowledge Item / Chunk 전략 + BGE-M3**로 이동한다.
