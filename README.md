# Jira Raw Data Collector & Parser

Jira REST API를 이용해 **현재 계정이 조회할 수 있는 모든 프로젝트**를 발견하고, 파일럿에서는 각 프로젝트의 **최근 수정 이슈 최대 30개**를 원본 JSON으로 저장하는 읽기 전용 수집기입니다.

수집된 `issue.json`은 별도의 로컬 Parser와 JSONL Exporter를 통해 분석 가능한 중간 데이터로 변환할 수 있습니다.

현재 범위:

```text
Jira 연결 확인
→ 프로젝트 발견
→ Raw JSON 수집
→ SHA-256 검증
→ Issue 핵심 필드 파싱
→ issues.jsonl / parse_warnings.jsonl / summary.json 저장
```

아직 포함하지 않는 범위:

- 댓글 Parser와 `comments.jsonl`
- 첨부파일 바이너리 다운로드
- 첨부파일 메타데이터 정규화
- 이슈 링크 Parser
- Custom field Parser
- Excel Exporter
- DB 적재
- 임베딩, FAISS, RAG, MCP, 생성형 LLM

---

## 프로젝트 문서

- **[상세 설계 명세](docs/DESIGN.md)**  
  Collector의 아키텍처, 설정 계약, Jira API, Raw 저장 구조, SQLite checkpoint, resume 의미, 오류 처리, 보안과 테스트 전략을 설명합니다.

- **[댓글 수집 계약](docs/COMMENT_COLLECTION.md)**  
  이슈 상세의 내장 댓글과 무관하게 댓글 전용 API를 `startAt=0`부터 호출하는 규칙을 정의합니다.

- **[Issue Parser Core](docs/PARSER_CORE.md)**  
  `RunReader`, `IssueParser`, HTML description 변환과 JSONL Exporter 사용법을 설명합니다.

- **[Issue JSONL Exporter 상세 명세](docs/ISSUE_EXPORT_SPEC.md)**  
  입력·출력 스키마, 원자 저장, 오류 격리, 종료 코드, 보안과 재실행 의미를 정의합니다.

다른 개발자나 Agent가 후속 개발을 시작할 때는 이 README를 읽은 뒤 관련 상세 명세를 반드시 확인하십시오. 코드 또는 저장 계약을 변경하면 README와 해당 명세를 같은 변경 단위에서 갱신해야 합니다.

---

## 주요 특징

### Collector

- ID/Password 기반 HTTP Basic 인증
- Jira URL, 사용자명, 비밀번호를 `.env`에서 각각 입력
- 일반 동작값은 `config/settings.yaml`에서 수정
- Jira API 호출을 분당 최대 20회로 제한
- 계정이 조회 가능한 프로젝트 전체 발견
- 프로젝트별 최근 수정 이슈 최대 30개 수집
- 이슈 상세 원본을 `issue.json`으로 보존
- 댓글 전용 API를 `startAt=0`부터 끝까지 호출
- 댓글이 없는 이슈도 빈 첫 댓글 페이지 저장
- 프로젝트 하나가 실패해도 다음 프로젝트 계속 진행
- SQLite checkpoint를 이용한 중단 후 재개
- 임시 파일 작성 후 atomic replace
- SHA-256 기반 파일 무결성 검증
- 비밀번호, Authorization, Cookie를 로그에 출력하지 않음

### Parser & Exporter

- Jira API를 호출하지 않고 저장된 `issue.json`만 읽음
- 프로젝트와 이슈 폴더를 정렬해 재현 가능한 순서 보장
- 핵심 이슈 필드를 `IssueRecord`로 변환
- `<p dir="auto">` 형태의 HTML description 지원
- HTML 원문은 Raw JSON에 남기고 정제 텍스트만 JSONL에 저장
- 경로와 JSON 내부의 프로젝트·이슈 키 불일치 경고
- 한 이슈 파싱 실패가 전체 run 처리를 막지 않음
- `issues.jsonl`, `parse_warnings.jsonl`, `summary.json` 생성
- 대용량 본문을 전체 메모리에 쌓지 않고 이슈를 한 줄씩 기록
- 분석 결과도 임시 파일 + `os.replace` 방식으로 원자 저장
- Windows `WinError 5`, `32`, `33` 파일 잠금 재시도
- 모든 레코드에 원본 `source_path` 보존

---

## 요구 환경

- Python 3.11 이상
- HTTPS로 접근 가능한 Jira Server/Data Center 또는 호환 REST API
- Windows PowerShell, Linux shell 또는 macOS shell

---

## 설치

