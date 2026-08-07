# Jira Issue Knowledge Input 상세 명세

## 1. 목적

이 단계는 지금까지 여러 ANALYSIS JSONL에 흩어져 있는 Jira 정보를 `issue_key` 기준으로 하나의 계층형 JSON으로 조립합니다.

이 파일은 OpenCode Agent가 이슈를 분석하기 전에 읽는 **최종 사실 입력 패키지**입니다.

중요한 경계:

```text
RAW
→ Parser / Exporter
→ ANALYSIS
→ Issue Knowledge Input Builder
→ KNOWLEDGE INPUT
→ OpenCode Agent   # 다음 단계
→ KNOWLEDGE        # 다음 단계
```

이 Builder는 LLM을 호출하지 않습니다.
원인, 결론, 계획 등을 추론하거나 요약하지 않습니다.
같은 ANALYSIS 입력이면 같은 의미 구조의 패키지를 만드는 결정적 처리입니다.

---

## 2. 입력 데이터 계층

이 단계는 **RAW를 다시 읽지 않습니다.**

입력은 다음 ANALYSIS 파일만 사용합니다.

```text
[ANALYSIS 데이터 경로]
data/analysis/<run_id>/
├─ issues.jsonl
├─ comments.jsonl
├─ attachments.jsonl
├─ issue_relationships.jsonl
├─ custom_field_catalog.jsonl
├─ custom_field_values.jsonl
└─ summary.json
```

왜 RAW를 다시 읽지 않는가:

- Parser가 이미 HTML 정제와 타입 검증을 수행함
- ANALYSIS에서 불필요한 개인정보 복제를 제거함
- 이전 단계의 저장 계약을 다음 계층의 공식 입력 계약으로 사용하기 위함
- Knowledge Input Builder가 Jira 원본 구조의 세부 차이에 다시 의존하지 않게 하기 위함

따라서 RAW에만 존재하는 `emailAddress`, `avatarUrls`, 전체 user 객체 등을 이 단계에서 다시 꺼내지 않습니다.

---

## 3. ANALYSIS 완료 조건

최종 분석 입력을 만들기 전에 다음 모든 영역이 `summary.json`에서 `completed`여야 합니다.

```text
issues
comments
attachments
relationships
custom_fields
```

예:

```json
{
  "issues": {"status": "completed"},
  "comments": {"status": "completed"},
  "attachments": {"status": "completed"},
  "relationships": {"status": "completed"},
  "custom_fields": {"status": "completed"}
}
```

하나라도 `partial`, `failed`, `not_run`이면 Builder는 시작하지 않습니다.

이 정책의 목적은 불완전한 ANALYSIS가 정상적인 Agent 입력처럼 보이는 것을 방지하는 것입니다.

---

## 4. 실행 명령

```powershell
python -m jira_collector.cli build-knowledge-input --run-id <RUN_ID>
```

예:

```powershell
$runId = "20260804T043628Z"
python -m jira_collector.cli build-knowledge-input --run-id $runId
```

이 명령은 Jira API를 호출하지 않습니다.

---

## 5. 출력 데이터 계층

```text
[KNOWLEDGE INPUT 데이터 경로]
data/knowledge_input/runs/<run_id>/
├─ issues/
│  ├─ ABC-123.json
│  ├─ ABC-124.json
│  └─ ...
├─ package_warnings.jsonl
└─ manifest.json
```

파일럿에 이슈가 30개라면 정상 상태에서 이슈 JSON도 30개 생성됩니다.

이슈 키는 파일명으로 사용하기 전에 안전한 문자 집합인지 검증합니다.

---

## 6. 이슈 패키지의 역할

현재 ANALYSIS에서는 한 이슈의 정보가 다음처럼 여러 파일에 분산됩니다.

```text
issues.jsonl
comments.jsonl
attachments.jsonl
issue_relationships.jsonl
custom_field_values.jsonl
```

Builder는 이를 다음처럼 조립합니다.

```text
Issue ABC-123
├─ core issue
├─ comments[]
├─ attachments[]
├─ relationships[]
└─ custom_fields[]
```

OpenCode Agent는 이후 여러 JSONL을 직접 JOIN할 필요 없이 `ABC-123.json` 하나를 읽고 분석할 수 있습니다.

---

## 7. 패키지 기본 구조

```json
{
  "package_schema_version": "1.0",
  "run_id": "20260804T043628Z",
  "project_key": "ABC",
  "issue_key": "ABC-123",
  "generated_at": "2026-08-07T07:00:00Z",
  "source_hash": "sha256:...",
  "issue": {},
  "comments": [],
  "attachments": [],
  "relationships": [],
  "custom_fields": [],
  "counts": {
    "comment_count": 0,
    "attachment_count": 0,
    "relationship_count": 0,
    "custom_field_count": 0
  }
}
```

