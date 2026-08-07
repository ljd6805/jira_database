# Jira Raw Data Collector & Parser

Jira REST API를 이용해 현재 계정이 조회할 수 있는 프로젝트와 이슈를 읽기 전용으로 수집하고, 저장된 Raw JSON을 로컬 Parser와 JSONL Exporter로 분석 가능한 중간 데이터로 변환하는 프로젝트입니다.

현재 파일럿 기본값은 프로젝트별 최근 수정 이슈 최대 30개입니다.

## 현재 구현 범위

```text
Jira 연결 확인
→ 접근 가능한 프로젝트 발견
→ 이슈 상세와 댓글 전용 API 원본 수집
→ Raw JSON SHA-256 검증
→ IssueParser
→ CommentParser
→ IssueStructureParser
→ issues.jsonl / comments.jsonl
→ attachments.jsonl / issue_relationships.jsonl
→ custom_field_catalog.jsonl / custom_field_values.jsonl
→ parse_warnings.jsonl / summary.json 2.0
```

아직 포함하지 않는 범위:

- 첨부파일 바이너리 다운로드 및 본문 분석
- OpenCode Agent 지식 재가공
- Excel/Data Profiling 보고서
- DB 적재
- 청크 생성
- 임베딩, FAISS, RAG, MCP, 생성형 LLM

---

## 데이터 계층

경로를 사용할 때는 항상 어느 계층인지 구분합니다.

```text
[RAW]
data/raw/runs/<run_id>/...
Jira API 원본. 사실의 기준이며 Parser가 수정하지 않음.

[ANALYSIS]
data/analysis/<run_id>/...
결정적 Parser/Exporter 결과. JSONL·Summary·Warning.

[KNOWLEDGE]  # 향후
data/knowledge/<run_id>/...
OpenCode Agent가 Issue 전체를 분석해 만든 파생 지식.

[DB] / [VECTOR]  # 향후
SQLite / Embedding / FAISS
```

---

## 프로젝트 문서

- [상세 Collector 설계](docs/DESIGN.md)
- [댓글 원본 수집 계약](docs/COMMENT_COLLECTION.md)
- [Parser Core](docs/PARSER_CORE.md)
- [Issue JSONL Exporter 명세](docs/ISSUE_EXPORT_SPEC.md)
- [Comment JSONL Exporter 명세](docs/COMMENT_EXPORT_SPEC.md)
- [4단계 Structure Export 명세](docs/STRUCTURE_EXPORT_SPEC.md)
- [실제 Jira 4단계 RAW 구조 조사 기록](docs/JIRA_STRUCTURE_PROFILE.md)
- [공통 Summary·Warning 저장 계약](docs/RUN_SUMMARY_SPEC.md)

코드 또는 저장 형식을 바꾸면 README와 관련 명세를 같은 변경 단위에서 함께 갱신합니다.

---

## 주요 특징

### Collector

- ID/Password 기반 HTTP Basic 인증
- `.env`에서 Jira URL, 사용자명, 비밀번호 입력
- 일반 설정은 `config/settings.yaml`에서 관리
- Jira API 호출을 분당 최대 20회로 제한
- 접근 가능한 프로젝트 전체 발견
- 프로젝트별 최근 수정 이슈 최대 30개 수집
- 이슈 상세 응답을 `issue.json`으로 보존
- 댓글 전용 API를 항상 `startAt=0`부터 마지막 페이지까지 수집
- 댓글이 없어도 빈 `comments/page_0001.json` 저장
- 프로젝트별 실패 격리와 SQLite checkpoint 재개
- 원자적 파일 저장과 SHA-256 검증

### Parser와 Exporter

- Jira API를 다시 호출하지 않고 `[RAW] data/raw`만 읽음
- HTML description과 HTML comment body를 일반 텍스트로 변환
- 이슈와 댓글의 HTML 원문은 RAW JSON에만 보존
- 댓글 페이지를 파일명 순서로 병합하고 `comment.id` 중복 제거
- 작성자는 `displayName → name → key` 순서로 추출
- 작성자 이메일, avatar URL, Jira self URL은 일반 분석 JSONL에 불필요하게 복제하지 않음
- 한 이슈 또는 댓글 페이지 오류가 전체 run을 중단시키지 않음
- 결과를 JSONL 한 줄씩 스트리밍 기록
- 임시 파일 작성 후 `os.replace`로 원자 저장
- Windows `WinError 5`, `32`, `33` 재시도
- Exporter가 공통 `summary.json`과 `parse_warnings.jsonl`을 영역별로 안전하게 병합

### 4단계 Structure Parser

