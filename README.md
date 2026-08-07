# Jira Knowledge Pipeline

Jira REST API에서 원본 데이터를 읽기 전용으로 수집하고, 원본 보존 → 결정적 정규화 → 이슈별 최종 분석 입력 패키지까지 만드는 프로젝트입니다.

현재 파일럿은 **계정이 조회 가능한 프로젝트를 발견하고, 프로젝트별 최근 수정 이슈 최대 30개**를 처리하는 범위로 검증했습니다.

현재 구현은 다음 지점까지 완료되었습니다.

```text
Jira REST API
    ↓
[RAW] 원본 수집
    ↓
Issue / Comment / Structure Parser
    ↓
[ANALYSIS] 정규화 JSONL
    ↓
IssueKnowledgeInputBuilder
    ↓
[KNOWLEDGE INPUT] 이슈별 최종 분석 입력 JSON
    ↓
OpenCode Agent Knowledge Extraction   # 다음 단계
```

중요한 아키텍처 원칙은 **LLM이 개입하기 전에 사실 데이터를 완전하고 재현 가능하게 정리하는 것**입니다.

---

# 1. 현재 구현 상태

```text
1. Jira 연결 / 인증                          완료
2. 접근 가능한 프로젝트 발견                 완료
3. 프로젝트별 최근 이슈 Raw 수집              완료
4. 댓글 전용 API Raw 수집                     완료
5. Raw SHA-256 검증 / resume                  완료
6. Issue Parser / Exporter                    완료 + 실환경 검증
7. Comment Parser / Exporter                  완료 + 실환경 검증
8. Structure Parser / Exporter                완료 + 실환경 검증
   ├─ Attachment metadata
   ├─ Issue Link
   ├─ Parent/Subtask hierarchy
   ├─ Custom Field Catalog
   └─ Custom Field Values
9. Knowledge Input Builder                    완료 + 실환경 검증
10. OpenCode Agent Knowledge Extraction       다음 단계
11. Knowledge 검증                            예정
12. Data Profiling / Excel                    예정
13. DB 논리 스키마 / SQLite                   예정
14. Chunk / BGE-M3 / FAISS                    예정
15. Retriever / MCP                           예정
```

---

# 2. 실환경 파일럿 검증 결과

실제 사내 Jira 데이터의 내용은 저장소에 기록하지 않고 건수와 상태만 기록합니다.

## Issue

```text
대상 30
저장 30
실패 0
경고 0
```

## Comment

```text
대상 이슈 30
댓글 278
저장 278
중복 0
실패 0
경고 0
```

## Structure

```text
Attachment               79 / 실패 0
Canonical Relationship    6 / 실패 0
  ├─ issue_link            2
  └─ hierarchy             4
Custom Field Catalog     220
실제 사용 Field           16
Custom Field Values      447 / 실패 0
정의 불일치                0
경고                       0
```

## Knowledge Input

```text
대상 이슈              30
생성 패키지            30
포함 댓글             278
포함 첨부              79
canonical 관계          6
Custom Field 값       447
패키지 경고             0
manifest status completed
```

사용자 환경 전체 테스트:

```text
pytest 100% PASS
```

---

# 3. 데이터 계층

경로를 사용할 때는 반드시 어느 계층인지 구분합니다.

## [RAW]

```text
data/raw/runs/<run_id>/...
```

Jira API 원본입니다.

역할:

- 사실의 기준
- 재파싱 기준
- 데이터 손실 검증 기준
- Parser는 수정하지 않음

대표 구조:

```text
data/raw/runs/<run_id>/
└─ projects/<project_key>/
   └─ issues/<issue_key>/
      ├─ issue.json
      └─ comments/
         ├─ page_0001.json
         └─ ...
```

RAW에는 원본 HTML, Jira self URL, 사용자 객체 등 ANALYSIS에서 의도적으로 제외한 정보도 존재할 수 있습니다.

---

## [ANALYSIS]

```text
data/analysis/<run_id>/...
```

RAW를 Parser/Exporter가 결정적으로 정규화한 계층입니다.

현재 파일:

```text
issues.jsonl
comments.jsonl
attachments.jsonl
issue_relationships.jsonl
custom_field_catalog.jsonl
custom_field_values.jsonl
parse_warnings.jsonl
summary.json
```

특징:

- Jira API를 다시 호출하지 않음
- LLM을 사용하지 않음
- HTML → 일반 텍스트 변환
- 타입 검증
- 관계 canonicalization
- 불필요한 개인정보 재복제 최소화
- RAW까지 추적 가능한 source_path 유지

