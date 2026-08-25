# M6 DB Logical Schema Completion Record

기준일: 2026-08-25  
대상 기준 Run: `20260804T043628Z`

이 문서는 M6 DB Logical Schema 단계의 **완료 시점 설계 결정과 M7 SQLite Materialization 인계 계약**을 고정 기록한다.

> M0~M5의 기존 입력·프롬프트·문제·해결·완료 기록은 삭제하지 않는다. M6 내부 초안과 변경 이유는 `docs/M6_DECISION_LOG.md`, 최종 현재 모델은 `docs/DB_LOGICAL_SCHEMA.md`를 기준으로 한다.

---

## 1. M6 목적

M6는 SQLite DDL을 바로 작성하는 단계가 아니다.

M5 실제 Knowledge/Review 분포를 근거로 다음을 논리적으로 확정하는 단계다.

```text
Source / Issue identity
Issue semantic version
Run observation
Knowledge generation
Retry attempt
Knowledge item
Evidence round-trip
Review audit
Active / Historical retrieval boundary
Deterministic ID
```

최종 목표는 다음 round-trip을 잃지 않는 것이다.

```text
Knowledge Item
→ Evidence
→ Issue Version / Source Entity
→ ANALYSIS
→ RAW
```

---

## 2. M5 입력 근거

```text
Issue                           30
Knowledge item                285
Issue당 item mean             9.5
Statement p95                 206.4 chars
Evidence refs                 503
Evidence/item mean            1.76
Comment Evidence              79.92%
Review files                  37
Final PASS                    30 / 30
```

M6는 이 실제 분포를 사용하되 현재 max/p95를 DB hard limit로 사용하지 않는다.

---

## 3. M6-01 · Version / History / Active Retrieval

확정:

```text
Pipeline Run ≠ Issue Version
```

Run마다 동일 Issue snapshot을 복제하지 않는다.
Knowledge Input `source_hash`가 변경될 때만 새로운 의미 상태가 발생한다.

```text
same source_hash
→ existing issue_version 재사용

different source_hash
→ new issue_version
```

Historical Version/Knowledge는 DB에 보존하지만 기본 RAG/FAISS corpus에는 승인된 Active Knowledge만 포함한다.

```text
History Storage ≠ Active Retrieval Corpus
```

---

## 4. M6-02 · Deterministic ID / Attempt

Jira Issue의 authoritative identity는 `jira_id`를 우선한다.
`issue_key`는 파일명, Evidence, 관계, 사용자 질의에 사용하는 human-readable locator로 계속 보존한다.

파생 logical ID 공통 규칙:

```text
versioned canonical JSON
→ UTF-8
→ sorted keys
→ no insignificant whitespace
→ SHA-256
→ full lowercase 64 hex
```

Prefix:

```text
iv_  issue_version
kc_  knowledge_contract
kg_  knowledge_generation
ka_  knowledge_attempt
ki_  knowledge_item
ke_  knowledge_evidence
```

Generation과 retry Attempt를 분리한다.

```text
Issue Version
└── Knowledge Generation
    ├── Attempt 1
    │   ├── Knowledge Item
    │   └── Review
    ├── Attempt 2
    │   ├── Knowledge Item
    │   └── Review
    └── Attempt N
```

`knowledge_generation`은 같은 Issue Version + 같은 Knowledge Contract의 retry lineage다.
`knowledge_attempt`는 immutable 실제 생성 시도다.

현재 M4 legacy artifact는 failed Attempt의 Review 파일은 남지만 당시 Knowledge 본문은 남지 않는다.
따라서 M7에서는:

```text
accepted final Attempt
→ content_available=true
→ Knowledge Item / Evidence 적재

failed historical Attempt
→ Attempt / Review / Finding 적재
→ content_available=false
→ 존재하지 않는 Knowledge 본문을 추정하지 않음
```

---

## 5. M6-03 · Simplification / Integrity

확정:

