# Jira Raw Data Collector

Jira REST API를 이용해 **현재 계정이 조회할 수 있는 모든 프로젝트**를 발견하고, 파일럿에서는 각 프로젝트의 **최근 수정 이슈 최대 30개**를 원본 JSON으로 저장하는 읽기 전용 수집기입니다.

현재 범위는 원본 수집과 검증까지입니다. 임베딩, FAISS, RAG, MCP, 생성형 LLM은 포함하지 않습니다.

## 프로젝트 문서

- **[상세 설계 명세](docs/DESIGN.md)**: 아키텍처, 모듈 책임, 설정 계약, Jira API 요청·응답 형식, 저장 구조, SQLite 스키마, 상태 전이, resume 의미, 오류 처리, 보안, 테스트 전략, 알려진 제한과 Agent 인수인계 절차를 설명합니다.
- `README.md`: 설치, 설정, 실행과 기본 운영 방법을 빠르게 확인하는 문서입니다.

다른 개발자나 Agent가 후속 개발을 시작할 때는 이 README를 확인한 뒤 반드시 [`docs/DESIGN.md`](docs/DESIGN.md)를 읽으십시오. 코드 또는 설정 계약을 변경하면 README와 상세 설계 명세도 같은 변경 단위에서 갱신해야 합니다.

## 주요 특징

- ID/Password 기반 HTTP Basic 인증
- Jira URL, 사용자명, 비밀번호를 `.env`에서 각각 입력
- 일반 동작값은 `config/settings.yaml`에서 수정
- Jira API 호출을 분당 최대 20회로 제한
- 계정이 조회 가능한 프로젝트 전체 발견
- 프로젝트별 최근 수정 이슈 최대 30개 수집
- 이슈 원본과 필요한 댓글 추가 페이지를 그대로 JSON으로 보존
- 프로젝트 하나가 실패해도 다음 프로젝트 계속 진행
- SQLite checkpoint를 이용한 중단 후 재개
- 임시 파일 작성 후 atomic replace
- SHA-256 기반 파일 무결성 검증
- 비밀번호, Authorization, Cookie를 로그에 출력하지 않음

## 요구 환경

- Python 3.11 이상
- HTTPS로 접근 가능한 Jira Server/Data Center 또는 호환 REST API

## 설치

```bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e .
```

개발 및 테스트 의존성까지 설치하려면 다음을 사용합니다.

```bash
pip install -e '.[dev]'
```

## 사용자 설정

`.env.example`을 `.env`로 복사한 뒤 세 값을 입력합니다.

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env`:

```dotenv
JIRA_BASE_URL=https://jira.example.com
JIRA_USERNAME=my-user-id
JIRA_PASSWORD=my-password
```

> `.env`는 Git에 올라가지 않습니다. 실제 인증정보를 `config/settings.yaml`이나 소스코드에 넣지 마십시오.

일반 설정은 `config/settings.yaml`에서 수정합니다.

```yaml
jira:
  api_base_path: /rest/api/2
  project_list_path: /project
  issue_search_path: /search
  issue_path: /issue/{issue_key}
  comment_path: /issue/{issue_key}/comment

  collection:
    issues_per_project: 30
    issue_order: updated_desc
    collect_comments: true

  rate_limit:
    requests_per_minute: 20
    max_concurrency: 1
```

Jira 환경마다 REST 경로가 다르면 이 YAML만 바꾸면 됩니다.

## 실행

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

### 5. 프로젝트별 이슈 수를 일시적으로 변경

```bash
jira-collector collect --issues-per-project 10
```

### 6. 중단된 실행 재개

```bash
jira-collector resume --run-id <RUN_ID>
```

실패한 프로젝트도 다시 시도하려면:

```bash
jira-collector resume --run-id <RUN_ID> --include-failed
```

### 7. 저장 파일 검증

```bash
jira-collector verify --run-id <RUN_ID>
```

## 저장 구조

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
│                       └─ page_0001.json
├─ state/
│  └─ collector.db
└─ reports/
   └─ <run_id>.json
```

각 API 응답은 가급적 변형하지 않고 저장합니다. 수집기 메타데이터와 checkpoint는 SQLite에 별도로 기록합니다.

