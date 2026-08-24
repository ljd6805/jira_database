# M0 Jira Collection / Analysis Completion Record

복원 기준일: 2026-08-24  
구현 시기: 2026-08-03 ~ 2026-08-07  
단계: **M0 · Jira 사실 수집·정규화**

이 문서는 M0 완료 이후 뒤늦게 작성한 회고성 요약이 아니라, 저장소의 실제 commit history, 현재 구현 코드, 상세 설계 문서, 실환경 검증 기록을 대조해 **M0 완료 시점의 결정과 구현 계약을 복원한 Completion Record**다.

> 문서 보존 원칙: 당시의 결정이 이후 구현으로 명백히 폐기된 것이 아니라면 삭제하지 않는다. 이후 단계에서 강화된 규칙은 원래 M0 결정과 구분해 기록한다.

---

## 1. M0 목적

M0의 목적은 Jira 데이터를 곧바로 LLM/RAG에 넣는 것이 아니었다.

먼저 다음 경계를 결정적으로 완성하는 것이 목표였다.

```text
Jira REST API
    ↓
읽기 전용 Collector
    ↓
[RAW] 원본 JSON snapshot
    ↓
Parser / Exporter
    ↓
[ANALYSIS] 정규화 JSONL
```

핵심 성공 조건은 다음과 같았다.

1. 인증 계정이 조회 가능한 프로젝트를 발견한다.
2. 파일럿에서는 프로젝트별 최근 수정 이슈를 최대 30개 수집한다.
3. Issue와 전체 Comment를 Raw로 보존한다.
4. 중단·부분 실패 후에도 수집을 재개할 수 있다.
5. Raw를 수정하지 않고 Issue / Comment / Structure를 결정적으로 정규화한다.
6. Attachment metadata, Relationship, Hierarchy, Custom Field를 ANALYSIS로 만든다.
7. 실제 Jira 파일럿에서 실패·경고 없이 다음 단계의 사실 입력 기반을 만든다.

M0에서는 생성형 LLM, 임베딩, FAISS, RAG, MCP를 구현하지 않았다.

---

## 2. M0의 가장 중요한 아키텍처 결정

### 2.1 Raw First

가장 먼저 확정된 원칙은 **Jira 원본 snapshot을 먼저 보존하고, 파싱·검색·LLM은 그 이후 계층에서 수행한다**는 것이다.

```text
[RAW]
= 사실의 기준

[ANALYSIS]
= RAW에서 결정적으로 파생한 검색/분석 친화적 사실 데이터
```

이 결정 때문에 이후 Parser가 잘못되더라도 Jira API를 다시 호출하지 않고 Raw에서 재처리할 수 있게 됐다.

### 2.2 Collector와 Parser 분리

Collector는 외부 Jira와 통신하고 원본을 저장한다.
Parser/Exporter는 Jira에 다시 접근하지 않고 로컬 Raw만 읽는다.

```text
Collector 책임
- API 호출
- pagination
- rate limit / retry
- Raw snapshot
- checkpoint / resume

Parser 책임
- HTML → text
- 타입 검증
- 구조 정규화
- canonical relationship
- JSONL export
- warning / summary
```

이 분리는 이후 M1의 Knowledge Input Builder가 Jira API가 아니라 ANALYSIS만 읽게 만든 기반이 됐다.

### 2.3 속도보다 안전성

파일럿의 품질 우선순위는 다음과 같이 정해졌다.

```text
1. Jira에 쓰기 요청을 보내지 않는다.
2. 인증정보를 유출하지 않는다.
3. 저장 파일을 중간 상태로 남기지 않는다.
4. 일부 실패가 전체 결과를 없애지 않는다.
5. 중단 후 재개 가능해야 한다.
6. 호출 제한을 지킨다.
7. 마지막이 속도다.
```

따라서 병렬 수집으로 처리량을 끌어올리는 대신 단일 요청 흐름과 보수적 rate limit을 선택했다.

---

## 3. Commit 기반 구현 연혁

### 3.1 설정과 실행 경계

초기 commit에서 운영값과 비밀정보를 분리했다.