---

## [KNOWLEDGE INPUT]

```text
data/knowledge_input/runs/<run_id>/...
```

ANALYSIS의 여러 JSONL을 `issue_key`로 JOIN하여 **OpenCode Agent가 읽을 최종 사실 입력**을 만듭니다.

출력:

```text
data/knowledge_input/runs/<run_id>/
├─ issues/
│  ├─ ABC-123.json
│  ├─ ABC-124.json
│  └─ ...
├─ package_warnings.jsonl
└─ manifest.json
```

이 계층도 LLM을 사용하지 않습니다.

아직 다음 값을 만들지 않습니다.

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

위 값은 다음 OpenCode Agent Knowledge Extraction 단계에서 생성합니다.

---

## [KNOWLEDGE] — 다음 단계

향후 예:

```text
data/knowledge/...
```

OpenCode Agent가 KNOWLEDGE INPUT을 읽고 업무 의미를 구조화한 파생 지식입니다.

후보 항목:

```text
problem_or_goal
context
observations
hypotheses
confirmed_causes
actions_taken
plans
decisions
results
conclusion
open_questions
blockers
evidence_refs
```

이 값들은 사실 원본 자체가 아니라 Agent 해석이므로 반드시 evidence와 연결합니다.

---

# 4. 프로젝트 문서

전체 흐름을 이해하려면 다음 순서로 읽는 것을 권장합니다.

1. **[전체 Pipeline 아키텍처](docs/PIPELINE_OVERVIEW.md)**
2. **[Collector 상세 설계](docs/DESIGN.md)**
3. **[댓글 Raw 수집 계약](docs/COMMENT_COLLECTION.md)**
4. **[Parser Core](docs/PARSER_CORE.md)**
5. **[Issue Export 명세](docs/ISSUE_EXPORT_SPEC.md)**
6. **[Comment Export 명세](docs/COMMENT_EXPORT_SPEC.md)**
7. **[Structure Export 명세](docs/STRUCTURE_EXPORT_SPEC.md)**
8. **[실제 Jira Structure Profile](docs/JIRA_STRUCTURE_PROFILE.md)**
9. **[Summary / Warning 공통 계약](docs/RUN_SUMMARY_SPEC.md)**
10. **[Knowledge Input 상세 명세](docs/KNOWLEDGE_INPUT_SPEC.md)**
11. **[Knowledge Input 코드 읽기 가이드](docs/KNOWLEDGE_INPUT_CODE_GUIDE.md)**
12. **[Knowledge Input 실환경 검증 기록](docs/KNOWLEDGE_INPUT_VALIDATION.md)**

코드 또는 저장 계약을 변경하면 README와 관련 명세 및 테스트를 같은 변경 단위에서 갱신합니다.

---

# 5. 요구 환경

- Python 3.11 이상
- Jira Server/Data Center 또는 호환 REST API
- Windows PowerShell, Linux shell 또는 macOS shell

---

# 6. 설치

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

개발 의존성 포함 설치:

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

브랜치를 바꾸거나 코드를 갱신한 뒤에는 editable install을 다시 실행하는 것이 안전합니다.

---

# 7. Jira 설정

`.env.example`을 `.env`로 복사합니다.

```powershell
Copy-Item .env.example .env
```

예:

```dotenv
JIRA_BASE_URL=https://jira.example.com
JIRA_USERNAME=my-user-id
JIRA_PASSWORD=my-password
```

주요 YAML 설정 예:

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

현재 Attachment 바이너리는 다운로드하지 않습니다.
`issue.json`에 존재하는 Attachment metadata만 정규화합니다.

---

# 8. CLI 명령

```text
jira-collector check-connection
jira-collector discover-projects
jira-collector collect
jira-collector resume --run-id <RUN_ID>
jira-collector verify --run-id <RUN_ID>
jira-collector export-issues --run-id <RUN_ID>
jira-collector export-comments --run-id <RUN_ID>
jira-collector export-structure --run-id <RUN_ID>
jira-collector build-knowledge-input --run-id <RUN_ID>
```

Windows에서 오래된 console script가 잡힐 수 있으므로 검증할 때는 다음 실행 방식을 권장합니다.

```powershell
python -m jira_collector.cli --help
```

---

# 9. Collector 실행

## 연결 확인

```powershell
python -m jira_collector.cli check-connection
```

## 프로젝트 발견

```powershell
python -m jira_collector.cli discover-projects
```

## 파일럿 수집

```powershell
python -m jira_collector.cli collect
```