`generated_at`은 패키지 생성 시각이고 `source_hash`에는 포함되지 않습니다.

---

## 8. Issue 영역

ANALYSIS `issues.jsonl`에서 다음 값을 선택합니다.

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

`description`은 ANALYSIS의 `description_text`입니다.
RAW HTML을 다시 복사하지 않습니다.

`source_path`는 가능한 경우 `[DATA ROOT]` 기준 상대 경로로 변환합니다.

---

## 9. Comment 영역

모든 댓글을 포함합니다.
첫 버전에서는 Agent context 크기를 이유로 댓글을 생략하거나 요약하지 않습니다.

댓글 순서:

```text
sequence
→ comment_id
```

저장 항목:

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

`body`는 ANALYSIS의 `body_text`입니다.

현재 단계에서 댓글을 분석해 원인/결과로 재분류하지 않습니다.

---

## 10. Attachment 영역

현재는 첨부파일 바이너리를 수집하지 않으므로 메타데이터만 포함합니다.

```text
attachment_id
filename
author_name
author_key
created_at
size_bytes
mime_type
content_available=false
source_path
```

Agent가 파일 내용이 실제로 제공됐다고 오해하지 않도록 `content_available=false`를 명시합니다.

현재 ANALYSIS의 `content_url`, `thumbnail_url`은 Agent 입력 패키지에는 포함하지 않습니다.

---

## 11. Relationship 영역

ANALYSIS의 `issue_relationships.jsonl`은 canonical graph edge입니다.

예:

```text
ABC-100 --blocks--> ABC-200
```

패키지에서는 canonical 관계를 보존하면서 현재 이슈가 어느 endpoint인지 추가합니다.

ABC-100 패키지:

```json
{
  "source_issue_key": "ABC-100",
  "target_issue_key": "ABC-200",
  "relationship_text": "blocks",
  "current_issue_role": "source",
  "current_issue_direction": "outgoing",
  "other_issue_key": "ABC-200"
}
```

ABC-200 패키지:

```json
{
  "source_issue_key": "ABC-100",
  "target_issue_key": "ABC-200",
  "relationship_text": "blocks",
  "current_issue_role": "target",
  "current_issue_direction": "incoming",
  "other_issue_key": "ABC-100"
}
```

### 관계 문구를 새로 추론하지 않는 이유

ANALYSIS에는 canonical `relationship_text`가 이미 있습니다.
Builder는 incoming 관계를 임의로 `is blocked by`처럼 새로 생성하지 않습니다.
원본 canonical 의미와 현재 endpoint 역할만 전달합니다.

---

## 12. 패키지 범위 밖의 연결 이슈

관계 대상 이슈가 이번 파일럿의 `issues.jsonl`에 없을 수 있습니다.

관계 자체는 버리지 않습니다.

```json
{
  "other_issue_key": "ABC-999",
  "other_package_available": false
}
```

나중에 전체 Jira 수집 범위가 커지면 같은 관계에서 `other_package_available=true`가 될 수 있습니다.

관계의 양 endpoint가 모두 현재 패키지 범위 밖이면 이 run의 패키지에는 연결할 대상이 없으므로 경고를 기록하고 제외합니다.

---

## 13. Custom Field 영역

220개 Catalog 정의 전체를 매 이슈에 복제하지 않습니다.

`custom_field_values.jsonl`에서 현재 이슈에 실제 값이 존재하는 필드만 선택하고, 같은 `field_id`의 Catalog 정의와 결합합니다.

예:

```json
{
  "field_id": "customfield_16603",
  "field_name": "...",
  "schema_type": "option",
  "schema_custom": "...:select",
  "actual_type": "object",
  "value_kind": "option",
  "display_value": "...",
  "value_id": "..."
}
```

Multi User Picker도 ANALYSIS에 이미 정규화된 `display_values`, `user_keys`만 사용합니다.

다음 RAW 개인정보는 다시 추가하지 않습니다.

```text
emailAddress
avatarUrls
self
timeZone
전체 user object
```

---

## 14. source_path 정책

ANALYSIS의 `source_path`는 원본 추적을 위해 유지합니다.

가능한 경우:

```text
C:\...\data\raw\runs\...
```

형태의 절대 경로를 다음처럼 바꿉니다.

```text
raw/runs/...
```

즉 Knowledge Input은 PC 설치 위치에 덜 의존하도록 합니다.

다른 OS에서 만들어진 경로처럼 안전하게 상대화할 수 없는 문자열은 정보 손실을 막기 위해 원문을 유지합니다.

---

## 15. source_hash

각 이슈 패키지는 의미 데이터 기반 SHA-256을 가집니다.

```text
source_hash = SHA256(
    issue
  + comments
  + attachments
  + relationships
  + custom_fields
)
```