| Commit | 결정 / 구현 |
|---|---|
| `32a3506` · `feat: add environment template` | Jira URL / 사용자명 / 비밀번호를 로컬 환경값으로 받는 틀 추가 |
| `9c4f96a` · `feat: add collector configuration` | API 경로, pagination, 30건 파일럿, 20 req/min, timeout/retry, 저장 경로를 YAML로 정의 |
| `48b7e61` · `feat: add validated layered settings` | 환경변수 + YAML을 타입 검증된 설정 객체로 캡슐화 |
| `4e04d99` / `ba6f9fe` | Python package와 module entrypoint 구성 |

초기 `settings.yaml`에서 이미 다음 값이 명시됐다.

```yaml
collection:
  project_scope: all_accessible
  issues_per_project: 30
  issue_order: updated_desc
  collect_comments: true
  download_attachments: false

rate_limit:
  requests_per_minute: 20
  max_concurrency: 1
```

즉 **모든 접근 가능 프로젝트 + 프로젝트별 30개 + 댓글 포함 + 첨부 바이너리 미수집**은 뒤에 우연히 생긴 동작이 아니라 초기 설계값이었다.

### 3.2 Rate limiter

`c3e438c · feat: add 20-per-minute rate limiter`

20 requests/minute를 단순 문구로만 두지 않고 요청 시작 시각 사이의 최소 간격으로 구현했다.

```text
interval = 60 / 20 = 3 seconds
concurrency = 1
```

재시도도 limiter를 우회하지 않는다.

이 값은 파일럿 처리량 극대화가 아니라 공유 Jira 서버에 부담을 주지 않기 위한 보수적 상한이다.

### 3.3 Atomic Raw Store

`c2c6f36 · feat: add atomic raw JSON store`

RawStore에서 다음을 구현했다.

- path component sanitization
- Raw root 밖으로의 path traversal 차단
- UTF-8 JSON 저장
- 임시 파일 작성
- `flush` + `fsync`
- `os.replace` 원자 교체
- SHA-256 계산
- 상대 경로 / 파일 크기 반환
- 저장 후 hash 검증

핵심 저장 순서:

```text
payload
→ JSON serialize
→ SHA-256
→ same-directory temp file
→ flush + fsync
→ os.replace
→ completed artifact
```

이 결정은 프로세스가 중간에 죽어도 정상 파일 경로에 반쪽짜리 JSON이 남을 가능성을 줄였다.

Windows 실환경에서는 `os.replace`가 일시적으로 `WinError 5/32/33`을 일으킬 수 있어 `74e83c7 · fix: retry Windows atomic file replacement`로 제한된 재시도를 추가했다.

### 3.4 Project Discovery

`eccfad4 · feat: add accessible project discovery`

프로젝트 목록은 특정 key를 하드코딩하지 않고 인증 계정이 볼 수 있는 범위를 API에서 발견하도록 구현했다.

지원 응답 형태:

```text
1. 최상위 array
2. values[]를 가진 page object
3. projects[]를 가진 object
```

발견 과정에서도 응답 page를 Raw artifact로 저장하고, project key 중복 제거 후 정렬된 목록을 사용한다.

### 3.5 Secure Jira REST Client

`3f594a6 · feat: add secure Jira REST client`

JiraClient는 다음 계약으로 시작했다.

- `requests.Session`
- HTTP Basic 인증
- GET only
- 공통 `Accept: application/json`
- connect/read timeout
- 모든 요청에 rate limiter 적용
- 401 / 403 / 404를 별도 오류로 분류
- 429는 `Retry-After`를 고려
- 5xx / 연결 오류는 제한된 backoff retry
- 예상하지 못한 status와 non-JSON 응답은 명시적 실패

비밀번호, Authorization, Cookie, 전체 response body는 일반 로그에 기록하지 않는 원칙을 함께 유지했다.

### 3.6 사내 TLS 문제와 설정화

실환경에서 사내 인증서 때문에 SSL 검증 오류가 발생했고 다음 commit 흐름이 남아 있다.

```text
8546e63  fix: disable Jira SSL certificate verification
137494f  feat: add configurable Jira TLS verification
11ebbe6  fix: apply disabled SSL verification to Jira requests
```

중요한 최종 결정은 **무조건 SSL 검증을 끄는 것**이 아니다.

`jira.tls.verify_ssl`을 설정값으로 만들었고, 코드 기본값은 `true`로 두되 사내 환경에서 필요한 경우 명시적으로 `false`를 선택할 수 있게 했다.

즉 실환경 우회책을 하드코딩하지 않고 환경별 설정으로 승격했다.

### 3.7 SQLite Checkpoint / Resume

`b03474e · feat: add SQLite checkpoint state store`

