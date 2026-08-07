# Jira Knowledge Pipeline 전체 아키텍처

## 1. 문서 목적

이 문서는 Jira 데이터를 수집한 뒤 최종적으로 Agent가 검색·분석할 수 있는 지식 시스템으로 발전시키기 위한 전체 파이프라인을 한 문서에서 설명합니다.

현재 구현은 **RAW 수집 → ANALYSIS 정규화 → KNOWLEDGE INPUT 조립**까지 완료되었습니다.

```text
Jira REST API
    ↓
[RAW]
Jira 원본 JSON
    ↓
Parser / Exporter
    ↓
[ANALYSIS]
정규화된 사실 데이터
    ↓
IssueKnowledgeInputBuilder
    ↓
[KNOWLEDGE INPUT]
이슈별 최종 분석 입력 패키지
    ↓
OpenCode Agent                    # 다음 단계
    ↓
[KNOWLEDGE]                       # 다음 단계
원인·계획·결정·결과·결론 등 파생 지식
    ↓
SQLite / Chunk / BGE-M3 / FAISS  # 이후 단계
    ↓
Retriever / MCP
```

이 계층 분리의 핵심 목적은 **사실의 보존과 LLM 해석을 분리**하는 것입니다.

---

## 2. 데이터 계층 정의

### 2.1 RAW

```text
[RAW]
data/raw/runs/<run_id>/...
```

역할:

- Jira API가 반환한 원본의 사실 기준
- 재파싱·재검증·재가공의 출발점
- Parser가 수정하지 않는 read-only 계층

대표 파일:

```text
issue.json
comments/page_*.json
```

RAW에는 ANALYSIS에서 의도적으로 제외한 정보도 존재할 수 있습니다.

예:

```text
원본 HTML
emailAddress
avatarUrls
Jira self URL
plugin 전용 복합 객체
```

---

### 2.2 ANALYSIS

```text
[ANALYSIS]
data/analysis/<run_id>/
```

역할:

- RAW를 결정적으로 정규화한 데이터
- HTML 정제, 타입 검증, 관계 canonicalization 수행
- 다음 계층이 Jira API 원본 구조에 직접 의존하지 않도록 하는 안정된 계약

현재 출력:

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

ANALYSIS는 LLM을 사용하지 않습니다.

같은 RAW 입력과 같은 Parser 버전이면 같은 의미의 ANALYSIS 결과가 나와야 합니다.

---

### 2.3 KNOWLEDGE INPUT

```text
[KNOWLEDGE INPUT]
data/knowledge_input/runs/<run_id>/
```

역할:

- 여러 ANALYSIS JSONL을 `issue_key` 기준으로 조립
- OpenCode Agent가 한 이슈를 분석할 때 필요한 최종 사실 입력 제공
- 아직 원인·계획·결론을 추론하지 않음

출력:

```text
issues/<ISSUE_KEY>.json
package_warnings.jsonl
manifest.json
```

한 이슈 패키지는 다음 구조를 가집니다.

```text
Issue
├─ 핵심 정보 + Description
├─ Comments
├─ Attachment metadata
├─ Relationships
└─ Custom Fields
```

---

### 2.4 KNOWLEDGE — 향후

```text
[KNOWLEDGE]
data/knowledge/...
```

OpenCode Agent가 KNOWLEDGE INPUT을 읽고 의미를 재가공하는 계층입니다.

후보 지식 항목:

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

이 값은 Jira 원문 자체가 아니라 **LLM이 원문을 근거로 해석한 파생 데이터**입니다.

따라서 반드시 KNOWLEDGE INPUT 및 RAW까지 역추적할 수 있어야 합니다.

---

### 2.5 DB / VECTOR — 향후

관계와 검색을 위한 파생 저장 계층입니다.

```text
SQLite
├─ Issue / Comment / Attachment
├─ Relationship
├─ Custom Field
├─ Knowledge Item
└─ Evidence

FAISS
└─ embedding_id + vector
```

FAISS는 원문 저장소가 아닙니다.
원문과 관계는 DB와 파일 계층에서 관리합니다.

---

## 3. 현재 구현 완료 범위

### 3.1 Collector

완료:

- ID/Password 기반 Jira 읽기
- 접근 가능한 프로젝트 발견
- 프로젝트별 최근 수정 이슈 최대 30개 파일럿
- 이슈 상세 원본 저장
- 댓글 전용 API 전체 페이지 저장
- SHA-256 무결성 검증
- SQLite checkpoint 및 resume
- 원자 파일 저장

