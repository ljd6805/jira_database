# M1 Knowledge Input Completion Record

복원 기준일: 2026-08-24  
구현 완료 근거: 2026-08-07 · PR #2 merge  
단계: **M1 · Issue 단위 LLM 입력 계약**

이 문서는 M1의 실제 commit, 구현 코드, `KNOWLEDGE_INPUT_SPEC.md`, 실환경 검증 기록을 바탕으로 뒤늦게 복원한 Completion Record다.

> M1의 핵심은 LLM을 붙이는 것이 아니라, M0에서 여러 JSONL로 나뉜 사실을 **Issue 한 건당 하나의 완전한 사실 입력 패키지**로 만드는 것이다.

---

## 1. M1 목적

M0 완료 시 데이터는 다음처럼 분산돼 있었다.

```text
[ANALYSIS]
issues.jsonl
comments.jsonl
attachments.jsonl
issue_relationships.jsonl
custom_field_catalog.jsonl
custom_field_values.jsonl
summary.json
```

이 구조는 데이터 파이프라인에는 적합하지만, Agent가 이슈 한 건을 분석할 때 매번 여러 JSONL을 직접 JOIN해야 한다.

M1은 이 문제를 해결하기 위해 다음 계층을 추가했다.

```text
[ANALYSIS]
    ↓ issue_key JOIN
IssueKnowledgeInputBuilder
    ↓
[KNOWLEDGE INPUT]
issues/<ISSUE_KEY>.json
```

한 문장으로 정리하면:

> **LLM이 의미를 추론하기 전에 필요한 사실을 이슈 하나의 입력 계약으로 완성한다.**

---

## 2. M1의 경계

M1 Builder는 생성형 LLM을 사용하지 않는다.

다음 내용을 만들지 않는다.

```text
원인
가설
계획
의사결정
결론
결과 해석
업무 요약
```

M1이 하는 일은 오직:

```text
ANALYSIS 검증
→ issue_key 기반 JOIN
→ 계층형 JSON 조립
→ 원본 추적 정보 유지
→ 정합성 warning 기록
→ 완료 manifest 기록
```

이다.

따라서 다음과 같이 오류 책임을 분리할 수 있게 됐다.

```text
KNOWLEDGE INPUT이 틀림
→ Parser / Join / deterministic code 문제

KNOWLEDGE INPUT은 맞고 LLM 결과가 틀림
→ Agent / Prompt / Skill 문제
```

이 경계가 이후 M2~M4 품질 검증의 전제가 됐다.

---

## 3. Commit 기반 구현 연혁

PR #2는 Knowledge Input을 기능별 작은 commit으로 구성했다.

```text
1d61041  feat: add knowledge input package
aa02b72  feat: add knowledge input result models
ee62d8c  feat: load completed analysis for issue packages
92e6da0  feat: build per-issue knowledge input packages
ad5b2fe  expose knowledge input models cleanly
56ca194  feat: expose knowledge input build status
e10a581  feat: add knowledge input build command
c6bbd81  test: knowledge input builder
c6ce8d4  test: knowledge input CLI
4f0bc8b  docs: define Knowledge Input contract
3ce72c7  docs: Knowledge Input code walkthrough
ec342e3  docs: record pilot validation
734382e  docs: expand README
cc07d44  docs/comments audit
98e1219  Merge PR #2
```

실제 PR #2 설명에는 다음 구현 범위가 명시됐다.

- completed ANALYSIS에서 Issue별 deterministic JSON 생성
- Issue / Comment / Attachment / canonical Relationship / Custom Field JOIN
- ANALYSIS completion gate
- orphan record 검증
- relationship endpoint view
- portable source path
- stable `source_hash`
- stale package cleanup
- package warning
- manifest completion marker
- CLI `build-knowledge-input`

---

## 4. 결정 1 — RAW를 다시 읽지 않는다

M1의 중요한 결정은 **Builder가 RAW를 다시 읽지 않는 것**이다.

입력은 오직 ANALYSIS다.

```text
[RAW]
  ↓ M0 Parser
[ANALYSIS]
  ↓ M1 Builder
[KNOWLEDGE INPUT]
```

이유:

1. HTML 정제와 타입 검증은 M0에서 이미 끝났다.
2. ANALYSIS에서 제거한 불필요한 개인정보를 다시 되살리지 않는다.
3. Builder가 Jira 원본 JSON 형태에 재의존하지 않는다.
4. 계층 간 책임이 선명해진다.
5. 같은 ANALYSIS 입력에서 같은 의미의 Knowledge Input을 재생성할 수 있다.

