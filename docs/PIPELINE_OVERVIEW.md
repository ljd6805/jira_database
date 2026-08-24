# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-24  
현재 단계: **M6 · DB Logical Schema**

## 1. 문서 목적

이 문서는 Jira 원본에서 시작해 검색 가능한 업무지식 시스템과 MCP까지 이어지는 **전체 데이터 계층과 책임 경계**를 설명합니다.

현재 진행 상태:

```text
M0  Jira 수집 · ANALYSIS 정규화          DONE
M1  Issue Knowledge Input              DONE
M2  Knowledge Schema · Skill           DONE
M3  Quality Loop                       DONE
M4  실제 Jira Knowledge Pilot          DONE
M5  Knowledge / Review Profiling       DONE
M6  DB Logical Schema                  CURRENT
M7  SQLite Materialization             NEXT
M8  Chunk · BGE-M3
M9  FAISS · Retrieval
M10 Evidence Builder · MCP             Functional MVP Gate
```

현재 전체 흐름:

```text
Jira REST API
    ↓
[RAW]                                  M0
    ↓ deterministic parser/exporter
[ANALYSIS]                             M0
    ↓ deterministic issue join
[KNOWLEDGE INPUT]                      M1
    ↓ Skill v0.9 + Worker
[KNOWLEDGE]                            M2~M4
    ├─ Python Validator
    └─ [REVIEW] Attempt history        M3~M4
            ↓
Knowledge / Review Profiling           M5
            ↓
DB Logical Schema                      M6
            ↓
SQLite                                 M7
            ↓
Chunk + BGE-M3                         M8
            ↓
FAISS + Retrieval                      M9
            ↓
Evidence Builder + MCP                 M10
```

핵심 목적은 **사실 보존, LLM 해석, 검색 인프라의 책임을 서로 분리**하는 것입니다.

---

## 2. 핵심 불변 원칙

### 2.1 RAW가 Source of Truth

```text
[RAW]
→ ANALYSIS
→ KNOWLEDGE INPUT
→ KNOWLEDGE
→ DB
→ VECTOR
```

뒤 계층은 모두 RAW에서 다시 만들 수 있는 파생물이어야 합니다.

### 2.2 결정적 처리와 LLM 의미 해석 분리

LLM이 개입하지 않는 경계:

```text
Jira → RAW → ANALYSIS → KNOWLEDGE INPUT
```

LLM이 의미를 해석하는 경계:

```text
KNOWLEDGE INPUT → KNOWLEDGE
```

구조 검증·집계·Profiling은 다시 deterministic Python으로 처리합니다.

### 2.3 Knowledge는 사실 원장이 아니다

Knowledge는 검색을 위한 **Light Structured semantic representation**입니다.

최종 사실 확인 경로:

```text
Knowledge Item
    ↓ evidence_ref
Knowledge Input
    ↓
ANALYSIS source entity
    ↓ source_path
RAW
```

### 2.4 Issue가 지식화 중심 Hub

```text
Issue
├─ Core / Snapshot
├─ Comments
├─ Attachments
├─ Relationships
├─ Custom Fields
├─ Knowledge Generation
├─ Knowledge Items
└─ Reviews
```

### 2.5 Evidence round-trip은 M6 핵심 계약

현재 Evidence type:

```text
summary
description
comment:<id>
attachment:<id>
relationship:<id>
custom_field:<id>
```

M6/M7에서는 이 exact reference를 잃지 않고 실제 source entity까지 다시 찾아갈 수 있어야 합니다.

---

## 3. [RAW] 계층

경로:

```text
data/raw/runs/<run_id>/...
```

역할:

- Jira API 응답 보존
- 재파싱/재검증 기준
- Parser가 수정하지 않는 read-only 사실 계층
- SHA-256 무결성 확인
- Run별 snapshot 분리

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

M0에서 중요한 구현 결정:

- 접근 가능한 프로젝트 전체 발견
- 프로젝트별 최근 수정 이슈 최대 30개
- Jira API 요청 최대 20회/분
- 동시 요청 1개
- Atomic file replace
- SQLite checkpoint / resume
- 프로젝트 단위 실패 격리
- 댓글은 Issue 응답의 embedded comment를 신뢰하지 않고 전용 Comment API를 `startAt=0`부터 전체 수집

---

## 4. [ANALYSIS] 계층

경로:

```text
data/analysis/<run_id>/
```

