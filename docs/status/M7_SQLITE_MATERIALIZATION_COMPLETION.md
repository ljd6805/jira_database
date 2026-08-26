# M7 SQLite Materialization Completion Record

기준일: 2026-08-26  
상태: **DONE**

대상 Pilot Run: `20260804T043628Z`

## 1. M7 목적

M6에서 확정한 Logical Schema를 실제 SQLite Schema v1, deterministic loader, Evidence integrity, real-run Gate로 구현하고 실제 Jira Pilot 30건으로 검증한다.

## 2. 구현 완료 범위

```text
src/jira_collector/knowledge_db/
├─ ids.py
├─ schema.py
├─ loader.py
├─ evidence.py
├─ validation.py
└─ models.py

tools/jira_knowledge/
├─ materialize_knowledge_db.py
└─ validate_m7_real_run.py
```

완료 항목:

- 15개 SQLite table
- `jira_id` authoritative identity
- `source_hash` 기반 Issue Version
- deterministic `iv_/kc_/kg_/ka_/ki_/ke_` ID
- Generation / Attempt 분리
- failed Attempt Review history 보존
- accepted Attempt Knowledge Item / Evidence 저장
- Issue당 active Generation 최대 1개 partial UNIQUE
- 6종 Evidence source round-trip
- integrity failure transaction rollback
- same-run idempotent materialization
- M5 raw baseline + canonical Evidence count 분리
- one-command real-run Gate

## 3. 실제 Pilot Gate 결과

```text
M5 raw baseline
Issue              30
Generation         30
Attempt            37
Knowledge Item    285
Evidence raw      503
Review             37

M7 canonical DB
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
SQLite Integrity    OK
Same-run idempotent true
Failures            []
```

## 4. raw 503 vs canonical 502

Pilot Knowledge 30건 중 단 하나의 Item에 동일 `evidence_ref`가 한 번 중복되어 있었다.

```text
AI5-1270.json
key_findings[2]

comment:2717096
comment:2720803
comment:2720803
```

Knowledge Schema v0.1은 `uniqueItems=true`였지만 과거 Validator가 중복 검사를 누락했다.

결정:

```text
Historical JSON     → 수정하지 않음
M5 raw count        → 503 유지
M7 canonical rows   → 502
DB UNIQUE contract  → 유지
Future Validator    → duplicate FAIL
```

## 5. Review legacy compatibility

M4 Review 2개에서 Schema v0.3의 `critical_issues: string[]` 계약과 달리 object가 남아 있었다.

원본은 수정하지 않고 M7 compatibility layer가 object의 `type/location/message`를 `review_finding`에 보존한다. `review_schema_version=0.3`은 당시 계약 그대로 유지한다.

## 6. Gate 판정

```text
M7_REAL_RUN = PASS
M7 = DONE
```

완료 근거:

- first/second DB snapshot 동일
- active Generation 30/30
- review_required 0
- accepted Evidence failure 0
- foreign key failure 0
- `PRAGMA integrity_check = ok`
- `failures=[]`

상세 실행 이력: `docs/M7_REAL_RUN_LOG.md`

## 7. 다음 단계

```text
M0~M7  DONE
M8     CURRENT / READY TO START
```

M8의 책임은 active accepted Knowledge를 기준으로 **embedding unit / Chunk 전략을 결정하고 BGE-M3 embedding을 구축·검증**하는 것이다. FAISS는 M9 책임이며 M8에 섞지 않는다.