정확히 말하면 현재 Raw JSON은 Jira 응답 JSON을 파싱한 뒤 UTF-8 pretty JSON으로 다시 직렬화한 파일입니다. HTTP wire byte, 응답 header 전체, 요청 parameter 전체를 그대로 보존하는 구조는 아닙니다. 정확한 저장 계약과 향후 개선점은 [상세 설계 명세](docs/DESIGN.md#15-raw-저장-명세)를 참고하십시오.

## 호출 제한

기본 정책은 다음과 같습니다.

```text
20 requests/minute
= 요청 시작 간 최소 3초
= 동시 요청 1개
```

재시도 요청도 호출 횟수에 포함됩니다. HTTP 429 응답에 `Retry-After`가 있으면 해당 시간을 우선합니다.

현재 limiter는 하나의 Python 프로세스 안에서만 적용됩니다. 여러 프로세스를 동시에 실행하면 합산 20회/분을 보장하지 않으므로 파일럿에서는 수집 프로세스를 하나만 실행하십시오.

## 수집 방식

1. `/project` 계열 API를 호출해 접근 가능한 프로젝트를 발견합니다.
2. 각 프로젝트에 대해 다음과 같은 JQL을 사용합니다.

```text
project = "ABC" ORDER BY updated DESC
```

3. 검색 결과에서 최대 30개 이슈를 선택합니다.
4. 각 이슈의 상세 원본을 저장합니다.
5. 이슈 응답의 댓글이 일부만 포함된 경우에만 댓글 API의 남은 페이지를 추가 수집합니다.
6. 한 프로젝트가 실패하면 오류를 기록하고 다음 프로젝트로 넘어갑니다.

resume의 정확한 상태 전이와 현재 제한은 [상세 설계 명세의 Resume 의미론](docs/DESIGN.md#13-resume-의미론)을 확인하십시오.

## 보안 원칙

- Jira 쓰기 API는 구현하지 않습니다.
- `.env`, `data/`, SQLite DB는 Git에서 제외됩니다.
- Authorization, Cookie, Password는 로그에 남기지 않습니다.
- 응답 전체를 기본 로그에 출력하지 않습니다.
- 읽기 전용 계정 사용을 권장합니다.
- 운영 환경에서는 HTTPS Jira URL을 사용합니다.

## 테스트

```bash
pytest
```

테스트는 실제 Jira에 접속하지 않으며 mock HTTP session과 임시 디렉터리를 사용합니다.

테스트가 통과해도 실제 사내 Jira API 형식과의 호환성이 자동으로 보장되는 것은 아닙니다. 실제 성공 응답에서 민감정보를 제거한 fixture와 소규모 end-to-end 검증이 추가로 필요합니다. 현재 테스트 범위와 누락된 테스트는 [상세 설계 명세의 테스트 전략](docs/DESIGN.md#21-테스트-전략)을 참고하십시오.

## 후속 개발 시작 순서

```bash
pip install -e '.[dev]'
pytest
jira-collector --help
```

그 다음 아래 문서를 순서대로 읽으십시오.

1. `README.md`
2. [`docs/DESIGN.md`](docs/DESIGN.md)
3. `config/settings.yaml`
4. `src/jira_collector/settings.py`
5. `src/jira_collector/jira_client.py`
6. `src/jira_collector/collector.py`
7. `src/jira_collector/state_store.py`
8. `tests/`

## 현재 MVP 완료 기준

- 접근 가능한 프로젝트 전체 발견
- 프로젝트별 최근 수정 이슈 최대 30개 저장
- 원본 JSON 파일 SHA-256 검증
- 프로젝트별 실패 격리
- 강제 종료 후 checkpoint 재개
- 분당 20회 제한 준수
- 인증정보 미노출
- README와 상세 설계 명세 최신 상태 유지

코드 단위 테스트만 통과한 상태와 실제 Jira 파일럿 완료 상태는 다릅니다. 실제 사내 Jira에서 `check-connection → discover-projects → 소규모 collect → verify` 순서의 검증을 통과해야 실환경 MVP 완료로 판단합니다.
