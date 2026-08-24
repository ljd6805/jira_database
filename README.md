# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Issue 단위 사실 패키지 → Knowledge 추출/검토 → Profiling → DB 논리 모델 → Vector Retrieval → MCP**로 발전시키는 프로젝트입니다.

현재 기준은 **M0~M5 완료, M6 DB Logical Schema 진행 중**입니다.

```text
Jira REST API
    ↓
M0  [RAW] → [ANALYSIS]                       DONE
    ↓
M1  [KNOWLEDGE INPUT]                        DONE
    ↓
M2  Knowledge Schema v0.1 + Skill v0.9       DONE
    ↓
M3  Worker → Validator → Reviewer Loop       DONE
    ↓
M4  [KNOWLEDGE] + [REVIEW] 실제 Jira Pilot  DONE
    ↓
M5  Knowledge / Review Profiling             DONE
    ↓
M6  DB Logical Schema                        CURRENT
    ↓
M7  SQLite Materialization                   NEXT
    ↓
M8  Chunk + BGE-M3
    ↓
M9  FAISS + Retrieval
    ↓
M10 Evidence Builder + MCP                   Functional MVP Gate
```

핵심 원칙은 세 가지입니다.

1. **RAW가 사실의 최종 기준**입니다.
2. **결정적 처리와 LLM 해석을 분리**합니다.
3. **Knowledge는 검색용 의미 압축이며 Evidence로 원문까지 round-trip**할 수 있어야 합니다.

---

## 1. 현재 상태

| Milestone | 상태 | 핵심 결과 |
|---|---|---|
| M0 | DONE | Jira 수집, RAW 보존, Issue/Comment/Structure ANALYSIS |
| M1 | DONE | Issue별 Knowledge Input 30 package |
| M2 | DONE | Knowledge Schema v0.1, Extraction Skill v0.9 |
| M3 | DONE | Orchestrator → Fresh Worker → Validator → Fresh Reviewer |
| M4 | DONE | 실제 Jira 30/30 최종 PASS, Human Validation 5/5 |
| M5 | DONE | Knowledge 285 items, Evidence 503 refs, Review 37 files |
| M6 | **CURRENT** | Entity, ID, Version, Evidence round-trip Logical Schema |
| M7 | NEXT | SQLite DDL, Loader, Integrity Test |

전체 M0~M16 로드맵과 완료 Gate는 [현재 상태와 향후 계획](docs/status/jira_knowledge_db_current_status.html)을 기준으로 합니다.

---

## 2. 실제 파일럿 검증 결과

실제 Jira 업무 내용은 저장소에 기록하지 않고 aggregate 값만 남깁니다.

### M0 / M1 Source Pipeline

```text
Issue                         30
Comment                      278
Attachment metadata           79
Canonical Relationship         6
  ├─ issue_link                2
  └─ hierarchy                 4
Custom Field Catalog         220
실제 사용 Field               16
Custom Field Values          447

Knowledge Input package       30
package warning                0
manifest.status        completed
```

사용자 환경에서 전체 `pytest` 100% PASS를 확인했습니다.

### M4 Knowledge Extraction

```text
대상 Issue                    30
1차 PASS                      24
2차 PASS                       5
3차 PASS                       1
재생성 Issue                   6
INPUT_ERROR                    0
REVIEW_REQUIRED                0
INCOMPLETE                     0
Human Validation             5/5
```

최종 Run 집계는 LLM 계산이 아니라 `summarize_knowledge_run.py`의 deterministic 결과를 기준으로 합니다.

### M5 Profiling

```text
Knowledge Item               285
Issue당 item mean            9.5
Issue당 item p95            16.1
Statement p95              206.4 chars
Evidence Ref                 503
Evidence / item mean        1.76
Comment Evidence           79.92%
Review JSON                   37
Final PASS                 30/30
```

이 실제 분포가 M6 Logical Schema의 설계 근거입니다.

---

## 3. 데이터 계층

### [RAW]

```text
data/raw/runs/<run_id>/...
```

Jira API 응답을 보존하는 사실 기준 계층입니다.

- Parser가 수정하지 않음
- 원자 저장
- SHA-256 무결성 확인
- 재파싱/재검증 기준
- Jira 원본 HTML 및 ANALYSIS에서 제거한 값이 남을 수 있음

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

### [ANALYSIS]

```text
data/analysis/<run_id>/...
```

RAW를 생성형 LLM 없이 결정적으로 정규화합니다.

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

핵심 처리:

- HTML → 일반 텍스트
- 타입 검증
- Comment sequence 정규화
- Relationship canonicalization
- Custom Field Catalog / Values 분리
- 불필요한 개인정보 재복제 최소화
- RAW까지 추적 가능한 `source_path` 유지

### [KNOWLEDGE INPUT]

```text
data/knowledge_input/runs/<run_id>/
├─ issues/<ISSUE_KEY>.json
├─ package_warnings.jsonl
└─ manifest.json
```

ANALYSIS를 `issue_key`로 JOIN한 **Issue 단위 최종 사실 입력 계약**입니다.