따라서 RAW에만 존재할 수 있는 다음 정보는 M1에서 다시 꺼내지 않는다.

```text
emailAddress
avatarUrls
전체 user object
불필요한 Jira self URL
```

---

## 5. 결정 2 — ANALYSIS Completion Gate

`ee62d8c · feat: load completed analysis for issue packages` 계열 구현에서 Builder 진입 전에 `summary.json`을 확인하도록 했다.

다음 다섯 영역이 모두 `completed`여야 한다.

```text
issues
comments
attachments
relationships
custom_fields
```

하나라도:

```text
partial
failed
not_run
```

이면 최종 Agent 입력 패키지를 만들지 않는다.

이유는 단순하다.

> 일부 댓글이나 관계가 빠진 데이터를 정상적인 “완성된 이슈 사실”처럼 LLM에 넘기면, 이후 LLM 품질 문제와 입력 누락 문제를 구분할 수 없다.

M1은 불완전한 데이터에 대해 “최선을 다해 패키지를 만들어준다”보다 **명확히 실패시키는 것**을 선택했다.

---

## 6. 결정 3 — Issue 한 건 = Package 한 건

최종 출력 구조:

```text
data/knowledge_input/runs/<run_id>/
├─ issues/
│  ├─ <ISSUE_KEY>.json
│  └─ ...
├─ package_warnings.jsonl
└─ manifest.json
```

개별 package의 기본 구조:

```json
{
  "package_schema_version": "1.0",
  "run_id": "...",
  "project_key": "ABC",
  "issue_key": "ABC-123",
  "generated_at": "...",
  "source_hash": "sha256:...",
  "issue": {},
  "comments": [],
  "attachments": [],
  "relationships": [],
  "custom_fields": [],
  "counts": {}
}
```

이 구조를 택한 이유:

- Worker가 한 파일만 읽어도 Issue 전체 시간 흐름을 볼 수 있음
- Comments와 관계를 매번 별도 JOIN할 필요가 없음
- Issue 단위 fresh context 운영이 쉬움
- Issue 단위 재분석 / 재생성 / caching 경계가 명확함
- 후속 `source_hash` 기반 증분 처리의 단위가 자연스럽게 Issue가 됨

---

## 7. Issue 영역

M1은 M0의 `issues.jsonl`에서 Agent가 의미 분석에 필요한 핵심 필드만 선택했다.

```text
jira_id
summary
description
description_format
issue_type
status
priority
created_at
updated_at
source_path
```

`description`은 ANALYSIS의 `description_text`이며 Raw HTML을 다시 복사하지 않는다.

---

## 8. Comment 영역

M1은 댓글을 생략하거나 사전 요약하지 않았다.

첫 버전의 원칙:

> Context 절약을 위해 사실을 미리 버리기보다, 이슈 단위 입력에서는 댓글 전체를 보존하고 이후 Knowledge Extraction이 의미를 압축하게 한다.

정렬:

```text
sequence
→ comment_id
```

필드:

```text
comment_id
sequence
author_name
author_key
created_at
updated_at
body
body_format
source_path
source_page
```

`body`는 M0 ANALYSIS의 정제된 `body_text`다.

---

## 9. Attachment 영역

M0에서 바이너리를 수집하지 않았기 때문에 M1도 파일 본문을 가진 척하지 않는다.

패키지에는 명시적으로:

```json
"content_available": false
```

를 넣었다.

핵심 의미:

```text
filename / size / mime type 존재
!=
첨부파일 내용을 읽었다
```

이 플래그는 이후 M2 Skill의 “content_available=false 첨부 내용을 상상하지 않는다” 규칙으로 그대로 이어졌다.

---

## 10. Relationship — canonical edge + 현재 Issue 관점

ANALYSIS의 관계는 canonical graph edge다.

예:

```text
A --blocks--> B
```

하지만 Issue 단위 package를 읽는 Agent에게는 현재 Issue가 A인지 B인지가 중요하다.

따라서 M1은 원래 edge를 변경하지 않고 **현재 package 관점만 추가**했다.

A package:

```text
current_issue_role = source
current_issue_direction = outgoing
other_issue_key = B
```

B package:

```text
current_issue_role = target
current_issue_direction = incoming
other_issue_key = A
```

중요한 결정:

- incoming 관계의 문구를 새로 추론하지 않음
- canonical `relationship_text`를 유지
- 현재 endpoint role/direction만 추가

즉 `blocks`를 임의로 `is blocked by`처럼 재작성해 의미가 뒤집힐 가능성을 피했다.

---

## 11. Package 범위 밖 Relationship 보존

