# Jira Parser Core

## 1. 목적

Parser Core는 Collector가 저장한 Jira Raw JSON을 수정하지 않고 읽어, 이후 JSONL·Excel·DB·Knowledge Extraction으로 전달할 표준 중간 레코드를 생성합니다.

Parser는 Jira API를 호출하지 않습니다.

```text
[RAW]
data/raw/runs/<run_id>/...
        ↓
RunReader
        ↓
IssueParser / CommentParser / IssueStructureParser
        ↓
[ANALYSIS]
표준 레코드와 JSONL
```

## 2. 설계 원칙

- RAW JSON은 읽기 전용으로 취급
- 같은 RAW 입력은 항상 같은 결과를 생성하는 결정적 처리
- 아는 필드는 표준 구조로 변환
- HTML 원문과 정제 텍스트를 구분
- 복잡한 원본 객체를 ANALYSIS에 무조건 복제하지 않음
- 개인정보는 필요한 식별·표시값만 최소화해 저장
- 한 이슈 또는 페이지 오류가 전체 run을 중단시키지 않음
- 모든 파생 레코드에 원본 추적 경로 보존
- 실제 Jira 데이터를 테스트 fixture로 사용하지 않음

## 3. RunReader

입력:

```text
[RAW]
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/
```

출력 `IssueSource`:

```text
run_id
project_key
issue_key
issue_path
comments_dir
```

정렬 순서:

```text
project 디렉터리 이름
→ issue 디렉터리 이름
→ comment page 파일 이름
```

## 4. IssueParser

읽는 파일:

```text
[RAW]
issues/<issue_key>/issue.json
```

생성 레코드:

```text
run_id
project_key
issue_key
jira_id
summary
description_raw
description_rendered
description_text
description_format
issue_type
status
priority
created_at
updated_at
source_path
```

### Description 처리

- HTML 문자열이면 `description_format=html`
- HTML 태그, style, color 속성은 `description_text`에서 제거
- HTML 원문은 `description_raw`에 유지
- 일반 문자열이면 `plain_text`
- null이면 `null`
- 예상하지 못한 객체·배열이면 타입을 기록하고 경고 생성
- `renderedFields.description`이 있으면 fallback으로 사용 가능

주요 경고:

```text
issue_key_mismatch
project_key_mismatch
unexpected_type
unsupported_description_type
```

## 5. CommentParser

읽는 파일:

```text
[RAW]
issues/<issue_key>/comments/page_0001.json
issues/<issue_key>/comments/page_0002.json
...
```

댓글 전용 API 파일만 기준 원본으로 사용합니다. `issue.json` 안의 `fields.comment`는 사용하지 않습니다.

생성 레코드:

```text
run_id
project_key
issue_key
comment_id
sequence
author_name
author_key
created_at
updated_at
body_raw
body_text
body_format
source_path
source_page
```

실제 파일럿 확인:

```text
BodyType           : System.String
BodyStartsWithHtml : True
```

작성자 객체에서 확인된 key:

```text
self
name
key
emailAddress
avatarUrls
displayName
active
timeZone
```

정규화:

```text
author_name = displayName → name → key
author_key  = name → key
```

Exporter는 emailAddress·avatarUrls·self URL을 JSONL에 저장하지 않습니다.

## 6. IssueStructureParser

4단계 Parser입니다.

Attachment·Relationship·Custom Field가 모두 같은 `[RAW] issue.json` 안에 있으므로 이 파일을 각각 세 번 읽지 않고 **한 번 읽어 함께 추출**합니다.

```text
[RAW] issue.json
        ↓ 1회 JSON load
IssueStructureParser
        ├─ _parse_attachments()
        ├─ _parse_relationships()
        └─ _parse_custom_fields()
```

생성 레코드:

```text
AttachmentRecord
IssueRelationshipRecord
CustomFieldDefinitionRecord
CustomFieldValueRecord
IssueStructureParseResult
```

## 7. AttachmentRecord

RAW 위치:

```text
/fields/attachment
```

실환경에서 확인된 key:

```text
self
id
filename
author
created
size
mimeType
content
thumbnail
```

레코드:

```text
run_id
project_key
issue_key
attachment_id
filename
author_name
author_key
created_at
size_bytes
mime_type
content_url
thumbnail_url
source_path
```

Attachment 바이너리는 다운로드하지 않습니다.

## 8. IssueRelationshipRecord

RAW 위치:

```text
/fields/issuelinks
/fields/parent
/fields/subtasks
```

### Issue Link 실환경 조사

```text
IssueCount        : 30
IssuesWithLinks   : 1
TotalLinks        : 2
TotalInwardLinks  : 1
TotalOutwardLinks : 1
```

Link type key:

```text
id
name
inward
outward
self
```

### Canonical edge

`inward`/`outward`를 현재 문서 관점 그대로 저장하면 같은 Jira Link가 양쪽 이슈에서 중복될 수 있습니다.