```text
Issue Package
├─ issue
├─ comments[]
├─ attachments[]
├─ relationships[]
├─ custom_fields[]
├─ counts
└─ source_hash
```

`source_hash`는 의미 데이터만 해시하며 생성시각·PC 절대경로는 제외합니다.

### [KNOWLEDGE]

```text
data/knowledge/runs/<run_id>/
├─ issues/<ISSUE_KEY>.json
└─ reviews/<ISSUE_KEY>.review.attempt<N>.json
```

OpenCode Worker가 Knowledge Input을 읽고 만드는 검색용 의미 압축입니다.

Knowledge Schema v0.1:

```text
issue_summary
problem_or_goal[]
key_findings[]
actions_and_decisions[]
outcomes[]
open_items[]
```

각 item:

```text
{
  statement,
  evidence_refs[]
}
```

Evidence type:

```text
summary
description
comment:<id>
attachment:<id>
relationship:<id>
custom_field:<id>
```

Knowledge는 사실 원장을 대체하지 않습니다.

```text
Knowledge
  ↓ evidence_ref
Knowledge Input
  ↓
ANALYSIS
  ↓ source_path
RAW
```

### [DB] — M6 현재 설계

현재 M6에서는 SQLite DDL을 먼저 만들지 않고 논리 Entity와 관계를 확정합니다.

주요 Entity:

```text
pipeline_run
issue
issue_snapshot
comment
attachment
relationship
custom_field_catalog
custom_field_value

knowledge_generation
knowledge_item
knowledge_evidence

knowledge_review
review_finding
```

핵심 Cardinality:

```text
issue                  1 ── N issue_snapshot
issue                  1 ── N knowledge_generation
knowledge_generation   1 ── N knowledge_item
knowledge_item         1 ── N knowledge_evidence
knowledge_generation   1 ── N knowledge_review
knowledge_review       1 ── N review_finding
```

상세 기준은 [M6 DB Logical Schema](docs/DB_LOGICAL_SCHEMA.md)를 참조합니다.

---

## 4. Knowledge Quality Loop

M3/M4에서 고정된 실행 구조입니다.

```text
Orchestrator
    ↓
Fresh Worker · Issue 1건
    ↓
Knowledge JSON
    ↓
Python Validator
    ↓
Fresh Defect Reviewer
    ↓
PASS / REGENERATE
    ↓
최대 3 Attempt
```

PASS 조건:

```text
score >= 8.5
AND critical_error == false
AND major_issue_count == 0
```

Reviewer Audit:

```text
Fact
Causal Claim
Evidence
Classification
Missing Knowledge
Duplication / Low-value
```

의미 판단은 LLM에 맡기되, JSON 구조 검증과 Run 통계 집계는 deterministic Python으로 분리합니다.

---

## 5. HTML 문서

프로젝트를 빠르게 파악할 때는 두 HTML 문서를 먼저 봅니다.

1. **[현재 상태와 향후 계획](docs/status/jira_knowledge_db_current_status.html)**
   - M0~M16 Master Roadmap
   - 현재 M6 위치
   - M5 실제 Profiling 근거
   - M6 설계 및 다음 Gate

2. **[Jira Knowledge Relationship Map](docs/architecture/jira_data_relationship_map.html)**
   - Source Entity
   - Knowledge / Evidence / Review
   - M0~M10 Pipeline
   - Evidence round-trip
   - M6 Logical DB 관계

전체 문서 진입점은 [`docs/index.html`](docs/index.html)입니다.

---

## 6. Milestone Completion Records

완료된 단계의 입력·결정·문제·해결·검증을 별도 기록으로 보존합니다.

- [M0 Jira Collection / Analysis Completion](docs/status/M0_JIRA_COLLECTION_ANALYSIS_COMPLETION.md)
- [M1 Knowledge Input Completion](docs/status/M1_KNOWLEDGE_INPUT_COMPLETION.md)
- [M2 Knowledge Schema / Skill Completion](docs/status/M2_KNOWLEDGE_SCHEMA_SKILL_COMPLETION.md)
- [M3 Knowledge Quality Loop Completion](docs/status/M3_KNOWLEDGE_QUALITY_LOOP_COMPLETION.md)
- [M4 Knowledge Extraction Completion](docs/status/M4_KNOWLEDGE_EXTRACTION_COMPLETION.md)
- [M5 Knowledge / Review Profiling Completion](docs/status/M5_KNOWLEDGE_PROFILING_COMPLETION.md)

현재 설계 문서:

- [M6 DB Logical Schema](docs/DB_LOGICAL_SCHEMA.md)

---

## 7. 상세 명세

Source pipeline:

