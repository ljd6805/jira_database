# Jira 4단계 RAW 구조 조사 기록

## 1. 목적

이 문서는 4단계 `IssueStructureParser`를 구현하기 전에 실제 사내 Jira 파일럿 RAW 데이터를 구조만 조사한 결과를 기록합니다.

조사 대상은 항상 다음 **RAW 데이터**입니다.

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

업무 본문·사용자 이메일·첨부파일 내용은 조사 결과에 기록하지 않습니다.

## 2. 파일럿 범위

```text
IssueCount = 30
```

Issue/Comment Parser 실환경 검증과 동일한 파일럿 run을 기준으로 구조를 확인했습니다.

## 3. Attachment 구조

`fields.attachment`는 배열이며, 첨부파일이 있는 이슈에서 원소 객체의 key는 다음과 같이 확인됐습니다.

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

4단계에서는 파일 바이너리를 다운로드하지 않고 메타데이터만 ANALYSIS 계층에 저장합니다.

## 4. Issue Link 구조

30개 이슈 전체 조사 결과:

```text
IssueCount        : 30
IssuesWithLinks   : 1
TotalLinks        : 2
TotalInwardLinks  : 1
TotalOutwardLinks : 1
```

Link 객체 key:

```text
id
self
outwardIssue 또는 inwardIssue
type
```

`type` 객체 key:

```text
id
name
inward
outward
self
```

연결 이슈 객체 key:

```text
id
key
self
fields
```

### 방향 정규화 결정

ANALYSIS의 `issue_relationships.jsonl`은 현재 이슈 관점 문자열을 그대로 중복 저장하지 않고, Jira link type의 `outward` 의미를 canonical edge 방향으로 사용합니다.

예:

```text
A issue.json에서 outwardIssue=B  → A --blocks--> B
B issue.json에서 inwardIssue=A   → 같은 A --blocks--> B
```

동일 Jira Link가 양쪽 issue.json에 나타나면 `relationship_id`로 중복 제거합니다.

## 5. Hierarchy 구조

30개 이슈 전체 조사 결과:

```text
IssueCount           : 30
ParentFieldPresent   : 0
SubtasksFieldPresent : 30
IssuesWithParent     : 0
IssuesWithSubtasks   : 1
TotalSubtasks        : 4
```

Subtask 객체 key:

```text
id
key
self
fields
```

현재 파일럿에는 `fields.parent`가 없었지만, Parser는 향후 parent가 나타날 경우도 처리합니다.

Hierarchy는 최종적으로 다음 canonical 방향으로 저장합니다.

```text
parent_issue --parent_of--> child_issue
```

`fields.subtasks`와 향후 `fields.parent` 양쪽에서 같은 관계가 관찰되면 canonical key로 중복 제거할 수 있습니다.

## 6. Custom Field 전체 분포

30개 이슈 조사 결과:

```text
IssueCount                  : 30
IssuesWithNames             : 30
IssuesWithSchema            : 30
UniqueCustomFieldIds        : 220
UniqueNonNullCustomFieldIds : 16
TotalNonNullValues          : 447
```

즉 Jira가 제공하는 Custom Field 정의는 220종이지만, 파일럿 30개 이슈에서 실제 값이 있는 필드는 16종입니다.

### 실제 값의 최상위 타입

```text
PSCustomObject : 244
String         : 173
Object[]       : 30
```

## 7. Custom Field Object 구조

대표 Object 값에서 다음 key가 확인됐습니다.

```text
self
value
id
disabled
```

Schema 예:

```text
type   = option
custom = com.atlassian.jira.plugin.system.customfieldtypes:select
```

따라서 이런 값은 `value_kind=option`으로 정규화하고 사람이 읽는 `value`와 내부 `id`만 ANALYSIS에 저장합니다.

## 8. Custom Field Array 구조

대표 배열은 multi-user picker였습니다.

```text
type  = array
items = user
custom = com.atlassian.jira.plugin.system.customfieldtypes:multiuserpicker
```

배열 원소 key:

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

ANALYSIS에는 다음 정보만 복제합니다.

```text
displayName
name 또는 key
```

다음 개인정보·보조 URL은 RAW에만 남깁니다.

```text
emailAddress
avatarUrls
self
timeZone
```

## 9. 실제 사용 Custom Field Schema

파일럿에서 값이 존재한 16종의 schema는 다음 형태가 확인됐습니다.

```text
customfield_16608  string        scripted-field
customfield_16603  option        select
customfield_15841  option        select
customfield_15842  option        radiobuttons
customfield_16800  any           devsummary
customfield_10015  array  user   multiuserpicker
customfield_12300  any           gh-lexo-rank
customfield_15126  any           timeinstatus
customfield_10903  any           scripted-field
customfield_15110  option        select
customfield_15109  option        select
customfield_16310  option        select
customfield_16309  option        select
customfield_16308  option        select
customfield_11407  any           gh-global-rank
customfield_11305  option        select
```

전체 plugin 식별자는 RAW `schema.custom`에 보존되며 Catalog에도 문자열 그대로 저장합니다.

## 10. 구현 결정

4단계는 같은 `issue.json`을 세 번 읽지 않고 한 번 읽어서 다음 네 ANALYSIS 파일을 만듭니다.

```text
data/analysis/<run_id>/
├─ attachments.jsonl
├─ issue_relationships.jsonl
├─ custom_field_catalog.jsonl
└─ custom_field_values.jsonl
```

구성요소:

```text
IssueStructureParser
        ↓
IssueStructureJsonlExporter
        ↓
export-structure --run-id <RUN_ID>
```

## 11. 데이터 계층 원칙

```text
[RAW]
Jira API 원본 전체 구조
        ↓ 결정적 파싱
[ANALYSIS]
검색·DB·프로파일링에 필요한 값만 정규화
        ↓ 향후
[KNOWLEDGE]
OpenCode Agent가 의미를 해석한 파생 지식
```

RAW는 사실의 기준이며 ANALYSIS가 RAW를 대체하지 않습니다.
