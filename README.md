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
→ issues.jsonl / comments.jsonl
→ parse_warnings.jsonl / summary.json 2.0
```

아직 포함하지 않는 범위:

- 첨부파일 바이너리 다운로드
- 첨부파일 메타데이터 정규화
- 이슈 링크 Parser
- Custom field Parser
- Excel Exporter
- DB 적재
- 임베딩, FAISS, RAG, MCP, 생성형 LLM

---

## 프로젝트 문서

- [상세 Collector 설계](docs/DESIGN.md)
- [댓글 원본 수집 계약](docs/COMMENT_COLLECTION.md)
- [Parser Core](docs/PARSER_CORE.md)
- [Issue JSONL Exporter 명세](docs/ISSUE_EXPORT_SPEC.md)
- [Comment JSONL Exporter 명세](docs/COMMENT_EXPORT_SPEC.md)
- [공통 Summary·Warning 저장 계약](docs/RUN_SUMMARY_SPEC.md)

코드 또는 저장 형식을 바꾸면 README와 관련 명세를 같은 변경 단위에서 함께 갱신해야 합니다.

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

- Jira API를 다시 호출하지 않고 `data/raw`만 읽음
- HTML description과 HTML comment body를 일반 텍스트로 변환
- 이슈와 댓글의 HTML 원문은 Raw JSON에만 보존
- 댓글 페이지를 파일명 순서로 병합
- `comment.id` 기준 중복 제거
- 작성자는 `displayName → name → key` 순서로 추출
- 작성자 이메일, avatar URL, Jira self URL은 JSONL에 저장하지 않음
- 한 이슈 또는 댓글 페이지의 오류가 전체 run을 중단시키지 않음
- 결과를 JSONL로 한 줄씩 기록해 전체 본문을 메모리에 쌓지 않음
- 분석 결과도 임시 파일 작성 후 `os.replace`로 원자 저장
- Windows `WinError 5`, `32`, `33` 재시도
- Issue와 Comment Exporter가 공통 `summary.json`과 `parse_warnings.jsonl`을 안전하게 병합

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

현재 `download_attachments: false`이며 실제 첨부파일 바이너리 다운로드 로직도 없습니다. `issue.json`에는 Jira가 반환한 첨부파일 메타데이터가 들어 있을 수 있습니다.

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
```

도움말:

```powershell
python -m jira_collector.cli --help
python -m jira_collector.cli export-comments --help
```

Windows에서 오래된 `jira-collector.exe`가 잡히면 우선 `python -m jira_collector.cli` 방식으로 실행하십시오.

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

## Issue Exporter 실행

```powershell
jira-collector export-issues --run-id <RUN_ID>
```

읽는 원본:

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

저장 결과:

```text
data/analysis/<run_id>/issues.jsonl
```

Issue JSONL 필드:

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

`description_raw`과 `description_rendered`는 Raw JSON에 이미 있으므로 JSONL에 중복 저장하지 않습니다.

---

## Comment Exporter 실행

```powershell
jira-collector export-comments --run-id <RUN_ID>
```

읽는 원본:

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/comments/page_*.json
```

저장 결과:

```text
data/analysis/<run_id>/comments.jsonl
```

Comment JSONL 필드:

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
body_text
body_format
source_path
source_page
```

저장하지 않는 값:

```text
body_raw HTML
emailAddress
avatarUrls
self URL
전체 author 객체
```

댓글은 `page_0001.json`, `page_0002.json` 순으로 읽으며, `comment.id`가 중복되면 첫 번째 값만 저장하고 경고를 남깁니다.

정상 실행 출력 예:

```text
대상 이슈: 30개
댓글 페이지: 30개
발견 댓글: 142개
저장 댓글: 142개
중복 댓글: 0개
실패 페이지: 0개
실패 댓글: 0개
댓글 원본 누락 이슈: 0개
경고 및 오류: 0개
댓글 JSONL: ...\comments.jsonl
경고 JSONL: ...\parse_warnings.jsonl
요약 JSON: ...\summary.json
```

