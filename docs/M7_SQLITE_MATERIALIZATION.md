# M7 SQLite Materialization

기준일: 2026-08-25  
상태: **IMPLEMENTED / REAL-RUN VALIDATION IN PROGRESS**

M7은 M6에서 확정한 Logical Schema를 실제 SQLite DB로 materialize하는 단계다.

현재 SQLite 구현, synthetic integration test, **실데이터 Gate 자동 검증 명령**까지 준비했고 실제 Jira Pilot Run `20260804T043628Z`로 Gate를 진행 중이다. 실데이터 검증 과정에서 발견한 historical artifact 계약 위반은 원본을 사후 수정하지 않고 M7 compatibility layer와 Gate report에 명시적으로 반영한다.

> M7은 M5 `profile.json`을 machine-readable raw baseline으로 사용한다. 다만 M5가 raw Evidence ref를 세는 반면 SQLite는 M6의 `UNIQUE(knowledge_item_id, evidence_ref)` 계약을 지키므로, historical 중복 Evidence가 있으면 raw count와 canonical DB row count를 분리해 검증한다.

---

## 1. 구현 범위

```text
src/jira_collector/knowledge_db/
├─ ids.py          deterministic logical ID
├─ schema.py       SQLite schema v1
├─ loader.py       single-run materializer + legacy compatibility
├─ evidence.py     Evidence resolver / integrity
├─ validation.py   M5 raw baseline + canonical Evidence / DB Gate snapshot
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
tests/test_validate_knowledge.py
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
- M5 profile 기반 raw expected count 검증
- historical duplicate Evidence의 canonical materialization
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

Historical duplicate Evidence는 **첫 occurrence의 raw ordinal**을 사용해 `ke_`를 만들고 이후 동일 ref는 DB row로 만들지 않는다. 따라서 invalid historical duplicate가 있어도 원본 위치를 임의 재번호화하지 않는다.

---

## 5. Legacy M4 Artifact 처리

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

### 5.1 Review `critical_issues` nonconformance

M4 당시 Review Schema v0.3은 `critical_issues: string[]` 계약이었다. 그러나 실제 historical Review 2개에는 `{type, location, message}` object가 남아 있다.

```text
schema-conformant string
→ type="", location="", message=<string>

historical object
→ type=<type>, location=<location>, message=<message>
```

둘 다 `review_finding(finding_group='critical')`로 보존한다. `review_schema_version`은 당시 계약대로 `0.3`을 유지하며 원본 Review JSON은 수정하지 않는다.

### 5.2 Knowledge Evidence duplicate nonconformance

Knowledge Schema v0.1은 `evidence_refs.uniqueItems=true`이지만 실제 Pilot에는 단 1개 중복이 있다.

```text
AI5-1270.json
key_findings[2]

comment:2717096
comment:2720803
comment:2720803   ← duplicate
```

M3/M4 `validate_knowledge.py`가 중복 검사를 빠뜨렸기 때문에 통과한 historical artifact다.

처리 원칙:

```text
Historical Knowledge JSON
→ 수정하지 않음

knowledge_content_hash
→ raw JSON 전체를 그대로 hash

SQLite knowledge_evidence
→ 첫 occurrence만 materialize
→ 이후 동일 ref는 skip
→ 첫 occurrence의 raw ordinal 유지
```

DB의 `UNIQUE(knowledge_item_id, evidence_ref)` 계약은 완화하지 않는다. 향후 생성되는 Knowledge는 `validate_knowledge.py`에서 중복을 실패 처리한다.

상세 발견·결정 이력은 `docs/M7_REAL_RUN_LOG.md`를 따른다.

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

## 7. M5 raw baseline → M7 canonical DB 연결

M7 Gate는 다음 파일을 raw baseline으로 사용한다.

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

현재 Pilot에서 실제 확인한 값:

```text
Issue                       30
Generation                  30
Attempt                     37
Knowledge Item             285
M5 raw Evidence ref        503
M7 canonical Evidence row  502
Review                      37

Duplicate Evidence occurrence  1
Duplicate Knowledge Item       1
```

따라서 M7 Gate의 count 계약은 다음과 같다.

```text
Issue       = M5 issue_count
Generation  = M5 issue_count
Attempt     = M5 review_file_count
Item        = M5 total_statement_item_count
Review      = M5 review_file_count

M5 raw Evidence
= profile.knowledge.evidence.total_evidence_ref_count
= 실제 Knowledge JSON raw ref count와 일치해야 함

M7 DB Evidence
= 각 Knowledge Item 내부 exact evidence_ref를 첫 occurrence 기준으로 canonicalize한 count
```

이 분리는 M5 숫자를 바꾸기 위한 것이 아니다. M5는 당시 artifact의 **raw 관찰값 503**을 그대로 보존하고, M7은 M6 DB 무결성 계약에 맞는 **canonical row 502**를 별도로 만든다.

---

## 8. 자동 테스트 계약

Synthetic/targeted test에서 다음을 검증한다.

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

historical duplicate Evidence
→ 첫 occurrence만 materialize
→ raw ordinal 유지

legacy critical_issues object
→ type/location/message 손실 없이 review_finding 저장

새 Knowledge duplicate Evidence
→ validate_knowledge.py에서 FAIL

같은 Jira Issue에 active Generation 2개
→ SQLite IntegrityError

historical + active
→ 허용

M5 profile
→ raw expected count로 변환

Knowledge artifacts
→ raw/canonical Evidence count 계산

DB snapshot
→ FK / SQLite integrity / active / review_required / Evidence 상태 확인
```