Attachment·Issue Link·Hierarchy·Custom Field가 모두 같은 `[RAW] issue.json` 안에 있으므로 같은 파일을 세 번 읽지 않습니다.

```text
issue.json 1회 읽기
       ↓
IssueStructureParser
       ├─ Attachment metadata
       ├─ Issue Link + Hierarchy
       ├─ Custom Field definitions
       └─ Custom Field values
       ↓
IssueStructureJsonlExporter
```

Issue Relationship은 그래프에서 중복을 줄이기 위해 canonical edge로 저장합니다.

```text
Issue Link: Jira type.outward 방향
Hierarchy : parent --parent_of--> child
```

---

## 요구 환경

- Python 3.11 이상
- Jira Server/Data Center 또는 호환 REST API
- Windows PowerShell, Linux shell 또는 macOS shell

---

## 설치

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

설치:

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

브랜치를 변경하거나 코드를 갱신한 뒤에는 editable install을 다시 실행하는 것이 안전합니다.

---

## 환경 설정

`.env.example`을 `.env`로 복사합니다.

```powershell
Copy-Item .env.example .env
```

`.env`:

```dotenv
JIRA_BASE_URL=https://jira.example.com
JIRA_USERNAME=my-user-id
JIRA_PASSWORD=my-password
```

주요 YAML 설정:

```yaml
jira:
  api_base_path: /rest/api/2
  issue_path: /issue/{issue_key}
  comment_path: /issue/{issue_key}/comment

  collection:
    issues_per_project: 30
    collect_comments: true
    download_attachments: false

  rate_limit:
    requests_per_minute: 20
    max_concurrency: 1

storage:
  data_root: ./data
  raw_directory: raw
  state_directory: state
  report_directory: reports
```

현재 `download_attachments: false`이며 실제 첨부파일 바이너리 다운로드 로직도 없습니다. `issue.json`에 들어 있는 Attachment 메타데이터만 4단계에서 정규화합니다.

---

## 명령 요약

```text
jira-collector check-connection
jira-collector discover-projects
jira-collector collect
jira-collector resume --run-id <RUN_ID>
jira-collector verify --run-id <RUN_ID>
jira-collector export-issues --run-id <RUN_ID>
jira-collector export-comments --run-id <RUN_ID>
jira-collector export-structure --run-id <RUN_ID>
```

Windows에서 오래된 `jira-collector.exe`가 잡히면 다음 방식을 우선 사용합니다.

```powershell
python -m jira_collector.cli --help
python -m jira_collector.cli export-structure --help
```

---

## Collector 실행

```powershell
jira-collector check-connection
jira-collector discover-projects
jira-collector collect
```

특정 프로젝트만 수집:

```powershell
jira-collector collect --project ABC
```

중단된 실행 재개:

```powershell
jira-collector resume --run-id <RUN_ID>
```

무결성 검증:

```powershell
jira-collector verify --run-id <RUN_ID>
```

---

## Issue Exporter

```powershell
python -m jira_collector.cli export-issues --run-id <RUN_ID>
```

읽는 원본:

```text
[RAW]
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

저장 결과:

```text
[ANALYSIS]
data/analysis/<run_id>/issues.jsonl
```

주요 필드:

```text
run_id
project_key
issue_key
jira_id
summary
description_text
description_format
issue_type
status
priority
created_at
updated_at
source_path
```

---

## Comment Exporter

```powershell
python -m jira_collector.cli export-comments --run-id <RUN_ID>
```

읽는 원본:

```text
[RAW]
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/comments/page_*.json
```

저장 결과:

```text
[ANALYSIS]
data/analysis/<run_id>/comments.jsonl
```

실환경 검증 결과:

```text
대상 이슈: 30
발견 댓글: 278
저장 댓글: 278
중복: 0
실패: 0
경고: 0
```

---

## 4단계 Structure Exporter

실행:

```powershell
$runId = "<RUN_ID>"
python -m jira_collector.cli export-structure --run-id $runId
```

읽는 원본:

```text
[RAW]
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

생성 결과:

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

### Attachment

저장 내용:

```text
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

바이너리는 다운로드하지 않습니다.

### Relationship

입력:

```text
fields.issuelinks
fields.parent
fields.subtasks
```

출력은 canonical edge입니다.

```text
relationship_category=issue_link
source_issue_key --relationship_text--> target_issue_key