```bash
python -m venv .venv
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

패키지 설치:

```bash
python -m pip install --upgrade pip
pip install -e .
```

개발 및 테스트 의존성까지 설치:

```bash
pip install -e '.[dev]'
```

Windows PowerShell에서도 위 명령을 그대로 사용할 수 있습니다.

---

## 사용자 설정

### 1. `.env`

`.env.example`을 `.env`로 복사합니다.

Linux/macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env`에 다음 값을 입력합니다.

```dotenv
JIRA_BASE_URL=https://jira.example.com
JIRA_USERNAME=my-user-id
JIRA_PASSWORD=my-password
```

> `.env`는 Git에 올라가지 않습니다. 실제 인증정보를 `config/settings.yaml`, README, 테스트 fixture 또는 소스코드에 넣지 마십시오.

### 2. `config/settings.yaml`

주요 설정 예:

```yaml
jira:
  api_base_path: /rest/api/2
  myself_path: /myself
  project_list_path: /project
  issue_search_path: /search
  issue_path: /issue/{issue_key}
  comment_path: /issue/{issue_key}/comment

  tls:
    verify_ssl: false

  collection:
    issues_per_project: 30
    issue_order: updated_desc
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

현재 `download_attachments: false`이며 실제 첨부파일 바이너리 다운로드 로직도 구현되어 있지 않습니다. `issue.json`에는 Jira가 반환한 첨부파일 메타데이터가 포함될 수 있습니다.

사내 Jira가 자체 서명 인증서를 사용해 `verify_ssl: false`로 설정한 상태입니다. 외부 Jira 또는 신뢰할 수 없는 네트워크에서는 인증서 검증을 끄지 마십시오.

---

## 실행 명령 요약

```text
jira-collector check-connection
jira-collector discover-projects
jira-collector collect
jira-collector resume --run-id <RUN_ID>
jira-collector verify --run-id <RUN_ID>
jira-collector export-issues --run-id <RUN_ID>
```

도움말:

```bash
jira-collector --help
jira-collector export-issues --help
```

---

## Collector 실행

### 1. 연결 확인

```bash
jira-collector check-connection
```

### 2. 접근 가능한 프로젝트 확인

```bash
jira-collector discover-projects
```

### 3. 전체 파일럿 수집

```bash
jira-collector collect
```

### 4. 특정 프로젝트만 수집

```bash
jira-collector collect --project ABC
```

### 5. 프로젝트별 이슈 수 일시 변경

```bash
jira-collector collect --issues-per-project 10
```

### 6. 중단된 실행 재개

```bash
jira-collector resume --run-id <RUN_ID>
```

실패한 프로젝트도 다시 시도:

```bash
jira-collector resume --run-id <RUN_ID> --include-failed
```

### 7. 저장 파일 검증

```bash
jira-collector verify --run-id <RUN_ID>
```

---

## Issue Parser와 JSONL Exporter 실행

### 1. 실제 run_id 확인

PowerShell:

```powershell
Get-ChildItem ".\data\raw\runs" -Directory |
    Select-Object Name
```

### 2. JSONL 생성

```powershell
jira-collector export-issues --run-id <RUN_ID>
```

예:

```powershell
jira-collector export-issues --run-id 20260804T074500Z
```

이 명령은 Jira 서버에 접속하지 않고 다음 경로만 읽습니다.

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

### 3. 정상 출력 예

```text
발견 이슈: 30개
저장 성공: 30개
저장 실패: 0개
경고 및 오류: 0개
이슈 JSONL: ...\data\analysis\<run_id>\issues.jsonl
경고 JSONL: ...\data\analysis\<run_id>\parse_warnings.jsonl
요약 JSON: ...\data\analysis\<run_id>\summary.json
```

### 4. 출력 확인

요약 확인:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\summary.json" -Raw |
    ConvertFrom-Json |
    Format-List
```

첫 레코드 확인:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\issues.jsonl" -TotalCount 1 |
    ConvertFrom-Json |
    Format-List
```

경고 레코드 수:

```powershell
@(Get-Content ".\data\analysis\<RUN_ID>\parse_warnings.jsonl").Count
```

경고 파일이 0바이트이면 현재 Parser가 검토할 구조적 경고나 파싱 오류를 발견하지 않았다는 의미입니다.

---

## 전체 저장 구조

```text
data/
├─ raw/
│  └─ runs/
│     └─ <run_id>/
│        ├─ project_discovery/
│        │  └─ page_0001.json
│        └─ projects/
│           └─ ABC/
│              ├─ project.json
│              ├─ issue_search/
│              │  └─ page_0001.json
│              └─ issues/
│                 └─ ABC-123/
│                    ├─ issue.json
│                    └─ comments/
│                       ├─ page_0001.json
│                       └─ page_0002.json
├─ analysis/
│  └─ <run_id>/
│     ├─ issues.jsonl
│     ├─ parse_warnings.jsonl
│     └─ summary.json
├─ state/
│  └─ collector.db
└─ reports/
   └─ <run_id>.json
