# Documentation Policy

기준일: 2026-08-25  
상태: **ACTIVE PROJECT RULE**

이 프로젝트는 코드 구현과 문서화를 분리하지 않는다.

> **방향을 바꾸는 결정, 데이터 계약 변경, Milestone 상태 변경은 같은 작업 단위에서 문서에도 반영한다.**

문서는 단순 결과 보고가 아니라 다음 작업을 시작할 때 사람과 Agent가 같은 맥락을 복원하기 위한 프로젝트 상태 저장소다.

---

## 1. 문서 계층

### A. Current Source of Truth

항상 현재 상태를 반영해야 한다.

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/architecture/jira_data_relationship_map.*
```

여기에 `CURRENT`라고 적힌 Milestone, Entity 관계, 다음 Gate가 실제 코드/설계와 다르면 문서 결함이다.

### B. Current Design / Implementation Contract

현재 단계와 이후 구현에서 직접 참조하는 계약이다.

```text
docs/DB_LOGICAL_SCHEMA.md
docs/M7_SQLITE_MATERIALIZATION.md
```

Schema/ID/Cardinality/Evidence contract가 변경되면 코드와 같이 갱신한다.

### C. Decision Log

```text
docs/M6_DECISION_LOG.md
```

결정 과정과 폐기된 초안도 보존한다.
과거 구조를 삭제하지 않되 현재 결정과 충돌하는 부분은 `Superseded`임을 명시한다.

### D. Milestone Completion Record

```text
docs/status/M*_..._COMPLETION.md
```

해당 Milestone을 닫을 때의 입력, 결정, 문제, 해결, 검증 결과를 고정한다.
완료 후 다음 Milestone이 진행됐다고 과거 내용을 현재형으로 다시 쓰지 않는다.

### E. Historical / Archive

```text
docs/status/archive/
```

당시 상태를 그대로 보존한다.
현재 상태 판단에는 사용하지 않는다.

---

## 2. Milestone 변경 규칙

예를 들어:

```text
M6 DONE
M7 CURRENT
```

으로 상태가 바뀌면 최소 다음을 같은 변경 단위에서 확인한다.

```text
README.md
PIPELINE_OVERVIEW.md
docs/index.html
current_status.html
architecture map
이전 Milestone Completion Record
현재 Milestone 실행/설계 문서
```

`M6 CURRENT`, `M7 NEXT` 같은 오래된 문자열이 Current Source of Truth에 남아 있으면 작업이 끝난 것이 아니다.

---

## 3. 구조 변경 규칙

Entity 관계가 변경되면 검색/대조한다.

예:

```text
old
knowledge_generation
├── knowledge_item
└── knowledge_review

current
knowledge_generation
└── knowledge_attempt
    ├── knowledge_item
    │   └── knowledge_evidence
    └── knowledge_review
        └── review_finding
```

이 경우 Current Source of Truth의 관계도, Cardinality, ID 설명을 모두 갱신한다.
Decision Log의 old 구조는 삭제하지 않고 `M6-02에서 superseded`라고 표시한다.

---

## 4. ID 계약은 문서와 코드가 함께 움직인다

현재 M6-02/M7 ID 계층:

```text
jira_id
  ↓
issue_version_id           iv_
  ↓
knowledge_contract_hash    kc_
  ↓
knowledge_generation_id    kg_
  ↓
knowledge_attempt_id       ka_   + attempt_no
  ↓
knowledge_item_id          ki_
  ↓
knowledge_evidence_id      ke_
```

다음 중 하나라도 바뀌면 반드시 문서와 테스트를 함께 갱신한다.

- hash material
- canonical serialization
- prefix
- Attempt/Generation 의미
- authoritative identity
- active/historical lifecycle

---

## 5. Gate 규칙

Milestone Gate는 세 층을 모두 만족해야 닫는다.

```text
DESIGN
→ 계약이 합의되고 문서화됨

IMPLEMENTATION
→ 코드/DDL/도구 구현

VALIDATION
→ unit/integration/실데이터 검증
```

그리고 마지막으로:

```text
DOCUMENTATION SYNC
→ Current Source of Truth가 실제 상태와 일치
```

따라서 **코드만 통과했다고 다음 Milestone으로 이동하지 않는다.**

---

## 6. 현재 적용 상태

2026-08-25 기준:

```text
M0~M6   DONE
M7      IMPLEMENTED / REAL-RUN VALIDATION PENDING
M8      BLOCKED UNTIL M7 REAL-RUN GATE
```

M6-01~03 결정은 `docs/M6_DECISION_LOG.md`에 보존되고, M6 최종 계약은 `docs/DB_LOGICAL_SCHEMA.md`, M7 구현 계약은 `docs/M7_SQLITE_MATERIALIZATION.md`를 기준으로 한다.

---

## 7. 작업 종료 전 문서 체크

- [ ] Current Milestone 표기가 실제 상태와 같은가?
- [ ] Next Milestone이 실제 다음 작업과 같은가?
- [ ] Entity/Cardinality가 현재 코드와 같은가?
- [ ] ID 계층과 hash material이 현재 코드와 같은가?
- [ ] Attempt/Generation 관계가 유실되지 않았는가?
- [ ] Evidence round-trip 경로가 최신인가?
- [ ] Decision Log에 변경 이유가 남아 있는가?
- [ ] 이전 Milestone Completion Record가 존재하는가?
- [ ] archive와 current 문서가 명확히 구분되는가?

이 체크가 끝나야 해당 작업 단위를 완료한 것으로 본다.