relationship_category=hierarchy
parent --parent_of--> child
```

`relationship_id`가 같은 Jira Link 또는 동일 parent-child 관계는 중복 제거합니다.

### Custom Field Catalog

`names`와 `schema`를 이용해 전체 Custom Field 정의를 `field_id` 기준으로 한 번씩 저장합니다.

파일럿 RAW 조사:

```text
UniqueCustomFieldIds = 220
```

### Custom Field Values

null이 아닌 값만 저장합니다.

파일럿 RAW 조사:

```text
UniqueNonNullCustomFieldIds = 16
TotalNonNullValues          = 447
```

확인된 주요 값 종류:

```text
string
option
user_array
generic_object / generic_array
```

Multi User Picker에서 `emailAddress`, `avatarUrls`, `self`, `timeZone` 같은 원본 사용자 속성은 ANALYSIS에 복제하지 않습니다.

---

## 전체 분석 결과 구조

```text
data/
├─ raw/
│  └─ runs/
│     └─ <run_id>/
│        └─ projects/
│           └─ ABC/
│              └─ issues/
│                 └─ ABC-123/
│                    ├─ issue.json
│                    └─ comments/
│                       ├─ page_0001.json
│                       └─ page_0002.json
├─ analysis/
│  └─ <run_id>/
│     ├─ issues.jsonl
│     ├─ comments.jsonl
│     ├─ attachments.jsonl
│     ├─ issue_relationships.jsonl
│     ├─ custom_field_catalog.jsonl
│     ├─ custom_field_values.jsonl
│     ├─ parse_warnings.jsonl
│     └─ summary.json
├─ state/
│  └─ collector.db
└─ reports/
   └─ <run_id>.json
```

`data/raw`와 `data/analysis`는 Git에 올리지 않습니다.

---

## 공통 `summary.json` 2.0

지원 영역:

```text
issues
comments
attachments
relationships
custom_fields
```

Issue/Comment의 기존 2.0 의미를 깨지 않기 위해 `attachments`, `relationships`, `custom_fields`가 아직 `not_run`이어도 Issue와 Comment가 정상 완료됐다면 기존 전체 status는 `completed`를 유지할 수 있습니다.

4단계 `export-structure`는 세 새 영역을 한 번의 `update_sections()` 호출로 원자 갱신합니다.

---

## 공통 `parse_warnings.jsonl`

지원 component:

```text
issues
comments
attachments
relationships
custom_fields
structure
```

각 Exporter 재실행 시 자기 component 경고만 교체하고 다른 component 경고는 보존합니다.

4단계는 여러 component를 `replace_components()` 한 번으로 갱신합니다.

---

## 결과 확인

Summary:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\summary.json" -Raw |
    ConvertFrom-Json |
    Format-List
```

첫 Structure 결과:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\attachments.jsonl" -TotalCount 1 |
    ConvertFrom-Json |
    Format-List

Get-Content ".\data\analysis\<RUN_ID>\issue_relationships.jsonl" -TotalCount 1 |
    ConvertFrom-Json |
    Format-List

Get-Content ".\data\analysis\<RUN_ID>\custom_field_values.jsonl" -TotalCount 1 |
    ConvertFrom-Json |
    Format-List
```

경고 코드 집계:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\parse_warnings.jsonl" |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Group-Object component, code |
    Select-Object Count, Name
```

---

## 보안 원칙

- 실제 Jira 원본과 분석 결과를 Git에 올리지 않음
- 인증정보를 소스, 문서, 테스트 fixture에 넣지 않음
- 실제 제목·description·comment body를 로그에 출력하지 않음
- 사용자 이메일과 avatar URL을 일반 ANALYSIS JSONL에서 최소화
- 원본 HTML과 복잡한 plugin 객체는 RAW JSON을 사실 기준으로 유지
- 테스트는 가짜 JSON만 사용

---

## 테스트

전체:

```powershell
pytest
```

Parser/Exporter 집중 테스트:

```powershell
pytest tests/parser tests/exporter tests/test_cli_export.py
```

4단계만:

```powershell
pytest tests/parser/test_structure_parser.py
pytest tests/exporter/test_structure_jsonl_exporter.py
pytest tests/test_cli_export.py
```

---

## 구현 진행 상태와 다음 순서

```text
1. Jira Raw 수집                         완료
2. Issue Parser / Exporter               완료 + 실환경 검증
3. Comment Parser / Exporter             완료 + 실환경 검증
4. Structure Parser / Exporter           구현 완료, 실환경 검증 대기
   ├─ Attachment metadata
   ├─ Issue Link + Hierarchy
   ├─ Custom Field Catalog
   └─ Custom Field Values
5. OpenCode Agent 입력 패키지            예정
6. OpenCode Agent 지식 재가공            예정
7. 지식 추출 검증                        예정
8. Data Profiling / Excel                예정
9. DB 논리 스키마 및 SQLite 적재         예정
10. 원문·지식 Chunk                      예정
11. BGE-M3 Embedding / FAISS             예정
12. Retrieval 검증                       예정
13. MCP                                  예정
```