```

### 디렉터리 역할

| 경로 | 역할 |
|---|---|
| `data/raw` | Jira 응답의 원본 snapshot |
| `data/analysis` | Parser와 Exporter가 만든 중간 분석 데이터 |
| `data/state` | Collector checkpoint SQLite |
| `data/reports` | 수집 실행 보고서 |

`data/raw`와 `data/analysis`는 모두 Git에 올리지 않습니다.

---

## Raw 저장 계약

각 API 응답은 가급적 변형하지 않고 저장합니다. 수집기 메타데이터와 checkpoint는 SQLite에 별도로 기록합니다.

`collect_comments: true`이면 이슈 상세 응답 안의 `fields.comment` 내용과 관계없이 댓글 전용 API를 항상 `startAt=0`부터 호출합니다. 후속 처리에서는 댓글의 기준 원본을 `comments/page_*.json`으로 사용합니다.

이슈 상세 응답에도 댓글이 포함되어 있다면 동일 댓글이 `issue.json`과 댓글 페이지 양쪽에 존재할 수 있습니다. 향후 Comment Parser는 댓글 전용 API 파일을 읽고 `comment.id`를 기준으로 중복을 제거합니다.

현재 Raw JSON은 HTTP 응답 JSON을 Python 객체로 읽은 뒤 UTF-8 pretty JSON으로 다시 직렬화한 파일입니다. HTTP wire byte, 응답 header 전체, 요청 parameter 전체를 그대로 보존하는 구조는 아닙니다.

---

## Issue JSONL 저장 계약

`issues.jsonl`은 이슈 하나당 JSON 객체 한 줄입니다.

저장 필드:

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

저장하지 않는 필드:

```text
description_raw
description_rendered
전체 fields 객체
댓글
첨부파일 바이너리
custom field 전체 값
```

HTML description 원문은 `issue.json`에 이미 있으므로 JSONL에는 중복 저장하지 않습니다. `source_path`를 통해 언제든 원본으로 돌아갈 수 있습니다.

상세 계약은 [Issue JSONL Exporter 상세 명세](docs/ISSUE_EXPORT_SPEC.md)를 확인하십시오.

---

## 호출 제한

기본 정책:

```text
20 requests/minute
= 요청 시작 간 최소 3초
= 동시 요청 1개
```

재시도 요청도 호출 횟수에 포함됩니다. HTTP 429 응답에 `Retry-After`가 있으면 해당 시간을 우선합니다.

현재 limiter는 하나의 Python 프로세스 안에서만 적용됩니다. 여러 수집 프로세스를 동시에 실행하면 합산 20회/분을 보장하지 않습니다.

댓글 수집을 켜면 이슈마다 댓글 API 호출이 최소 1회 추가됩니다. 댓글이 많으면 페이지 수만큼 호출이 늘어납니다.

`export-issues`는 네트워크 요청을 하지 않으므로 Jira rate limit과 무관합니다.

---

## 수집 방식

1. `/project` 계열 API를 호출해 접근 가능한 프로젝트를 발견합니다.
2. 프로젝트별로 다음 JQL을 사용합니다.

```text
project = "ABC" ORDER BY updated DESC
```

3. 검색 결과에서 최대 30개 이슈를 선택합니다.
4. 각 이슈의 상세 원본을 `issue.json`으로 저장합니다.
5. 댓글 전용 API를 `startAt=0`부터 마지막 페이지까지 호출합니다.
6. 댓글이 0개여도 `comments/page_0001.json`에 빈 응답을 저장합니다.
7. 이슈 상세와 댓글 전체 페이지가 모두 저장된 뒤 checkpoint를 `completed`로 기록합니다.
8. 한 프로젝트가 실패하면 오류를 기록하고 다음 프로젝트로 넘어갑니다.

---

## Parser와 Exporter 처리 방식

1. `RunReader`가 `issue.json` 경로를 정렬해 탐색합니다.
2. `IssueParser`가 핵심 필드를 `IssueRecord`로 변환합니다.
3. HTML description에서 태그와 style을 제거해 `description_text`를 만듭니다.
4. 비치명적 구조 차이는 `ParseWarning`으로 기록합니다.
5. 손상된 이슈 JSON은 `issue_parse_error`로 기록하고 다음 이슈를 처리합니다.
6. 성공 이슈는 `issues.jsonl`에 한 줄씩 기록합니다.
7. 경고와 오류는 `parse_warnings.jsonl`에 기록합니다.
8. 통계를 `summary.json`에 마지막으로 기록합니다.

### Export 종료 코드

| 코드 | 의미 |
|---:|---|
| `0` | 모든 발견 이슈 저장 성공 |
| `1` | run_id, 설정, 파일 시스템 등 전체 명령 오류 |
| `2` | 일부 이슈 파싱 실패, 나머지 결과 저장 완료 |

---

## 원자 저장

Raw JSON과 분석 결과는 모두 대상 파일에 직접 쓰지 않습니다.

```text
같은 디렉터리에 임시 파일 생성
→ 내용 기록
→ flush + fsync
→ os.replace
```

Windows에서 백신이나 인덱서가 파일을 잠그는 경우 `WinError 5`, `32`, `33`을 재시도합니다.

같은 run_id로 `export-issues`를 다시 실행하면 기존 분석 결과를 새 결과로 교체합니다. Raw JSON은 변경하지 않습니다.

---

## 보안 원칙

- Jira 쓰기 API를 구현하지 않습니다.
- `.env`, `data/`, SQLite DB는 Git에서 제외됩니다.
- Authorization, Cookie, Password는 로그에 남기지 않습니다.
- 응답 전체를 기본 로그에 출력하지 않습니다.
- 읽기 전용 계정 사용을 권장합니다.
- 운영 환경에서는 HTTPS Jira URL을 사용합니다.
- 실제 Jira JSON을 테스트 fixture로 commit하지 않습니다.
- `issues.jsonl`에는 실제 업무 제목과 본문이 포함되므로 사내 데이터로 취급합니다.
- 외부 공유 시 `source_path`, 프로젝트 키, 이슈 키도 필요에 따라 마스킹합니다.

---

## 테스트

전체 테스트:

```bash
pytest
```

Parser와 Exporter만 실행:

```bash
pytest tests/parser tests/exporter tests/test_cli_export.py
```

테스트는 실제 Jira에 접속하지 않으며 mock HTTP session, 가짜 JSON과 임시 디렉터리를 사용합니다.

현재 Parser/Exporter 테스트는 다음을 검증합니다.

- HTML description 텍스트 변환
- HTML 원문 중복 저장 방지
- 경로와 JSON 키 불일치 경고
- 손상 JSON의 이슈 단위 오류 격리
- 빈 warning 파일 생성
- JSONL 필드 계약
- summary의 completed/partial 상태
- 분석 루트 밖 경로 차단
- 기존 파일 원자 교체
- CLI 명령 등록

테스트가 통과해도 모든 사내 Jira custom field 구조와의 호환성을 자동으로 보장하지는 않습니다. 실제 run에서 summary와 warning 코드만 확인하며 점진적으로 Parser를 확장합니다.

---

## 후속 개발 시작 순서

```bash
pip install -e '.[dev]'
pytest
jira-collector --help
```

그 다음 아래 문서를 순서대로 읽으십시오.

1. `README.md`
2. [`docs/DESIGN.md`](docs/DESIGN.md)
3. [`docs/COMMENT_COLLECTION.md`](docs/COMMENT_COLLECTION.md)
4. [`docs/PARSER_CORE.md`](docs/PARSER_CORE.md)
5. [`docs/ISSUE_EXPORT_SPEC.md`](docs/ISSUE_EXPORT_SPEC.md)
6. `config/settings.yaml`
7. `src/jira_collector/collector.py`
8. `src/jira_collector/parser/`
9. `src/jira_collector/exporter/`
10. `tests/`

---

## 현재 완료 기준

### Collector

- 접근 가능한 프로젝트 전체 발견
- 프로젝트별 최근 수정 이슈 최대 30개 저장
- 댓글 전용 API 전체 페이지 저장
- 원본 JSON SHA-256 검증
- 프로젝트별 실패 격리
- 강제 종료 후 checkpoint 재개
- 분당 20회 제한 준수
- 인증정보 미노출

### Issue Parser & Exporter

- run_id의 모든 `issue.json` 탐색
- 핵심 이슈 필드 파싱
- HTML description 텍스트 변환
- 경고와 파싱 오류 격리
- `issues.jsonl` 생성
- `parse_warnings.jsonl` 생성
- `summary.json` 생성
- Windows 파일 잠금 재시도
- 원본 수정 없음
- 실제 데이터 Git 미반영

코드 단위 테스트 통과와 실제 사내 run 검증은 다릅니다. 실제 환경에서는 다음 순서로 확인하십시오.

```text
check-connection
→ discover-projects
→ collect
→ verify
→ export-issues
→ summary.json 확인
→ parse_warnings.jsonl 확인
```

다음 구현 우선순위는 댓글 전용 파일을 병합하는 `CommentParser`입니다.