이번 real-run compatibility 변경에 대한 최종 targeted test와 전체 pytest는 로컬에서 다시 확인한 뒤 M7 Gate를 닫는다.

---

## 9. 권장 실데이터 Gate 실행

현재 Pilot Run:

```text
20260804T043628Z
```

프로젝트 루트에서 한 번 실행한다. Tool은 `src` layout을 자체 bootstrap하므로 별도 `PYTHONPATH` 설정이 필요하지 않다.

PowerShell 한 줄 실행:

```powershell
python tools/jira_knowledge/validate_m7_real_run.py --run-id 20260804T043628Z --data-root data --skill-version 0.9 --runtime-version 0.9 --model-profile legacy-m4-unrecorded --reset
```

당시 정확한 model profile metadata가 보존되지 않았으므로 현재 Pilot Gate에서는:

```text
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
3. M5 raw expected count 계산
4. Knowledge JSON의 raw/canonical Evidence count 계산
5. M5 raw Evidence == artifact raw Evidence 확인
6. canonical DB expected count 계산
7. 전용 validation SQLite 생성
8. Run 1차 materialize
9. DB snapshot / FK / Evidence / SQLite integrity 검사
10. 같은 Run 2차 materialize
11. DB snapshot 재검사
12. 1차 == 2차 snapshot 확인
13. active Generation == Issue count 확인
14. review_required == 0 확인
15. Gate JSON report 저장
```

Gate JSON에는 다음 세 층이 함께 남는다.

```text
m5_raw_expected
→ M5 profile raw count

evidence_canonicalization
→ raw_evidence_ref_count
→ canonical_evidence_count
→ duplicate_evidence_ref_count
→ duplicate_item_count

expected
→ 실제 SQLite row 기준 expected count
```

DB snapshot에는 다음이 포함된다.

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
  "evidence_canonicalization": {
    "raw_evidence_ref_count": 503,
    "canonical_evidence_count": 502,
    "duplicate_evidence_ref_count": 1,
    "duplicate_item_count": 1
  },
  "idempotent": true,
  "failures": []
}
```

그리고 `m5_raw_expected`, `expected`, `first_snapshot`, `second_snapshot` 상세가 함께 출력 및 report 파일에 저장된다.

실패 시 `failures[]`에 사람이 바로 볼 수 있는 차이를 남긴다.

예:

```text
M5 raw evidence count mismatch: profile=503, artifacts=502
knowledge_item_count: expected=285, actual=284
active_generation_count: expected=30, actual=29
accepted_evidence_failure_count: expected=0, actual=1
same-run idempotency failure: first/second DB snapshot differs
```

M7 Gate 결과를 대화에 전달할 때는 가능하면 **전체 stdout 또는 `.gate.json` 내용**을 사용한다.

---

## 12. 저수준 materialize 명령

Gate 디버깅이나 DB 직접 확인이 필요할 때만 사용한다.

```powershell
python tools/jira_knowledge/materialize_knowledge_db.py --run-id 20260804T043628Z --data-root data --database data/knowledge_db/jira_knowledge.sqlite3 --skill-version 0.9 --runtime-version 0.9 --model-profile legacy-m4-unrecorded
```

일반 M7 완료 판정에는 `validate_m7_real_run.py`를 우선한다.

---

## 13. M7 Gate

자동 구현/검증:

- [x] SQLite schema v1 구현
- [x] deterministic ID utility
- [x] source / version loader
- [x] Generation / Attempt loader
- [x] Knowledge / Review loader
- [x] same-run idempotency test
- [x] Evidence 6종 round-trip integration test
- [x] broken Evidence rollback test
- [x] active Generation DB-level uniqueness test
- [x] M5 profile → raw expected count validator
- [x] Knowledge raw/canonical Evidence count validator
- [x] legacy Critical Finding compatibility
- [x] historical duplicate Evidence canonical materialization
- [x] future Knowledge duplicate validator
- [x] DB FK / SQLite integrity / active state snapshot validator
- [x] one-command real-run Gate tool

실데이터 검증:

- [ ] targeted tests 재실행 PASS
- [ ] `validate_m7_real_run.py` status = PASS
- [ ] M5 raw baseline과 artifact raw count 일치
- [ ] canonical DB count 일치
- [ ] 동일 Run 2회 snapshot 동일
- [ ] active Generation = Issue count
- [ ] review_required = 0
- [ ] Evidence failure = 0
- [ ] foreign key failure = 0
- [ ] SQLite integrity = ok

## **M7 Gate: IN PROGRESS / REAL-RUN VALIDATION**

실데이터 Gate가 통과하면 결과를 기록하고 M7을 DONE으로 닫는다. 그 뒤에만 **M8 · Knowledge Item / Chunk 전략 + BGE-M3**로 이동한다.