출력:

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

역할:

- HTML 정제
- 타입 검증
- Comment sequence 정규화
- Relationship canonicalization
- Attachment metadata 정규화
- Custom Field Catalog / Values 분리
- 개인정보 불필요 복제 최소화
- RAW `source_path` 보존

실환경 M0 결과:

```text
Issue                         30
Comment                      278
Attachment                    79
Canonical Relationship         6
Custom Field Catalog         220
Custom Field Value           447
경고/실패                       0
```

---

## 5. [KNOWLEDGE INPUT] 계층

경로:

```text
data/knowledge_input/runs/<run_id>/
├─ issues/<ISSUE_KEY>.json
├─ package_warnings.jsonl
└─ manifest.json
```

역할:

- ANALYSIS 여러 JSONL을 `issue_key`로 JOIN
- Worker가 한 파일만 읽어도 해당 Issue의 사실 맥락을 모두 알 수 있게 함
- RAW를 다시 읽지 않음
- LLM 추론을 수행하지 않음

한 패키지:

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

M1 핵심 계약:

- ANALYSIS 5개 영역이 모두 completed여야 시작
- Relationship canonical edge는 유지하고 현재 Issue 관점만 추가
- 파일럿 외부 endpoint도 `other_package_available=false`로 관계를 보존
- Attachment는 `content_available=false`
- `source_hash`는 의미 데이터만 반영
- 빌드 시작 시 기존 manifest 제거
- 모든 package/warning 저장 후 마지막에 manifest를 원자 기록

실환경 M1:

```text
Issue package              30 / 30
Comment                   278
Attachment                 79
Canonical Relationship      6
Custom Field Value        447
Package warning             0
manifest.status      completed
```

---

## 6. [KNOWLEDGE] 계층

경로:

```text
data/knowledge/runs/<run_id>/issues/<ISSUE_KEY>.json
```

M2에서 고정한 Knowledge Schema v0.1:

```text
knowledge_schema_version
issue_key
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
  "statement": "...",
  "evidence_refs": ["comment:...", "description", ...]
}
```

핵심 Skill 규칙:

- 입력에 없는 사실 생성 금지
- Evidence 없는 Knowledge 생성 금지
- 빈 배열 허용
- 원문 certainty를 높이지 않음
- 댓글 sequence를 시간 흐름으로 읽음
- 후속 결과가 초기 가설을 뒤집으면 반영
- Finding / Decision / Outcome / Open Item을 구분
- 선택 이유를 이해하는 데 필요한 trade-off 보존
- 첨부 본문이 없으면 상상하지 않음

모델 결정:

```text
Pro Worker + Pro Reviewer
```

MAX는 일부 복잡한 사례에서 더 섬세했지만 처리 시간이 10배 이상 느려 검색용 의미 압축 목적에서는 제외했습니다.

---

## 7. [REVIEW] 계층과 Quality Loop

Review 경로:

```text
data/knowledge/runs/<run_id>/reviews/
<ISSUE_KEY>.review.attempt<N>.json
```

실행 구조:

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

PASS:

```text
score >= 8.5
AND critical_error == false
AND major_issue_count == 0
```

Reviewer Audit:

```text
Fact Audit
Causal Claim Audit
Evidence Audit
Classification Audit
Missing Knowledge Audit
Duplication / Low-value Audit
```

M3의 핵심은 **Context 격리**입니다.

- Orchestrator는 본문을 읽지 않고 경로/상태만 관리
- Worker/Reviewer는 Issue 한 건만 읽음
- REGENERATE는 새 Worker Context에서 원본 + 이전 Review를 읽고 전체 Knowledge 재생성
- 다음 Issue로 넘어가기 전에 현재 Issue를 종료
- 구조 검증은 Python Validator
- 다건 집계는 deterministic summarizer

M4 실제 결과:

```text
30/30 final PASS
1차 24
2차 5
3차 1
재생성 6
INPUT_ERROR 0
REVIEW_REQUIRED 0
Human Validation 5/5
```

---

## 8. M5 Profiling이 M6에 준 근거

M5는 Knowledge를 다시 생성하지 않고 실제 30건 산출물의 분포를 deterministic하게 측정했습니다.