특정 프로젝트:

```powershell
python -m jira_collector.cli collect --project ABC
```

중단 후 재개:

```powershell
python -m jira_collector.cli resume --run-id <RUN_ID>
```

Raw 무결성 검증:

```powershell
python -m jira_collector.cli verify --run-id <RUN_ID>
```

---

# 10. Issue Exporter

실행:

```powershell
python -m jira_collector.cli export-issues --run-id <RUN_ID>
```

입력:

```text
[RAW]
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

출력:

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

Description HTML 원문은 RAW에 남고 ANALYSIS에는 정제 텍스트가 저장됩니다.

---

# 11. Comment Exporter

실행:

```powershell
python -m jira_collector.cli export-comments --run-id <RUN_ID>
```

입력:

```text
[RAW]
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/comments/page_*.json
```

출력:

```text
[ANALYSIS]
data/analysis/<run_id>/comments.jsonl
```

핵심 처리:

```text
page_*.json 파일명 순서 병합
comment.id 중복 제거
sequence 부여
HTML body → text
작성자 displayName/name/key 정규화
```

이메일, avatar URL, Jira self URL은 일반 ANALYSIS JSONL에 불필요하게 복제하지 않습니다.

---

# 12. Structure Exporter

실행:

```powershell
python -m jira_collector.cli export-structure --run-id <RUN_ID>
```

입력:

```text
[RAW]
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

`IssueStructureParser`는 같은 `issue.json`을 한 번 읽고 모든 구조를 함께 추출합니다.

```text
issue.json
   ↓
Attachment metadata
Issue Link
Parent/Subtask hierarchy
Custom Field definitions
Custom Field values
```

출력:

```text
[ANALYSIS]
data/analysis/<run_id>/
├─ attachments.jsonl
├─ issue_relationships.jsonl
├─ custom_field_catalog.jsonl
└─ custom_field_values.jsonl
```

## Relationship

canonical edge를 사용합니다.

```text
Issue Link : Jira type.outward 방향
Hierarchy  : parent --parent_of--> child
```

동일 Jira Link가 양쪽 issue.json에서 관찰돼도 하나의 canonical edge만 저장합니다.

## Custom Field

두 파일로 분리합니다.

```text
custom_field_catalog.jsonl
→ 전체 Field 정의

custom_field_values.jsonl
→ 실제 non-null 값
```

Multi User Picker의 emailAddress 등 불필요한 개인정보는 ANALYSIS에 복제하지 않습니다.

---

# 13. Summary와 Warning

## ANALYSIS Summary

```text
[ANALYSIS]
data/analysis/<run_id>/summary.json
```

지원 영역:

```text
issues
comments
attachments
relationships
custom_fields
```

Knowledge Input Builder는 이 다섯 영역이 모두 `completed`인지 확인합니다.

불완전한 ANALYSIS를 최종 Agent 입력으로 넘기지 않습니다.

## ANALYSIS Warning

```text
data/analysis/<run_id>/parse_warnings.jsonl
```

지원 component:

```text
issues
comments
attachments
relationships
custom_fields
structure
```

---

# 14. Knowledge Input Builder

실행:

```powershell
python -m jira_collector.cli build-knowledge-input --run-id <RUN_ID>
```

입력은 **ANALYSIS만 사용합니다. RAW를 다시 읽지 않습니다.**

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

출력:

```text
[KNOWLEDGE INPUT]
data/knowledge_input/runs/<run_id>/
├─ issues/
│  ├─ <ISSUE_KEY>.json
│  └─ ...
├─ package_warnings.jsonl
└─ manifest.json
```

한 패키지의 개념 구조:

```text
Issue
├─ issue
├─ comments[]
├─ attachments[]
├─ relationships[]
├─ custom_fields[]
├─ counts
└─ source_hash
```

---

# 15. Relationship의 Package 관점

ANALYSIS는 canonical edge를 저장합니다.

예:

```text
A --blocks--> B
```

A package:

```text
current_issue_role=source
current_issue_direction=outgoing
other_issue_key=B
```

B package:

```text
current_issue_role=target
current_issue_direction=incoming
other_issue_key=A
```

연결 이슈가 현재 파일럿에 없으면 관계를 버리지 않고:

```text
other_package_available=false
```

로 표시합니다.

---

# 16. Attachment Package 정책

현재 파일 본문은 수집하지 않았습니다.

따라서 Knowledge Input에서:

```text
content_available=false
```

를 명시합니다.