1. [전체 Pipeline 아키텍처](docs/PIPELINE_OVERVIEW.md)
2. [Collector 상세 설계](docs/DESIGN.md)
3. [댓글 Raw 수집 계약](docs/COMMENT_COLLECTION.md)
4. [Parser Core](docs/PARSER_CORE.md)
5. [Issue Export 명세](docs/ISSUE_EXPORT_SPEC.md)
6. [Comment Export 명세](docs/COMMENT_EXPORT_SPEC.md)
7. [Structure Export 명세](docs/STRUCTURE_EXPORT_SPEC.md)
8. [실제 Jira Structure Profile](docs/JIRA_STRUCTURE_PROFILE.md)
9. [Summary / Warning 공통 계약](docs/RUN_SUMMARY_SPEC.md)
10. [Knowledge Input 상세 명세](docs/KNOWLEDGE_INPUT_SPEC.md)
11. [Knowledge Input 코드 읽기 가이드](docs/KNOWLEDGE_INPUT_CODE_GUIDE.md)
12. [Knowledge Input 실환경 검증 기록](docs/KNOWLEDGE_INPUT_VALIDATION.md)

Knowledge pipeline:

13. [Knowledge Extraction Runtime](docs/KNOWLEDGE_EXTRACTION_RUNTIME.md)
14. [M5 Profiling Metric Contract](docs/KNOWLEDGE_PROFILING_SPEC.md)
15. [M6 DB Logical Schema](docs/DB_LOGICAL_SCHEMA.md)

코드 또는 데이터 계약을 변경할 때는 관련 상세 명세와 현재 상태/관계 맵을 같은 변경 단위에서 갱신합니다.

---

## 8. 요구 환경

- Python 3.11 이상
- Jira Server/Data Center 또는 호환 REST API
- Windows PowerShell, Linux shell 또는 macOS shell

---

## 9. 설치

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

브랜치를 변경하거나 코드를 갱신한 뒤에는 editable install을 다시 실행하는 것이 안전합니다.

---

## 10. Jira 설정

`.env.example`을 `.env`로 복사한 뒤 실제 값을 입력합니다.

```dotenv
JIRA_BASE_URL=https://jira.example.com
JIRA_USERNAME=my-user-id
JIRA_PASSWORD=my-password
```

일반 정책은 `config/settings.yaml`에서 관리합니다.

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
```

현재 Attachment 바이너리는 다운로드하지 않습니다.

---

## 11. Collector / Parser CLI

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

## 12. Knowledge 도구

Knowledge 구조 검증:

```powershell
python tools/jira_knowledge/validate_knowledge.py <KNOWLEDGE_OUTPUT> <KNOWLEDGE_INPUT>
```

M4 Run deterministic 집계:

```powershell
python tools/jira_knowledge/summarize_knowledge_run.py `
  data/knowledge_input/runs/<RUN_ID>/issues `
  data/knowledge/runs/<RUN_ID>/issues `
  data/knowledge/runs/<RUN_ID>/reviews
```

M5 Profiling:

```powershell
python tools/jira_knowledge/profile_knowledge_run.py `
  data/knowledge/runs/<RUN_ID>/issues `
  data/knowledge/runs/<RUN_ID>/reviews `
  --expected-issue-count 30 `
  --output data/knowledge/runs/<RUN_ID>/profile.json
```

---

## 13. 보안 원칙

- Jira 접근은 읽기 전용
- 실제 Jira 데이터는 Git에 올리지 않음
- `JIRA_PASSWORD`와 API Key를 코드/문서에 하드코딩하지 않음
- 로그에 Password, Authorization, Cookie, 전체 원문을 남기지 않음
- ANALYSIS에서 불필요한 개인정보 복제를 최소화
- Knowledge Agent는 M4에서 로컬 Knowledge Input만 사실 입력으로 사용
- Knowledge의 주장은 Evidence 없이 생성하지 않음
- 외부 응답에는 로컬 `source_path`를 노출하지 않음

---

## 14. 현재 안정 경계

```text
Jira
 ↓
RAW
 ↓ deterministic
ANALYSIS
 ↓ deterministic
KNOWLEDGE INPUT
 ───────────────────────── 사실 계약 경계
 ↓ LLM semantic extraction
KNOWLEDGE
 ↓ deterministic validation / review history / profiling
M6 Logical DB
```

따라서 오류를 다음처럼 분리할 수 있습니다.

```text
KNOWLEDGE INPUT이 틀림
→ Collector / Parser / Join 문제

KNOWLEDGE INPUT은 맞고 KNOWLEDGE가 틀림
→ Skill / Worker / Reviewer 해석 문제

Knowledge/Evidence는 맞고 DB round-trip이 틀림
→ M6/M7 ID · Join · Resolver 문제
```

---

## 15. 다음 단계

현재는 **M6 DB Logical Schema**입니다.

M6 Gate:

```text
주요 Entity / Cardinality 합의
Source ID / Knowledge ID 원칙 합의
6개 Evidence type round-trip 표현
Review Attempt / Finding 보존 방식 합의
Run / source_hash / version 추적
M7에서 구현 가능한 field contract 확정
```

Gate 통과 후:

```text
M7 SQLite Materialization
→ M8 Chunk + BGE-M3
→ M9 FAISS + Retrieval
→ M10 Evidence Builder + MCP
```

M10이 Functional MVP 완료선입니다.