```text
Knowledge Item               285
Issue당 item mean            9.5
Issue당 item p95            16.1
Issue당 item max              19

Statement p50                104 chars
Statement p95              206.4 chars
Statement max                447 chars

Evidence Ref                 503
Evidence / item mean        1.76
Evidence / item max           13
Comment Evidence           79.92%

Review JSON                   37
Final PASS                 30/30
```

M6 설계에 반영한 제약:

1. Issue → Knowledge Item은 1:N
2. Knowledge Item → Evidence는 1:N
3. Comment round-trip이 가장 중요한 source path
4. 6개 category를 별도 테이블로 남발하지 않음
5. Empty category는 정상
6. `issue_summary`와 fine-grained item 역할 차이를 보존
7. 현재 p95/max를 DB hard limit로 사용하지 않음
8. 모든 Review Attempt와 historical defect를 보존

---

## 9. M6 DB Logical Schema

M6는 SQLite DDL 단계가 아닙니다.

현재 논리 구조:

```text
Pipeline Run
   │
   ├── Issue Snapshot
   │      ├── Comment
   │      ├── Attachment
   │      ├── Custom Field Value
   │      └── Relationship
   │
   └── Knowledge Generation
          ├── Knowledge Item
          │      └── Knowledge Evidence
          └── Knowledge Review
                 └── Review Finding
```

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
pipeline_run          1 ── N issue_snapshot
issue                 1 ── N issue_snapshot
issue                 1 ── N knowledge_generation
knowledge_generation  1 ── N knowledge_item
knowledge_item        1 ── N knowledge_evidence
knowledge_generation  1 ── N knowledge_review
knowledge_review      1 ── N review_finding
```

ID 원칙:

- Jira/source가 이미 제공하는 ID는 authoritative source identity로 유지
- DB surrogate key는 내부 저장 최적화용
- Knowledge Generation/Item은 deterministic logical ID 사용
- FAISS vector position은 Knowledge identity가 아님

상세 문서:

```text
docs/DB_LOGICAL_SCHEMA.md
```

---

## 10. Evidence round-trip 계약

예:

```text
Knowledge Item
    ↓
evidence_ref = comment:5001
    ↓
knowledge_evidence
    ↓
type = comment
source_run_id + source_issue_key + source_entity_key
    ↓
comment(run_id, issue_key, comment_id)
    ↓
source_path
    ↓
RAW comments/page_*.json
```

Type별 resolver:

```text
summary
→ issue_snapshot.summary

description
→ issue_snapshot.description

comment:<id>
→ comment

attachment:<id>
→ attachment

relationship:<id>
→ relationship

custom_field:<id>
→ custom_field_value
```

M6 Gate에서는 이 6개 경로를 모두 표현할 수 있어야 합니다.

---

## 11. 현재 안정 경계

```text
RAW
 ↓
ANALYSIS
 ↓
KNOWLEDGE INPUT
 ─────────────── deterministic source boundary
 ↓
KNOWLEDGE
 ↓
Validator / Review / Profiling
 ↓
M6 Logical DB
```

오류 분리:

```text
RAW/ANALYSIS/KNOWLEDGE INPUT 오류
→ Collector / Parser / Join 문제

KNOWLEDGE 의미 오류
→ Skill / Worker / Reviewer 문제

Evidence Resolver / DB round-trip 오류
→ Logical ID / Join / Materialization 문제
```

---

## 12. 보안과 개인정보

- Jira는 읽기 전용
- 실제 Raw/Analysis/Knowledge 데이터를 Git에 저장하지 않음
- Password/API Key 하드코딩 금지
- 로그에 Authorization/Cookie/전체 원문을 남기지 않음
- ANALYSIS부터 개인정보 불필요 복제 최소화
- M4 Knowledge Agent는 로컬 Knowledge Input만 사실 입력으로 사용
- 외부 MCP 응답에 로컬 `source_path`를 직접 노출하지 않음

---

## 13. 현재와 다음 단계

현재:

```text
M6 DB Logical Schema
```

M6 Gate:

```text
Entity / Cardinality
Source ID / Knowledge ID
Evidence round-trip
Review Attempt / Finding 보존
Run / source_hash / version
M7 구현 가능한 field contract
```

다음:

```text
M7 SQLite Materialization
→ DDL
→ Loader / Upsert
→ Index / FK / UNIQUE
→ Integrity / Evidence round-trip tests

M8 Chunk + BGE-M3
M9 FAISS + Retrieval
M10 Evidence Builder + MCP
```

M10이 Functional MVP 완료선입니다.
