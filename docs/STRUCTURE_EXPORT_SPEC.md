# Jira Structure Export 상세 명세

## 1. 목적

4단계는 이미 수집된 **RAW `issue.json`** 안에서 다음 구조 데이터를 추출해 ANALYSIS JSONL로 저장합니다.

```text
Attachment metadata
Issue Link
Parent/Subtask hierarchy
Custom Field definitions
Custom Field values
```

Jira API를 다시 호출하지 않습니다.

## 2. 입력 경로

```text
[RAW]
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

`IssueStructureParser`는 각 `issue.json`을 한 번만 읽고 모든 구조 데이터를 함께 추출합니다.

## 3. 실행 명령

```powershell
python -m jira_collector.cli export-structure --run-id <RUN_ID>
```

또는 editable 설치 후:

```powershell
jira-collector export-structure --run-id <RUN_ID>
```

## 4. 출력 경로

```text
[ANALYSIS]
data/analysis/<run_id>/
├─ attachments.jsonl
├─ issue_relationships.jsonl
├─ custom_field_catalog.jsonl
├─ custom_field_values.jsonl
├─ parse_warnings.jsonl
└─ summary.json
```

## 5. Attachment 계약

RAW 위치:

```text
/fields/attachment
```

저장 필드:

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

파일 바이너리는 다운로드하지 않습니다.

`author` 전체 객체도 복제하지 않습니다. 사용자 표시 이름과 내부 식별용 name/key만 추출합니다.

## 6. Issue Relationship 계약

RAW 위치:

```text
/fields/issuelinks
/fields/parent
/fields/subtasks
```

출력은 문서 관점 문자열이 아니라 **canonical graph edge**로 저장합니다.

필드:

```text
run_id
observed_project_key
relationship_id
relationship_category
relationship_type
relationship_text
source_issue_key
target_issue_key
source_summary
source_status
target_summary
target_status
observed_from_issue_key
observed_direction
derived
source_path
```

### Issue Link 방향

Jira link type의 `outward` 문구를 canonical edge 의미로 사용합니다.

```text
outwardIssue 관찰:
current --outward--> linked

inwardIssue 관찰:
linked --outward--> current
```

예:

```text
A에서 outwardIssue=B, type.outward=blocks
→ A --blocks--> B

B에서 inwardIssue=A
→ 동일한 A --blocks--> B
```

동일 `relationship_id`는 한 번만 저장합니다.

### Hierarchy 방향

```text
parent --parent_of--> child
```

`fields.parent`와 `fields.subtasks`가 같은 관계를 동시에 제공하면 canonical 관계 key로 중복 제거합니다.

## 7. Custom Field Catalog 계약

RAW 정의 위치:

```text
/names
/schema
```

한 run에서 `field_id` 하나당 Catalog 레코드 하나만 저장합니다.

필드:

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

동일 `field_id`가 이슈별로 다른 name/schema를 가지면 첫 정의를 유지하고 다음 경고를 기록합니다.

```text
custom_field_definition_mismatch
```

## 8. Custom Field Value 계약

RAW 값 위치:

```text
/fields/customfield_*
```

null은 Value JSONL에 저장하지 않습니다.

필드:

```text
run_id
project_key
issue_key
field_id
field_name
schema_type
schema_items
schema_custom
actual_type
value_kind
display_value
display_values
value_id
value_ids
user_keys
value_shape
source_path
```

### value_kind

```text
string
scalar
option
user_array
generic_object
generic_array
```

### Option

확인된 형태:

```text
self
value
id
disabled
```

저장:

```text
display_value = value
value_id = id
```

### User Array

확인된 multi-user picker 원소에는 emailAddress 등 개인정보가 포함될 수 있습니다.

ANALYSIS에 저장:

```text
display_values
user_keys
value_shape
```

ANALYSIS에 저장하지 않음:

```text
emailAddress
avatarUrls
self
timeZone
전체 user 객체
```

### Plugin `any`

Jira plugin field는 schema.type이 `any`일 수 있으므로 schema만으로 실제 타입을 가정하지 않습니다.

```text
schema_type = Jira schema 값
actual_type = 실제 JSON 값 타입
```

알려진 표시값이 있으면 추출하고, 복잡한 원본 객체 전체는 ANALYSIS에 복제하지 않습니다. 구조 확인용 `value_shape`만 남깁니다.

## 9. 경고 처리

공통 파일:

```text
[ANALYSIS]
data/analysis/<run_id>/parse_warnings.jsonl
```

component:

```text
attachments
relationships
custom_fields
structure
```

대표 경고/오류:

```text
invalid_attachment_array
invalid_attachment_object
missing_attachment_id
invalid_attachment_size
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
custom_field_definition_mismatch
issue_structure_parse_error
```

한 이슈의 구조 파싱 실패는 전체 run 처리를 중단하지 않습니다.

## 10. Summary 갱신

`summary.json` 2.0에 다음 영역을 추가합니다.

```text
attachments
relationships
custom_fields
```

4단계는 세 영역을 `update_sections()` 한 번으로 원자 갱신합니다.

## 11. 재실행 의미

같은 run_id에 다시 실행하면 네 구조 JSONL을 현재 RAW 기준으로 다시 생성합니다.

공통 Warning에서는 다음 component만 교체하고 기존 Issue/Comment 경고는 보존합니다.

```text
attachments
relationships
custom_fields
structure
```

## 12. 개인정보와 보안

원칙:

```text
RAW = 사실 원본
ANALYSIS = 필요한 파생 값만
```

Custom Field의 사용자 객체나 Attachment author 객체를 그대로 복제하지 않습니다.

내부 Jira URL은 ANALYSIS에 존재할 수 있으므로 향후 MCP 외부 응답에서는 그대로 노출하지 않고 공식 Jira 출처 생성 규칙을 별도로 적용합니다.

## 13. 종료 코드

```text
0 = 모든 구조 데이터가 정상 파싱됨
2 = 일부 이슈/Attachment/Relationship/Custom Field 실패 또는 정의 불일치
1 = 설정·파일·Summary/Warning 저장 자체의 치명적 오류
```

## 14. 테스트

```powershell
pytest tests/parser/test_structure_parser.py
pytest tests/exporter/test_structure_jsonl_exporter.py
pytest tests/test_cli_export.py
```

검증 항목:

- Attachment 메타데이터 추출
- outward/inward canonical edge
- Subtask parent_of
- Option 정규화
- Multi User Picker 정규화
- 이메일 미복제
- Catalog 생성
- 네 JSONL 생성
- Summary 영역 갱신