실제 구현은 key 정렬된 canonical JSON 문자열을 해시합니다.

해시에서 제외:

```text
generated_at
source_path
source_page
PC 절대 경로
```

따라서 같은 업무 내용이 다른 PC 경로에 있어도 동일한 source_hash를 만들 수 있습니다.

### 향후 용도

```text
old source_hash == new source_hash
→ OpenCode Agent 재분석 생략 가능

old source_hash != new source_hash
→ 이슈 내용 변경
→ Knowledge 재추출 대상
```

이 값은 향후 증분 Knowledge Extraction의 기준입니다.

---

## 16. manifest.json

`manifest.json`은 run 전체 패키지 생성의 완료 표식입니다.

빌드를 시작할 때 기존 manifest를 먼저 삭제합니다.
빌드가 끝까지 성공한 뒤 마지막에 새 manifest를 원자 저장합니다.

즉 패키지 생성 도중 프로세스가 중단되면 manifest가 없어 완료된 run으로 오해하지 않습니다.

주요 필드:

```text
schema_version
run_id
generated_at
status
issue_count
package_count
comment_count
attachment_count
relationship_count
custom_field_catalog_count
custom_field_value_count
warning_count
input_files
warnings_file
packages[]
```

`packages[]`에는 각 이슈의 경로, source_hash, 포함 데이터 개수를 기록합니다.

---

## 17. package_warnings.jsonl

이 파일은 Parser 경고와 별개입니다.

Parser는 RAW → ANALYSIS 변환의 문제를 기록합니다.
Knowledge Input 경고는 ANALYSIS → KNOWLEDGE INPUT JOIN 과정의 정합성 문제를 기록합니다.

예:

```text
missing_issue_key
orphan_analysis_record
invalid_relationship_endpoint
relationship_outside_package_scope
custom_field_definition_missing
```

`severity=error`가 하나라도 있으면 manifest status는 `partial`입니다.

warning만 존재하면 패키지 자체가 완전할 수 있으므로 status는 `completed`를 유지할 수 있습니다.

---

## 18. 필수 정합성 규칙

### Issue

- `issues.jsonl`의 `issue_key`는 유일해야 함
- 빈 이슈 목록은 허용하지 않음

### Comment / Attachment / Custom Field Value

- 모든 레코드는 `issue_key`를 가져야 함
- 해당 issue_key가 `issues.jsonl`에 존재해야 함
- 고아 레코드는 패키지에 넣지 않고 오류 경고

### Custom Field Catalog

- `field_id`는 유일해야 함
- 값에 대응하는 정의가 없으면 값은 보존하되 경고

### Relationship

- source_issue_key / target_issue_key 필요
- 현재 이슈가 source면 outgoing
- 현재 이슈가 target이면 incoming
- 연결 이슈 패키지 존재 여부를 별도 표시

---

## 19. 재실행 의미

같은 run_id를 다시 빌드하면 해당 run의 Knowledge Input을 현재 ANALYSIS 기준으로 다시 생성합니다.

- 같은 issue_key JSON은 원자 교체
- 더 이상 존재하지 않는 오래된 issue JSON은 제거
- `package_warnings.jsonl` 전체 재생성
- `manifest.json` 마지막 재생성

append 방식이 아닙니다.

---

## 20. 완료 기준

파일럿 기준 예상 성공 조건:

```text
대상 이슈           30
생성 package        30
포함 댓글           278
포함 attachment      79
canonical 관계        6
Custom Field 값      447
패키지 오류           0
manifest status       completed
```

Relationship은 각 이슈 패키지에서 양쪽 관점으로 보일 수 있으므로 개별 package의 relationship_count 합계는 canonical 관계 6보다 커질 수 있습니다.
manifest의 `relationship_count`는 ANALYSIS canonical 관계 건수를 의미합니다.

---

## 21. 다음 단계와의 경계

이 Builder의 출력에는 다음 항목이 없습니다.

```text
problem
cause
hypothesis
action
plan
decision
result
conclusion
```

이 값들은 OpenCode Agent가 이후 KNOWLEDGE 계층에서 원문 근거를 바탕으로 추출합니다.

```text
[KNOWLEDGE INPUT]
ABC-123.json
        ↓
OpenCode Agent
        ↓
[KNOWLEDGE]
issue_knowledge.jsonl
```

따라서 문제가 발생했을 때 다음처럼 원인을 분리할 수 있습니다.

```text
Knowledge Input부터 잘못됨
→ 결정적 JOIN/Parser 문제

Knowledge Input은 맞지만 Knowledge가 잘못됨
→ Agent 추론/프롬프트 문제
```

이 계층 분리가 본 단계의 가장 중요한 아키텍처 목적입니다.