파일럿은 프로젝트별 최근 30건이므로 연결된 다른 Issue가 현재 package 집합에 없을 수 있다.

M1은 이 관계를 버리지 않았다.

```json
{
  "other_issue_key": "ABC-999",
  "other_package_available": false
}
```

이 결정의 목적은 파일럿의 제한된 수집 범위를 **관계 없음**으로 오해하지 않게 하는 것이다.

---

## 12. Custom Field — Catalog 전체 복제를 피한다

M0에서:

```text
Catalog = 220 definitions
Values  = Issue별 non-null values
```

로 분리했다.

M1은 220개 정의 전체를 모든 Issue package에 복제하지 않는다.

현재 Issue에 실제 값이 있는 field만 골라 같은 `field_id`의 Catalog 정의와 결합한다.

대표 필드:

```text
field_id
field_name
schema_type
schema_items
schema_custom
actual_type
value_kind
display_value / display_values
value_id / value_ids
user_keys
value_shape
```

Catalog 정의가 없으면 값을 버리지 않고 보존하면서 `custom_field_definition_missing` warning을 남긴다.

---

## 13. 결정 4 — Portable source_path

ANALYSIS에는 개발 PC 절대 경로가 들어 있을 수 있다.

예:

```text
C:\work\jira_database\data\raw\runs\...
```

M1은 가능한 경우 다음처럼 `[DATA ROOT]` 기준 상대 경로로 바꾼다.

```text
raw/runs/...
```

이유:

- PC 설치 위치와 package 의미를 분리
- 다른 환경으로 data root를 옮겨도 추적 가능
- `source_hash`가 절대 경로 변경 때문에 불필요하게 달라지는 것을 방지

안전하게 상대화할 수 없는 외부 형식의 경로는 정보 손실을 피하기 위해 원문을 보존한다.

---

## 14. 결정 5 — semantic source_hash

`92e6da0 · feat: build per-issue knowledge input packages`에서 `source_hash`를 구현했다.

Hash 대상:

```text
issue
comments
attachments
relationships
custom_fields
```

Hash에서 제외:

```text
generated_at
source_path
source_page
PC 절대 경로
```

구현은 의미 데이터에서 경로성 값을 제거하고 canonical JSON으로 직렬화한 뒤 SHA-256을 계산한다.

```text
same semantic facts
→ same source_hash

different semantic facts
→ different source_hash
```

향후 의도:

```text
old source_hash == new source_hash
→ OpenCode 재분석 생략 가능

old source_hash != new source_hash
→ Knowledge 재추출 대상
```

M1 시점에는 아직 증분 Extraction을 구현하지 않았지만, 그 판단 기준을 미리 데이터 계약에 포함했다.

---

## 15. 결정 6 — manifest는 완료 표식

`manifest.json`은 단순 통계 파일이 아니라 **run의 Knowledge Input이 끝까지 완성됐음을 나타내는 marker**로 설계했다.

빌드 순서:

```text
기존 manifest 삭제
→ Issue package들을 원자 저장
→ stale package 정리
→ package_warnings 저장
→ 집계 계산
→ 마지막에 manifest 원자 저장
```

따라서 process가 중간에 종료되면 새 manifest가 남지 않는다.

```text
manifest 없음
→ 완료 아님

manifest.status == completed
→ build가 마지막 단계까지 종료됨
```

`severity=error` warning이 존재하면 manifest는 `partial`이 된다.

---

## 16. 결정 7 — Snapshot 재생성, append 아님

같은 `run_id`로 Builder를 다시 실행하면 기존 package에 append하지 않는다.

```text
현재 ANALYSIS snapshot
→ 현재 KNOWLEDGE INPUT snapshot 재생성
```

동작:

- 같은 Issue package 원자 교체
- 더 이상 존재하지 않는 stale Issue package 삭제
- package_warnings 전체 재생성
- manifest 마지막 재생성

이 결정은 이전 실행의 유령 package가 남아 Agent 입력에 섞이는 것을 막는다.

---

## 17. package_warnings와 Parser warning 분리

M0:

```text
parse_warnings.jsonl
= RAW → ANALYSIS 문제
```

M1:

```text
package_warnings.jsonl
= ANALYSIS → KNOWLEDGE INPUT JOIN 문제
```

대표 M1 warning:

```text
missing_issue_key
orphan_analysis_record
invalid_relationship_endpoint
relationship_outside_package_scope
custom_field_definition_missing
```

단계를 분리한 이유는 문제의 발생 위치를 바로 식별하기 위해서다.

---

## 18. 필수 정합성 규칙

### Issue

