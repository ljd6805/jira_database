# M7 SQLite Materialization

기준일: 2026-08-26  
상태: **DONE**

M7은 M6에서 확정한 Logical Schema를 실제 SQLite DB로 materialize하고, 실제 Jira Pilot Run `20260804T043628Z`로 무결성과 재현성을 검증한 단계다.

최종 Gate 결과:

```text
M7_REAL_RUN = PASS
```

실제 Jira Issue Key, Review 본문, 원문 내용은 문서에 기록하지 않고 aggregate 결과만 보존한다.

---

## 1. 구현 범위

```text
src/jira_collector/knowledge_db/
├─ ids.py          deterministic logical ID
├─ schema.py       SQLite schema v1
├─ loader.py       single-run materializer + legacy compatibility
├─ evidence.py     Evidence resolver / integrity
├─ validation.py   raw/canonical baseline + DB Gate snapshot
└─ models.py

tools/jira_knowledge/
├─ materialize_knowledge_db.py
└─ validate_m7_real_run.py
```

완료 범위:

- 15개 SQLite table
- `jira_id` authoritative identity
- `source_hash` 기반 Issue Version
- `issue_version_observation`
- deterministic `iv_/kc_/kg_/ka_/ki_/ke_`
- Generation / Attempt 분리
- failed Attempt Review history 보존
- accepted Attempt Knowledge Item / Evidence materialization
- active Generation partial UNIQUE
- 6종 Evidence round-trip
- integrity failure transaction rollback
- same-run idempotency
- M5 raw baseline + M7 canonical Evidence 분리
- one-command real-run Gate

---

## 2. SQLite Schema v1

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

Issue당 active Generation은 partial UNIQUE index로 최대 1개만 허용한다.

---

## 3. Deterministic ID

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

공통 규칙:

```text
id_schema_version=1
kind 포함
canonical JSON UTF-8
sort_keys=true
SHA-256 full lowercase hex
```

Timestamp는 logical ID material에 포함하지 않는다.

---

## 4. Legacy M4 Artifact 보존 원칙

M4에는 failed Attempt 당시 Knowledge body가 남지 않았다.

```text
failed Attempt
→ Attempt / Review / Finding 보존
→ content_available=false

accepted final Attempt
→ Knowledge Item / Evidence 보존
→ content_available=true
```

없는 과거 Knowledge는 추정 복원하지 않는다.

### 4.1 Review Schema v0.3 nonconformance

실제 historical Review 2개에서 `critical_issues`가 당시 Schema v0.3의 `string[]` 계약과 달리 object 형태로 남아 있었다.

원본 JSON은 수정하지 않고 M7 compatibility layer가 string/object 양쪽을 `review_finding`에 손실 없이 보존한다. `review_schema_version=0.3`은 당시 계약 그대로 유지한다.

### 4.2 Duplicate Evidence nonconformance

Knowledge Schema v0.1은 `evidence_refs.uniqueItems=true`였지만 Pilot에는 단 1개의 duplicate Evidence가 있었다.

처리 원칙:

```text
Historical JSON
→ 수정하지 않음

M5 raw profile
→ 503 유지

M7 SQLite
→ 같은 Item의 exact evidence_ref는 첫 occurrence만 materialize
→ 첫 occurrence raw ordinal 유지
→ canonical Evidence row 502

DB UNIQUE contract
→ 완화하지 않음
```

향후 새 Knowledge는 `validate_knowledge.py`에서 duplicate Evidence를 FAIL 처리한다.

---

## 5. Evidence Resolver

Accepted Attempt의 6개 Evidence type은 실제 source까지 round-trip해야 한다.

```text
summary
→ issue_version

description
→ issue_version

comment:<id>
→ comment(run_id, issue_key, comment_id)

attachment:<id>
→ attachment(run_id, attachment_id)

relationship:<id>
→ relationship(run_id, relationship_id)

custom_field:<field_id>
→ custom_field_value(run_id, issue_key, field_id)
```

하나라도 실패하면 materialization transaction 전체를 rollback한다.

---

## 6. M5 raw baseline과 M7 canonical DB

최종 Pilot 값:

```text
M5 raw baseline
Issue              30
Generation         30
Attempt            37
Knowledge Item    285
Evidence raw      503
Review             37

Evidence canonicalization
Raw refs          503
Canonical rows    502
Duplicate refs      1
Duplicate items     1
```

M5 `503`은 당시 artifact의 raw 관찰값이고, M7 `502`는 M6 DB 무결성 계약에 따라 canonicalize된 실제 SQLite row 수다. 둘 중 하나를 다른 값으로 덮어쓰지 않는다.

---

## 7. 최종 Real-run Gate

실행 명령:

```powershell
python tools/jira_knowledge/validate_m7_real_run.py --run-id 20260804T043628Z --data-root data --skill-version 0.9 --runtime-version 0.9 --model-profile legacy-m4-unrecorded --reset
```

최종 결과:

```text
first_snapshot
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
Integrity          true

second_snapshot
= first_snapshot

idempotent         true
failures           []
```

따라서:

```text
M7_REAL_RUN = PASS
M7 = DONE
```

상세 과정은 `docs/M7_REAL_RUN_LOG.md`, 완료 기록은 `docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md`를 참조한다.

---

## 8. M7 Gate 완료 체크

- [x] SQLite Schema v1
- [x] deterministic ID
- [x] source / version loader
- [x] Generation / Attempt loader
- [x] Knowledge / Review loader
- [x] same-run idempotency
- [x] Evidence 6종 round-trip
- [x] broken Evidence rollback
- [x] active Generation uniqueness
- [x] M5 raw baseline validation
- [x] duplicate Evidence canonicalization
- [x] legacy Review compatibility
- [x] actual 30-issue real-run PASS
- [x] active Generation = 30
- [x] review_required = 0
- [x] Evidence failure = 0
- [x] foreign key failure = 0
- [x] SQLite integrity = ok

---

## 9. 다음 단계

```text
M0~M7  DONE
M8     CURRENT / READY TO START
```

M8 책임:

```text
active accepted Knowledge
→ embedding unit / Chunk 전략 결정
→ BGE-M3 embedding
→ embedding 품질/재현성 검증
```

FAISS index와 Retrieval은 M9 책임이며 M8에 섞지 않는다.
