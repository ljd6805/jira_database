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

### D. Milestone Completion Record / Visual Companion

상세 사실 기록의 기준본은 Markdown Completion Record다.

```text
docs/status/M*_..._COMPLETION.md
```

해당 Milestone을 닫을 때의 입력, 결정, 문제, 해결, 검증 결과를 고정한다.
완료 후 다음 Milestone이 진행됐다고 과거 내용을 현재형으로 다시 쓰지 않는다.

사람이 Milestone의 목적과 결과를 빠르게 다시 읽을 수 있도록 **각 단계별 정적 HTML 시각 문서를 필수 산출물로 함께 보존한다.**

```text
docs/status/M0_JIRA_COLLECTION_ANALYSIS_COMPLETION.html
docs/status/M1_KNOWLEDGE_INPUT_COMPLETION.html
docs/status/M2_KNOWLEDGE_SCHEMA_SKILL_COMPLETION.html
docs/status/M3_KNOWLEDGE_QUALITY_LOOP_COMPLETION.html
docs/status/M4_KNOWLEDGE_EXTRACTION_COMPLETION.html
docs/status/M5_KNOWLEDGE_PROFILING_COMPLETION.html
docs/status/M6_DB_LOGICAL_SCHEMA_COMPLETION.html
docs/status/M7_SQLITE_MATERIALIZATION.html
```

현재 진행 중인 Milestone은 아직 Completion Record가 아니라도 실행/설계 Markdown을 기준으로 HTML Visual Companion을 둔다. 현재 M7은 `docs/M7_SQLITE_MATERIALIZATION.md`가 상세 기준이고 `docs/status/M7_SQLITE_MATERIALIZATION.html`이 시각본이다.

#### HTML 보존 규칙

1. Milestone이 `CURRENT`가 되는 시점부터 해당 `M<N>_*.html`을 작성한다.
2. Milestone이 `DONE`이 된 이후에도 해당 HTML을 삭제하지 않는다.
3. Markdown은 상세 기준본으로 함께 유지하지만 **Markdown으로 HTML을 대체하지 않는다.**
4. 코드/설계/Schema/Gate/검증 결과가 바뀌면 관련 HTML도 같은 작업 단위에서 업데이트한다.
5. 본문은 HTML 파일 자체에 정적으로 포함한다.
6. 외부 CDN이나 원격 문서가 없어도 핵심 내용은 읽을 수 있어야 한다.
7. `fetch()`로 압축 조각을 가져와 `DecompressionStream`으로 복원하는 loader 방식은 Milestone 문서에 사용하지 않는다.
8. HTML이 Markdown보다 더 강한 사실을 새로 만들지 않는다. 상세 내용이 충돌하면 Markdown Completion Record / Current Contract가 우선한다.
9. `docs/index.html`에서 M0부터 현재 Milestone HTML과 기준 Markdown을 모두 찾을 수 있어야 한다.
10. Milestone HTML 삭제·누락·동적 loader 회귀는 `tests/test_documentation_current_state.py`에서 실패해야 한다.

#### HTML 삭제 / 이동 승인 규칙

`docs/status/M*.html`에 대한 삭제, 이름 변경, 다른 형식으로의 대체, archive 이동은 일반적인 정리 작업으로 취급하지 않는다.

> **Milestone HTML의 삭제가 반드시 필요하다면 실제 삭제 전에 사용자에게 이유와 영향 범위를 설명하고 명시적 승인을 받아야 한다.**

현재 작업에서 사용자의 명시적 승인 여부를 확인할 수 없다면 HTML을 보존한다.
가능하면 삭제 대신 `superseded`, `historical`, `archive reference` 표기를 추가해 이력을 유지한다.

Agent는 사용자의 승인 없이 이 규칙 또는 HTML 보존 regression test를 삭제하거나 약화해서는 안 된다.

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
이전 Milestone HTML Visual Companion
현재 Milestone 실행/설계 문서
현재 Milestone HTML Visual Companion
```

새 Milestone이 `CURRENT`가 되었는데 해당 `M<N>_*.html`이 없다면 Milestone 전환 작업은 미완료다.

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

Milestone HTML은 당시 완료 시점의 구조를 보존한다. 이후 구조가 바뀌었다면 과거 HTML을 현재 구조처럼 다시 쓰기보다, 필요한 경우 후속 변경 또는 superseded 사실을 명확히 주석으로 남긴다.

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
→ Milestone Completion Record와 HTML Visual Companion이 보존됨
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

M0~M7 HTML Visual Companion은 `docs/status/`에 보존하고 `docs/index.html`에서 연결한다.

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
- [ ] M0부터 현재 Milestone까지 HTML Visual Companion이 존재하는가?
- [ ] 새 CURRENT Milestone의 HTML이 같은 작업 단위에서 작성되었는가?
- [ ] 관련 구현/설계 수정이 Milestone HTML에도 반영되었는가?
- [ ] docs/index.html에서 HTML과 기준 Markdown을 모두 찾을 수 있는가?
- [ ] Milestone HTML이 fetch/압축 fragment loader에 의존하지 않는가?
- [ ] HTML 삭제/이동이 있다면 사용자의 사전 명시적 승인을 받았는가?
- [ ] archive와 current 문서가 명확히 구분되는가?

이 체크가 끝나야 해당 작업 단위를 완료한 것으로 본다.
