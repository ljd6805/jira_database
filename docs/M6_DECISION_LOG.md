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

## 다음 결정

다음 검토 대상은 **M6-02 · Knowledge deterministic ID**다.

확정할 내용:

- `issue_version_id`의 logical ID 구성
- `knowledge_generation_id` canonical serialization
- `knowledge_item_id`가 statement 수정에 따라 어떻게 변해야 하는지
- hash algorithm / prefix / encoding 규칙
