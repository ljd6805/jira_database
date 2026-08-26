# M7 Real-run Validation Log

기준일: 2026-08-26  
상태: **COMPLETE / PASS**

대상 Pilot Run: `20260804T043628Z`

이 문서는 M7 SQLite Materialization의 실제 Jira Pilot 검증에서 발견한 문제, 해결 결정, 최종 Gate 결과를 시간 순서대로 기록한다. 실제 Jira Issue Key, Review 본문, 원문 내용은 기록하지 않고 aggregate 정보만 보존한다.

---

## 1. Preflight

```text
Knowledge issue JSON = 30
Review JSON          = 37
```

M5 baseline과 동일한 입력 집합이 존재함을 확인했다.

---

## 2. 실행 문제 1 — src layout import 실패

최초 실행에서 tool script가 `src/jira_collector`를 import하지 못했다.

결정/해결:

- 사용자 환경 문제로 넘기지 않고 one-command Gate 실행성 결함으로 처리했다.
- `validate_m7_real_run.py`, `materialize_knowledge_db.py`가 repository `src` 경로를 자체 bootstrap하도록 수정했다.

---

## 3. 실행 문제 2 — Review Schema v0.3 historical nonconformance

실데이터 37개 Review를 검사한 결과 historical Review 2개에서 `critical_issues`가 Schema v0.3의 `string[]` 계약과 달리 object 형태로 남아 있음을 확인했다.

Git history를 확인한 결과 M4 당시 계약도 이미 Review Schema v0.3이었다. 따라서 이는 옛 schema가 아니라 실제 Reviewer output의 nonconformance다.

결정:

```text
Review 원본 JSON
→ 사후 수정하지 않음

review_schema_version
→ 당시 계약대로 0.3 유지

M7 compatibility
string critical_issue
→ message로 보존

object critical_issue
→ type/location/message를 review_finding에 보존
```

회귀 방지 integration test를 추가했다.

---

## 4. 실행 문제 3 — Knowledge Evidence 중복 1회

30개 Knowledge JSON 전체 진단 결과:

```text
Knowledge files           30
M5 raw Evidence refs     503
Unique per-item refs     502
Duplicate occurrences      1
Items with duplicates      1
```

Knowledge Schema v0.1은 `evidence_refs.uniqueItems=true`였지만 M3/M4 `validate_knowledge.py`가 중복 검사를 구현하지 않아 historical artifact로 남았다.

결정:

```text
Historical Knowledge JSON
→ 수정하지 않음

M5 profile
→ raw 관찰값 503 유지

M7 SQLite
→ 동일 Item의 exact evidence_ref는 첫 occurrence만 materialize
→ 첫 occurrence raw ordinal 유지
→ canonical Evidence row = 502

DB UNIQUE(knowledge_item_id, evidence_ref)
→ 완화하지 않음
```

향후 새 Knowledge는 `validate_knowledge.py`에서 duplicate Evidence를 FAIL 처리하도록 수정했다.

---

## 5. 최종 M7 Real-run Gate

2026-08-26 최종 실행 결과:

```text
M5 raw expected
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

SQLite first snapshot
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

SQLite second snapshot
= first snapshot

Idempotent         true
Failures           []
```

Gate 판정:

```text
M7_REAL_RUN = PASS
```

`failures=[]`이고 first/second snapshot이 동일하며, active Generation 30/30, review_required 0, accepted Evidence failure 0, foreign key failure 0, SQLite integrity OK를 확인했다.

---

## 6. M7 Closure 결정

```text
M0~M7  DONE
M8     CURRENT / READY TO START
M9     PLAN
M10    Functional MVP Gate
```

M8은 M7의 active accepted Knowledge를 입력으로 Chunk 전략과 BGE-M3 embedding을 검증하는 단계다. M7 완료와 동시에 M8 구현을 자동 시작하지는 않는다.

---

## 7. 핵심 교훈

이번 real-run Gate에서 synthetic test만으로는 발견하지 못한 두 historical contract drift를 실제 데이터로 찾았다.

1. Review Schema v0.3 `critical_issues` nonconformance 2건
2. Knowledge Schema v0.1 duplicate Evidence 1건

처리 원칙:

```text
과거 artifact를 사후 수정하지 않는다.
DB contract를 약하게 만들지 않는다.
compatibility layer로 history를 보존한다.
미래 생성물은 deterministic validator를 강화해 차단한다.
```

이 기록을 M7 완료 근거로 보존한다.