M0의 SQLite는 업무지식 DB가 아니라 **Collector 실행 상태 DB**다.

핵심 테이블:

```text
collection_runs
project_runs
artifacts
issue_checkpoints
```

주요 상태:

```text
run       : running / completed / partial
project   : pending / running / completed / failed / partial
issue     : running / completed / failed
```

Project 실패는 수집된 이슈가 있으면 `partial`, 전혀 없으면 `failed`로 구분했다.

Resume은 기존 `run_id`에서 미완료 프로젝트와 이슈 checkpoint를 읽어 이미 완료한 이슈를 건너뛴다.

### 3.8 Project / Issue Collection

`8c5a631 · feat: implement project and issue collection`

Collector는 다음 순서로 구현됐다.

```text
new run 생성
→ Project Discovery
→ project_runs 등록
→ 프로젝트별 순차 처리
   → JQL search: project = "KEY" ORDER BY updated DESC
   → 최대 N개 issue stub 확보
   → issue detail 수집
   → comment 수집
   → issue checkpoint 완료
→ project 완료/부분실패 기록
→ 전체 run 완료 상태 계산
```

프로젝트 하나의 오류는 `_collect_project_list()` 경계에서 잡아 다음 프로젝트 수집을 계속한다.

이슈 하나가 실패하면 해당 checkpoint를 실패로 기록하고 프로젝트는 부분 실패 상태를 가질 수 있다.

### 3.9 Comment 수집 계약 수정

초기 구현은 issue detail 응답에 embed된 comment 개수를 보고 부족한 페이지만 보충하려 했다.

실환경 검토 후 `2077557 · fix: always fetch complete Jira comments`에서 정책을 바꿨다.

이유:

- Jira 버전/설정에 따라 issue detail에 댓글이 모두, 일부, 또는 전혀 들어오지 않을 수 있음
- embed 상태에 의존하면 Raw 저장 계약이 환경마다 달라짐

최종 계약:

```text
댓글은 dedicated comment endpoint를 사용
startAt = 0부터 항상 시작
마지막 page까지 전체 저장
댓글 0건이어도 빈 page_0001.json 저장
pagination이 전진하지 않으면 오류
```

이 변경으로 `issue.json`의 embed comment 상태와 무관하게 댓글 Raw 구조가 일관되게 됐다.

### 3.10 CLI

`73a0abd · feat: add collector CLI`

M0에서 확립된 주요 실행 명령:

```text
check-connection
discover-projects
collect
resume --run-id <RUN_ID>
verify --run-id <RUN_ID>
```

이후 Parser/Exporter가 추가되면서:

```text
export-issues
export-comments
export-structure
```

가 같은 CLI에 편입됐다.

---

## 4. RAW 저장 계약

대표 구조:

```text
data/raw/runs/<run_id>/
└─ projects/<project_key>/
   ├─ project.json
   ├─ issue_search/
   │  └─ page_0001.json
   └─ issues/<issue_key>/
      ├─ issue.json
      └─ comments/
         ├─ page_0001.json
         └─ ...
```

Raw의 정의는 HTTP wire byte 그대로가 아니라, Jira JSON 응답을 Python object로 파싱한 뒤 UTF-8 pretty JSON으로 재직렬화한 snapshot이다.

Raw에는 이후 ANALYSIS에서 의도적으로 제거될 수 있는 다음 값도 존재한다.

```text
HTML 원문
Jira self URL
emailAddress
avatarUrls
plugin 전용 복합 객체
```

따라서 Raw 접근 권한은 보호 대상이다.

---

## 5. ANALYSIS Parser / Exporter 구현

Collector 검증 후 M0는 단순 수집 단계에서 끝내지 않고 **결정적 ANALYSIS 계층**까지 확장됐다.

### 5.1 Issue Parser

대표 commit 흐름:

```text
f69d79a  feat: add Jira parser core models
94f66e2  feat: add Jira HTML text normalization
01e2d24  feat: discover collected Jira issue artifacts
0110955  feat: parse core Jira issue fields
6b6258c  feat: export parsed issues to JSONL
2426581  feat: add export-issues CLI command
```

출력:

```text
data/analysis/<run_id>/issues.jsonl
```

핵심 필드:

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

HTML description 원문은 Raw에 남기고 ANALYSIS에는 정제 text를 저장한다.

### 5.2 Comment Parser

대표 commit 흐름:

```text
32a910d  feat: add Jira comment parser
9abb927  feat: add Jira author key helper
cb69cf0  feat: extend parser models for comments
0e8d372  feat: add Jira comment JSONL exporter
85af1f1  feat: add export-comments CLI command
```

핵심 규칙:

- `page_*.json` 파일명 순으로 병합
- `comment.id` 중복 제거
- deterministic `sequence` 부여
- HTML body → text
- author는 `displayName → name → key` 순으로 정규화
- email / avatar / Jira self URL은 일반 ANALYSIS에 불필요하게 복제하지 않음

출력:

```text
data/analysis/<run_id>/comments.jsonl
```

### 5.3 공통 Summary / Warning

```text
1a3ad59  feat: add shared run summary store
490228a  feat: add shared warning JSONL store
```

공통 결과:

```text
summary.json
parse_warnings.jsonl
```

Parser별 파일을 제각각 두지 않고 run 전체의 완료 상태와 warning을 같은 계약으로 합치도록 했다.

### 5.4 Structure Parser

PR #1의 후반부에서 다음 구조를 한 번에 추가했다.

```text
58fb8ad  feat: add issue structure parser
725a544  feat: add structure parser models
f55adf5  feat: add structure JSONL exporter
cb6d336  feat: extend run summary for structure export
ca6f8e9  feat: atomically replace multiple warning components
1bc37df  feat: add export-structure CLI command
```

같은 `issue.json`을 Attachment / Relationship / Custom Field 때문에 반복해서 읽지 않고 한 번의 `IssueStructureParser`에서 함께 추출한다.

출력:

```text
attachments.jsonl
issue_relationships.jsonl
custom_field_catalog.jsonl
custom_field_values.jsonl
```

---

## 6. Structure별 핵심 결정

### 6.1 Attachment

첫 버전은 파일 바이너리를 다운로드하지 않는다.

저장하는 것은 metadata다.

```text
attachment_id
filename
author_name / author_key
created_at
size_bytes
mime_type
content_url / thumbnail_url
source_path
```

### 6.2 Issue Link canonicalization

Jira link는 양쪽 Issue JSON에서 중복 관찰될 수 있다.

그래프 저장은 Jira `type.outward` 의미를 기준으로 하나의 canonical edge로 정규화한다.

```text
A outward blocks B
B에서 inward A 관찰
→ 둘 다 A --blocks--> B 한 edge
```

동일 `relationship_id`는 한 번만 저장한다.

### 6.3 Parent / Subtask

Hierarchy는 항상:

```text
parent --parent_of--> child
```

형태로 정규화한다.

`fields.parent`와 `fields.subtasks`에서 같은 관계가 중복 관찰돼도 canonical key로 하나만 남긴다.

### 6.4 Custom Field

정의와 값을 분리했다.

```text
custom_field_catalog.jsonl
→ field 정의 1회

custom_field_values.jsonl
→ Issue별 non-null 실제 값
```

Plugin field는 `schema.type=any`일 수 있어 schema만 보고 실제 타입을 단정하지 않는다.

따라서:

```text
schema_type
actual_type
value_kind
```

을 분리한다.

Multi User Picker 등 사용자 객체는 전체를 ANALYSIS에 복제하지 않고 `display_values`, `user_keys`, `value_shape`처럼 필요한 파생 값만 유지한다.

---

## 7. M0 보안 경계

M0에서 고정된 보안 원칙:

- 실제 Jira URL/ID/Password는 코드에 하드코딩하지 않음
- `.env` / Secret으로 인증정보 분리
- 실제 Raw/Analysis는 Git에서 제외
- Jira write method 미구현
- Authorization / Cookie / Password 비로그
- 전체 Jira 원문을 일반 로그에 출력하지 않음
- ANALYSIS에서 불필요한 사용자 개인정보 재복제 최소화
- 테스트 fixture는 실제 Jira 업무 데이터가 아닌 가짜 JSON 사용

---

## 8. 실환경 검증 결과

PR #1 merge 시점에 실제 사내 Jira 파일럿에서 확인된 결과:

```text
Issue
  대상 30
  저장 30
  실패 0
  경고 0

Comment
  대상 Issue 30
  Comment 278
  저장 278
  중복 0
  실패 0
  경고 0

Structure
  Attachment metadata        79 / 실패 0
  Canonical Relationship      6 / 실패 0
    issue_link                2
    hierarchy                 4
  Custom Field Catalog      220
  실제 사용 Field             16
  Custom Field Values       447 / 실패 0
  정의 불일치                  0
  경고                         0
```