### 3.2 Issue Parser / Exporter

완료:

```text
issue.json
→ IssueParser
→ issues.jsonl
```

실환경 검증:

```text
이슈 30건
저장 30건
실패 0
경고 0
```

### 3.3 Comment Parser / Exporter

완료:

```text
comments/page_*.json
→ CommentParser
→ comments.jsonl
```

실환경 검증:

```text
대상 이슈 30
댓글 278
저장 278
중복 0
실패 0
경고 0
```

### 3.4 Structure Parser / Exporter

완료:

```text
issue.json 1회 읽기
→ Attachment
→ Relationship
→ Custom Field Catalog / Values
```

실환경 검증:

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

### 3.5 Knowledge Input Builder

완료:

```text
ANALYSIS 6개 JSONL
→ issue_key JOIN
→ 이슈별 JSON
```

실환경 검증:

```text
대상 이슈              30
생성 패키지            30
포함 댓글             278
포함 첨부              79
canonical 관계          6
Custom Field 값       447
패키지 경고             0
manifest status completed
pytest 100% pass
```

---

## 4. 현재의 안정 경계

현재까지의 처리는 모두 **결정적 처리**입니다.

```text
RAW
→ ANALYSIS
→ KNOWLEDGE INPUT
```

여기까지는 LLM 추론이 없습니다.

따라서 문제를 다음처럼 분리할 수 있습니다.

```text
KNOWLEDGE INPUT이 틀림
→ Collector / Parser / Join 문제

KNOWLEDGE INPUT은 맞고 KNOWLEDGE가 틀림
→ OpenCode Agent / Prompt / Extraction 문제
```

이 경계가 이후 품질 검증의 기준이 됩니다.

---

## 5. 원본 추적 체계

각 계층은 다음 식별자를 가능한 한 유지합니다.

```text
issue_key
comment_id
attachment_id
relationship_id
field_id
source_path
```

향후 예:

```text
Knowledge Item
→ evidence comment_id=5001
→ KNOWLEDGE INPUT comment 5001
→ ANALYSIS comments.jsonl
→ RAW comments/page_0001.json
```

지식 추출 결과가 원문 근거로 돌아갈 수 있어야 합니다.

---

## 6. source_hash의 역할

각 KNOWLEDGE INPUT 패키지는 의미 데이터 기반 SHA-256을 가집니다.

```text
source_hash = SHA256(
    issue
  + comments
  + attachments
  + relationships
  + custom_fields
)
```

다음 값은 hash에서 제외합니다.

```text
generated_at
source_path
source_page
PC 설치 경로
```

향후 증분 처리:

```text
기존 hash == 신규 hash
→ OpenCode 재분석 불필요

기존 hash != 신규 hash
→ Knowledge 재추출 필요
```

---

## 7. 개인정보 최소화 원칙

RAW에는 Jira가 반환한 사용자 객체 전체가 존재할 수 있습니다.

ANALYSIS부터는 검색·관계 연결에 필요한 값만 최소한으로 유지합니다.

예:

```text
유지 가능:
displayName
name / key

기본 제외:
emailAddress
avatarUrls
self
timeZone
전체 user object
```

KNOWLEDGE INPUT은 RAW를 다시 읽지 않기 때문에 ANALYSIS에서 제거한 개인정보가 다시 복원되지 않습니다.

---

## 8. 오류와 완료 표식

### ANALYSIS

```text
summary.json
parse_warnings.jsonl
```

### KNOWLEDGE INPUT

```text
manifest.json
package_warnings.jsonl
```

`manifest.json`은 마지막에 작성합니다.

빌드가 중간에 끊기면 manifest가 없으므로 완료된 run으로 오해하지 않습니다.

---

## 9. 다음 개발 단계

다음 단계는 **OpenCode Agent Knowledge Extraction**입니다.

권장 순서:

```text
1. Knowledge Extraction 출력 스키마 정의
2. Agent Prompt / Skill 계약 정의
3. 대표 이슈 5건 파일럿
4. 원문 대비 사람 검증
5. Prompt / Schema 수정
6. 30개 전체 재가공
7. source_hash 기반 증분 재분석
8. Knowledge JSONL 저장
9. Data Profiling / Excel
10. DB 스키마
11. Chunk / Embedding / FAISS
12. Retriever
13. MCP
```

OpenCode Agent 단계에서 가장 중요한 원칙은 **추측과 확정 사실을 구분하고, 모든 지식 항목에 evidence를 연결하는 것**입니다.