---

## 분석 결과 구조

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

Issue와 Comment Exporter는 같은 파일에서 자기 영역만 갱신합니다.

```json
{
  "schema_version": "2.0",
  "run_id": "20260804T043628Z",
  "status": "completed",
  "issues": {
    "status": "completed",
    "discovered_count": 30,
    "exported_count": 30,
    "failed_count": 0,
    "warning_count": 0,
    "parse_error_count": 0,
    "description_formats": {"html": 30}
  },
  "comments": {
    "status": "completed",
    "issue_count": 30,
    "page_count": 30,
    "discovered_count": 142,
    "exported_count": 142,
    "duplicate_count": 0,
    "failed_page_count": 0,
    "failed_comment_count": 0,
    "missing_comment_source_count": 0,
    "warning_count": 0,
    "body_formats": {"html": 142}
  }
}
```

동작 규칙:

- 기존 파일이 없으면 2.0 문서를 새로 생성
- 기존 1.0 Issue 요약은 자동으로 2.0으로 변환
- 기존 2.0 파일에서는 다른 Exporter 영역을 보존
- 깨진 JSON은 자동으로 덮어쓰지 않음
- 파일 경로의 run_id와 내부 run_id가 다르면 중단
- Issue와 Comment가 모두 `completed`일 때 전체 상태가 `completed`
- 한 영역만 실행됐으면 전체 상태가 `incomplete`
- 한 영역에 실패가 있으면 전체 상태가 `partial` 또는 `failed`

---

## 공통 `parse_warnings.jsonl`

각 경고에는 `component`가 포함됩니다.

```json
{"component":"issues","severity":"warning","code":"issue_key_mismatch"}
{"component":"comments","severity":"error","code":"comment_page_parse_error"}
```

Exporter를 다시 실행하면 자기 component의 기존 경고만 교체하고 다른 component 경고는 보존합니다.

기존 Issue 전용 경고에는 `component`가 없을 수 있으며, 이 경우 `issues` 경고로 해석합니다.

---

## 결과 확인

요약:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\summary.json" -Raw |
    ConvertFrom-Json |
    Format-List
```

첫 댓글 레코드:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\comments.jsonl" -TotalCount 1 |
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

## 재실행 의미

Exporter는 증분 append가 아니라 해당 component의 현재 결과를 다시 생성합니다.

- `issues.jsonl`은 Issue Exporter 실행 결과로 전체 교체
- `comments.jsonl`은 Comment Exporter 실행 결과로 전체 교체
- `summary.json`은 해당 영역만 병합
- `parse_warnings.jsonl`은 해당 component 경고만 교체

따라서 다음 실행 순서는 모두 안전해야 합니다.

```text
export-issues → export-comments
export-comments → export-issues
export-comments 재실행
export-issues 재실행
```

---

## 보안 원칙

- 실제 Jira 원본과 분석 결과를 Git에 올리지 않음
- 인증정보를 소스, 문서, 테스트 fixture에 넣지 않음
- 실제 제목·description·comment body를 로그에 출력하지 않음
- 작성자 이메일과 avatar URL을 분석 JSONL에서 제외
- 원본 HTML은 Raw JSON에만 보존
- 테스트는 가짜 JSON만 사용

---

## 테스트

```powershell
pytest
```

Parser와 Exporter 관련 테스트만 실행:

```powershell
pytest tests/parser tests/exporter tests/test_cli_export.py
```

테스트는 실제 Jira API를 호출하지 않고 임시 디렉터리와 가짜 JSON을 사용합니다.

---

## 다음 개발 순서

```text
1. Issue Parser / Exporter       완료
2. Comment Parser / Exporter     완료
3. Attachment metadata Parser
4. Issue Link Parser
5. Custom field Profiler
6. Excel Exporter
7. DB 논리 스키마 결정
```