따라서 Jira의 `type.outward` 의미를 기준으로 canonical 방향을 만듭니다.

```text
current에서 outwardIssue=B
→ current --outward text--> B

current에서 inwardIssue=A
→ A --outward text--> current
```

`relationship_id`가 같은 Jira Link는 Exporter에서 한 번만 저장합니다.

### Hierarchy

파일럿 조사:

```text
ParentFieldPresent   : 0
SubtasksFieldPresent : 30
IssuesWithSubtasks   : 1
TotalSubtasks        : 4
```

표준 방향:

```text
parent --parent_of--> child
```

향후 `fields.parent`가 나타나도 같은 방향으로 변환합니다.

## 9. CustomFieldDefinitionRecord

RAW 정의:

```text
/names
/schema
```

파일럿 30건 모두 names/schema가 존재했습니다.

```text
UniqueCustomFieldIds = 220
```

레코드:

```text
run_id
field_id
field_name
schema_type
schema_items
schema_custom
schema_custom_id
source_path
```

동일 field_id 정의가 이슈별로 다르면 `custom_field_definition_mismatch` 경고를 생성합니다.

## 10. CustomFieldValueRecord

RAW 위치:

```text
/fields/customfield_*
```

파일럿 조사:

```text
UniqueNonNullCustomFieldIds : 16
TotalNonNullValues          : 447
```

최상위 실제 타입:

```text
object : 244
string : 173
array  : 30
```

지원 value_kind:

```text
string
scalar
option
user_array
generic_object
generic_array
```

### Option

확인된 구조:

```text
self
value
id
disabled
```

정규화:

```text
display_value = value
value_id      = id
```

### Multi User Picker

Schema:

```text
type  = array
items = user
```

원소 key에는 emailAddress 등이 포함되지만 ANALYSIS에는 다음만 저장합니다.

```text
display_values
user_keys
value_shape
```

다음은 복제하지 않습니다.

```text
emailAddress
avatarUrls
self
timeZone
전체 user 객체
```

### Plugin any

`schema.type=any`는 실제 JSON 타입을 의미하지 않습니다.

따라서 다음 둘을 구분합니다.

```text
schema_type = Jira schema
actual_type = 실제 값 타입
```

복잡한 객체는 공통 이름/value/id가 있으면 표시값만 추출하고, 전체 원본 객체 대신 `value_shape`로 key 구조만 기록합니다.

## 11. ParseWarning

```text
code
message
json_path
severity
```

Parser는 경고를 직접 파일에 저장하지 않습니다. Exporter가 `parse_warnings.jsonl`로 변환합니다.

Structure 주요 경고:

```text
invalid_attachment_array
invalid_attachment_object
missing_attachment_id
invalid_issue_links_array
invalid_issue_link_object
missing_issue_link_target
missing_linked_issue_key
invalid_subtasks_array
invalid_subtask_object
missing_subtask_issue_key
missing_custom_field_names
missing_custom_field_schema
custom_field_value_parse_error
```

## 12. HTML 텍스트 변환

표준 라이브러리 `html.parser.HTMLParser`를 사용합니다.

- script와 style 내용 무시
- p, div, heading, table, tr 뒤 줄바꿈
- br 줄바꿈
- li 앞 `- ` 추가
- td/th 사이 구분
- HTML entity 디코딩
- 중복 공백과 빈 줄 정리

## 13. CLI

Issue:

```powershell
python -m jira_collector.cli export-issues --run-id <RUN_ID>
```

Comment:

```powershell
python -m jira_collector.cli export-comments --run-id <RUN_ID>
```

4단계 Structure:

```powershell
python -m jira_collector.cli export-structure --run-id <RUN_ID>
```

`export-structure`는 다음 네 ANALYSIS 파일을 생성합니다.

```text
attachments.jsonl
issue_relationships.jsonl
custom_field_catalog.jsonl
custom_field_values.jsonl
```

## 14. 테스트

```powershell
pytest tests/parser
pytest tests/exporter
pytest tests/test_cli_export.py
```

Structure 집중 테스트:

```powershell
pytest tests/parser/test_structure_parser.py
pytest tests/exporter/test_structure_jsonl_exporter.py
```

검증 항목:

- Attachment 메타데이터
- outward/inward canonicalization
- subtask parent_of
- Option 정규화
- Multi User Picker 정규화
- emailAddress 미복제
- Catalog 정의 생성
- 네 JSONL 파일 생성
- Summary/Warning 병합

## 15. 현재 제한

- Jira Wiki markup 전용 변환기 없음
- Atlassian Document Format 객체의 직접 텍스트 변환 없음
- 댓글 수정 이력 없음
- 삭제 댓글 복원 없음
- Attachment 바이너리 다운로드·본문 분석 없음
- Plugin `any` 객체별 전용 의미 해석 없음
- OpenCode Agent 지식 재가공은 아직 별도 단계

지원하지 않는 구조는 임의 추측하지 않고 경고와 RAW `source_path`를 남깁니다.