사용자 환경 전체 테스트:

```text
pytest 100% PASS
```

PR #1 `feat: integrate Jira parser and structure analysis pipeline`이 M0의 Collector → RAW → ANALYSIS 경계를 통합 완료했다.

---

## 9. M0에서 하지 않은 것

다음은 의도적으로 M0 밖에 뒀다.

```text
Knowledge 의미 추출
LLM 요약
원인/가설/결정/결과 생성
첨부파일 본문 분석
업무지식 SQLite schema
Chunk
Embedding
FAISS
Retriever
MCP
```

M0의 성공 기준은 “지식을 잘 추론하는가”가 아니라 **LLM이 개입하기 전 사실 데이터가 완전하고 재현 가능한가**였다.

---

## 10. M0 Gate 판정

- [x] 읽기 전용 Jira Client
- [x] 계정이 접근 가능한 프로젝트 발견
- [x] 프로젝트별 최근 수정 이슈 최대 30개 수집
- [x] Jira 호출 상한 20 req/min / concurrency 1
- [x] Atomic Raw + SHA-256
- [x] SQLite checkpoint / resume
- [x] 프로젝트 부분 실패 격리
- [x] dedicated comment endpoint 전체 pagination
- [x] Issue / Comment ANALYSIS JSONL
- [x] Attachment / Relationship / Hierarchy / Custom Field ANALYSIS
- [x] Summary / Warning 공통 계약
- [x] 실제 30건 파일럿 실패·경고 0
- [x] pytest 100% PASS 확인

## **M0 Gate: PASS / DONE**

다음 단계는 **M1 · Issue 단위 Knowledge Input 계약**이다.

---

## 11. M0가 M1 이후에 남긴 설계 제약

1. `[RAW]`는 사실의 기준이며 후속 단계가 수정하지 않는다.
2. `[ANALYSIS]`는 Jira API를 다시 호출하지 않는 deterministic 계층이다.
3. 후속 LLM 단계는 Raw Jira object를 직접 다루기보다 정규화된 사실 계약을 사용한다.
4. Comment ID / Attachment ID / Relationship ID / Custom Field ID / source_path를 잃지 않는다.
5. 관계는 canonical edge로 유지한다.
6. 개인정보 최소화는 ANALYSIS에서 시작한다.
7. 부분 완료 데이터를 정상 완료처럼 다음 단계에 넘기지 않도록 summary/warning 상태를 사용한다.

---

## 12. 주요 근거 Commit / 문서

### Collector

- [`9c4f96a` collector configuration](https://github.com/ljd6805/jira_database/commit/9c4f96ae6e601a953f100d17f00d3cd396639906)
- [`c2c6f36` atomic raw store](https://github.com/ljd6805/jira_database/commit/c2c6f369b76dac4fb1985bd63f554d6c0181e273)
- [`3f594a6` secure Jira REST client](https://github.com/ljd6805/jira_database/commit/3f594a609227c113959bbe7f9744ca339390caca)
- [`b03474e` SQLite checkpoint](https://github.com/ljd6805/jira_database/commit/b03474eda936e1268c8bfe1a1a7fc3d0d6933a11)
- [`8c5a631` project / issue collection](https://github.com/ljd6805/jira_database/commit/8c5a631b392f6915c429c75376580853936eebf3)
- [`2077557` complete comment collection](https://github.com/ljd6805/jira_database/commit/207755749508dac691fcdfb1afb94907d8b68ed6)
- [`137494f` configurable TLS verification](https://github.com/ljd6805/jira_database/commit/137494f4129ad152b98cb5e51db44a7dbbc3c5a3)

### Parser / Structure

- [PR #1 · Jira parser and structure analysis pipeline](https://github.com/ljd6805/jira_database/pull/1)
- `docs/DESIGN.md`
- `docs/PIPELINE_OVERVIEW.md`
- `docs/PARSER_CORE.md`
- `docs/ISSUE_EXPORT_SPEC.md`
- `docs/COMMENT_EXPORT_SPEC.md`
- `docs/STRUCTURE_EXPORT_SPEC.md`
- `docs/JIRA_STRUCTURE_PROFILE.md`
- `docs/RUN_SUMMARY_SPEC.md`