Agent는 filename과 metadata의 존재는 알 수 있지만 파일 내용을 읽었다고 가정하면 안 됩니다.

---

# 17. source_hash

각 Issue package는 의미 데이터 기반 SHA-256을 가집니다.

Hash 대상:

```text
issue
comments
attachments
relationships
custom_fields
```

제외:

```text
generated_at
source_path
source_page
PC 설치 경로
```

향후:

```text
old hash == new hash
→ OpenCode 재분석 생략

old hash != new hash
→ Knowledge 재추출
```

증분 Knowledge Extraction의 핵심 기준입니다.

---

# 18. Knowledge Input 완료 표식

```text
[KNOWLEDGE INPUT]
manifest.json
```

빌드 시작 시 기존 manifest를 제거하고 모든 package와 warning 저장이 끝난 뒤 마지막에 새 manifest를 원자 저장합니다.

따라서 중간 실패 상태를 completed로 오해하지 않습니다.

실환경 검증에서는:

```text
manifest.status = completed
```

을 확인했습니다.

---

# 19. Knowledge Input Warning

```text
[KNOWLEDGE INPUT]
package_warnings.jsonl
```

ANALYSIS Parser warning과 역할이 다릅니다.

ANALYSIS Warning:

```text
RAW → ANALYSIS 문제
```

Knowledge Input Warning:

```text
ANALYSIS → Issue Package JOIN 정합성 문제
```

예:

```text
missing_issue_key
orphan_analysis_record
invalid_relationship_endpoint
relationship_outside_package_scope
custom_field_definition_missing
```

---

# 20. 재실행 의미

Knowledge Input은 append log가 아니라 현재 ANALYSIS snapshot의 파생 결과입니다.

같은 run_id 재실행 시:

```text
기존 package 원자 교체
더 이상 존재하지 않는 stale package 삭제
package_warnings.jsonl 전체 재생성
manifest.json 마지막 재생성
```

---

# 21. 테스트

전체 테스트:

```powershell
pytest
```

Knowledge Input 집중 테스트:

```powershell
pytest tests/knowledge_input tests/test_cli_export.py
```

현재 사용자 환경에서 전체 pytest 100% PASS를 확인했습니다.

---

# 22. 보안 원칙

- 실제 Jira Raw/Analysis/Knowledge Input 데이터를 Git에 올리지 않음
- 인증정보를 코드·문서·fixture에 넣지 않음
- 실제 Jira 제목·본문·댓글 내용을 로그로 남기지 않음
- RAW에서 ANALYSIS로 넘어갈 때 개인정보 불필요 복제를 최소화
- Knowledge Input은 RAW를 다시 읽지 않아 제거된 개인정보를 되살리지 않음
- 테스트는 가짜 JSON만 사용

---

# 23. 현재 안정 경계

현재까지는 모두 결정적 파이프라인입니다.

```text
RAW
→ ANALYSIS
→ KNOWLEDGE INPUT
```

여기까지 문제가 있으면 코드/데이터 JOIN 문제입니다.

다음 단계부터 LLM이 개입합니다.

```text
KNOWLEDGE INPUT
→ OpenCode Agent
→ KNOWLEDGE
```

따라서 Knowledge Input이 정상인데 Knowledge 결과가 틀리면 Prompt/Agent 해석 문제로 분리할 수 있습니다.

---

# 24. 다음 단계: OpenCode Knowledge Extraction

다음 단계에서는 KNOWLEDGE INPUT을 OpenCode Agent가 읽고 업무 의미를 구조화합니다.

후보 schema:

```text
issue_summary
problem_or_goal
context
observations
hypotheses
confirmed_causes
actions_taken
plans
decisions
results
conclusion
open_questions
blockers
evidence_refs
```

처음부터 전체 30건을 자동 처리하기보다 대표 이슈 5건으로 schema와 prompt를 검증한 뒤 전체에 적용하는 것을 권장합니다.

가장 중요한 원칙:

```text
추측과 확정 사실 분리
계획과 완료 작업 분리
근거 없는 값 생성 금지
모든 주요 지식 항목에 evidence 연결
원문과 모순되면 추출 실패 또는 미확정 처리
```

---

# 25. 향후 로드맵

```text
Knowledge Extraction Schema / Prompt
→ 대표 이슈 파일럿
→ 사람 검증
→ 전체 Knowledge 생성
→ Data Profiling / Excel
→ DB 논리 스키마
→ SQLite Loader
→ Raw/Knowledge Chunk
→ BGE-M3 Embedding
→ FAISS
→ Retriever
→ MCP
```