1. Custom Field multi-value는 M7에서 JSON text로 유지한다.
2. Review category score는 `knowledge_review` 고정 column으로 둔다.
3. Evidence polymorphic source는 억지 FK 대신 exact ref + type-specific resolver validator로 검증한다.
4. `issue_version_observation`은 M7에서 실제 table로 구현한다.
5. `knowledge_generation.state`는 `candidate / active / historical / review_required`를 사용한다.
6. SQLite partial UNIQUE index로 Jira Issue당 `active` Generation 최대 1개를 보장한다.
7. 새 Version/Generation이 생겨도 PASS 전에는 기존 active Knowledge를 유지한다.

---

## 6. 최종 Entity

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

최종 Cardinality:

```text
pipeline_run               1 ── N issue_version_observation
issue                      1 ── N issue_version
issue_version              1 ── N issue_version_observation
issue_version              1 ── N knowledge_generation

knowledge_generation       1 ── N knowledge_attempt
knowledge_attempt          1 ── N knowledge_item
knowledge_item             1 ── N knowledge_evidence
knowledge_attempt          1 ── 0..1 knowledge_review
knowledge_review           1 ── N review_finding
```

---

## 7. Evidence round-trip 계약

최소 6개 Evidence type을 모두 복원할 수 있어야 한다.

```text
summary
→ issue_version.summary

description
→ issue_version.description

comment:<id>
→ comment(source_run_id, source_issue_key, comment_id)

attachment:<id>
→ attachment(source_run_id, attachment_id)

relationship:<id>
→ relationship(source_run_id, relationship_id)

custom_field:<field_id>
→ custom_field_value(source_run_id, source_issue_key, field_id)
```

Accepted Attempt에서 하나라도 resolver가 실패하면 integrity failure다.

---

## 8. Active publish 계약

```text
G1 active
+ new Version / G2 candidate

G2 Reviewer PASS 전
→ G1 active 유지

G2 PASS
→ accepted_attempt_id 설정
→ 같은 transaction에서 G1 historical
→ G2 active
```

따라서 다음은 서로 다른 개념이다.

```text
latest observed Issue Version
approved active Knowledge Generation
```

---

## 9. M6에서 의도적으로 하지 않은 것

- SQLite DDL 구현
- Chunk 정책
- Embedding schema
- FAISS index
- Ranking 정책
- Historical Knowledge 기본 검색 포함
- Custom Field array element table
- generic Review score EAV
- polymorphic source FK 발명
- Prompt/Git artifact 전체 hash 기반 완전 재현성
- Comment content-addressed versioning

---

## 10. M6 Gate

- [x] 주요 Entity / Cardinality 합의
- [x] `jira_id` authoritative identity 결정
- [x] Issue Version / Run Observation 분리
- [x] deterministic logical ID 규칙 확정
- [x] Generation / Attempt 분리
- [x] Knowledge Item / Evidence 연결 확정
- [x] 6 Evidence type round-trip 표현 가능
- [x] Review Attempt / Finding audit 보존
- [x] Active / Historical 경계 확정
- [x] M7에서 구현 가능한 field contract 확정
- [x] 과도한 정규화 제거

## **M6 Gate: PASS / DONE**

---

## 11. M7 인계

다음 단계는 **M7 · SQLite Materialization**이다.

구현 순서:

```text
1. deterministic ID utility
2. SQLite DDL / migration
3. Source / Version loader
4. Generation / Attempt / Knowledge / Review loader
5. idempotent rerun
6. FK / UNIQUE / CHECK / partial UNIQUE index
7. Evidence resolver validator
8. round-trip integration test
```

M7 완료 조건의 핵심은 단순히 SQLite 파일이 생성되는 것이 아니다.

```text
같은 Run 재적재
→ duplicate 없음
→ identity drift 없음

Knowledge Item 선택
→ Evidence
→ Source Entity
→ source_path
→ 원문 위치 복원
```

이 두 가지가 자동 테스트로 통과해야 M7 Gate를 통과한다.