- `issue_key` 유일
- 빈 Issue 목록 거부

### Comment / Attachment / Custom Field Value

- `issue_key` 필수
- `issues.jsonl`에 존재하는 Issue만 package에 포함
- orphan record는 넣지 않고 오류 warning

### Custom Field Catalog

- `field_id` 유일
- 정의 누락 시 value는 보존 + warning

### Relationship

- source / target endpoint 필수
- current issue가 source면 outgoing
- target이면 incoming
- 연결 package 존재 여부를 별도 표시

---

## 19. CLI

M1은 기존 collector CLI에 다음 명령을 추가했다.

```powershell
python -m jira_collector.cli build-knowledge-input --run-id <RUN_ID>
```

이 명령은 Jira API를 호출하지 않는다.

---

## 20. 실환경 검증 결과

실제 사내 Jira 파일럿 ANALYSIS를 입력으로 사용했다.

```text
Issue                       30
Comment                    278
Attachment metadata         79
Canonical Relationship       6
  issue_link                 2
  hierarchy                  4
Custom Field Catalog       220
실제 사용 Field              16
Custom Field Value         447
```

Knowledge Input 결과:

```text
대상 Issue                  30
생성 Package                30
포함 Comment               278
포함 Attachment             79
Canonical Relationship       6
Custom Field Value         447
Package Warning              0
manifest.status       completed
```

선행 ANALYSIS와 manifest 집계가 일치했다.

사용자 환경:

```text
pytest 100% PASS
```

테스트는 특히 다음을 검증했다.

```text
미완료 ANALYSIS 거부
Issue 1 → Package 1
Comment / Attachment / Custom Field JOIN
Relationship source/target view
파일럿 밖 endpoint 보존
개인정보 재복제 방지
source_hash 경로 독립성
orphan record warning
stale package 삭제
manifest 최종 완료 표식
```

---

## 21. M1에서 하지 않은 것

의도적으로 다음은 구현하지 않았다.

```text
LLM 호출
Issue summary 생성
문제/원인/가설 추출
Decision/Outcome/Open Item 분류
Reviewer
DB 적재
Chunk / Embedding / FAISS
```

M1은 **Agent가 의미를 만들기 직전의 마지막 deterministic 사실 계층**이다.

---

## 22. M1 Gate 판정

- [x] ANALYSIS 다섯 영역 completion gate
- [x] RAW 재조회 없음
- [x] Issue별 package 1건
- [x] Comment 전체 포함
- [x] Attachment metadata + `content_available=false`
- [x] canonical Relationship + current issue endpoint view
- [x] file scope 밖 endpoint 보존
- [x] non-null Custom Field만 Issue package에 결합
- [x] 개인정보 재복제 방지
- [x] portable source path
- [x] semantic source_hash
- [x] orphan / definition mismatch warning
- [x] stale package cleanup
- [x] manifest 마지막 원자 저장
- [x] 실제 30 / 30 package
- [x] package warning 0
- [x] `manifest.status = completed`
- [x] pytest 100% PASS

## **M1 Gate: PASS / DONE**

다음 단계는 **M2 · 검색용 Knowledge Schema / Skill 계약**이다.

---

## 23. M1이 M2 이후에 남긴 설계 제약

1. LLM의 유일한 사실 입력은 Issue 단위 Knowledge Input이어야 한다.
2. LLM이 첨부파일 metadata만 보고 본문 내용을 상상하면 안 된다.
3. 지식 항목은 원래 사실로 되돌아갈 수 있는 Evidence reference를 가져야 한다.
4. `source_hash`는 Issue 의미 변경 탐지의 안정적인 기준으로 사용한다.
5. Knowledge Input은 사실 원장이고 Knowledge는 그 위의 파생 의미 계층으로 분리한다.
6. Empty array나 값 부재를 LLM이 임의로 사실로 보충하지 않는다.

---

## 24. 주요 근거 Commit / 문서

- [PR #2 · Issue-level Knowledge Input packages](https://github.com/ljd6805/jira_database/pull/2)
- [`92e6da0` per-issue package builder](https://github.com/ljd6805/jira_database/commit/92e6da0514b6c167990b4d14630c369774dc853c)
- [`98e1219` PR #2 merge](https://github.com/ljd6805/jira_database/commit/98e1219a860f6a1abea8a2eaae6cee07958c55ca)
- `docs/KNOWLEDGE_INPUT_SPEC.md`
- `docs/KNOWLEDGE_INPUT_CODE_GUIDE.md`
- `docs/KNOWLEDGE_INPUT_VALIDATION.md`
- `docs/PIPELINE_OVERVIEW.md`
