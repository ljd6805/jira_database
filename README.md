# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Knowledge 추출/검토 → Versioned SQLite Knowledge DB → BGE-M3 Embedding → FAISS Retrieval → Evidence/MCP → OpenCode 실제 소비자 검증**까지 발전시킨 프로젝트입니다.

> 📚 사람이 읽는 공식 문서는 [Documentation Hub](docs/index.html)에서 시작하세요. Hub가 연결하는 로컬 문서는 HTML입니다.

현재 기준:

```text
M0~M11 Functional MVP        DONE / PASS
Two-Loop Operational Arch    FROZEN
Sync Contract                v2 FROZEN
Operational State Schema     v2 FROZEN
Implementation               NOT STARTED
```

현재 최상위 기준은 다음 세 문서입니다.

- [2-Loop Operational Architecture](docs/architecture/jira_operational_two_loop_architecture.html)
- [Sync Contract v2](docs/architecture/jira_sync_contract.html)
- [Operational State Schema v2](docs/architecture/jira_sync_state_schema_contract.html)

## 1. Functional MVP — DONE / PASS

```text
Jira REST API
    ↓
M0  RAW → ANALYSIS                          DONE
    ↓
M1  KNOWLEDGE INPUT                         DONE
    ↓
M2  Knowledge Schema + Skill               DONE
    ↓
M3  Worker → Validator → Reviewer          DONE
    ↓
M4  실제 Knowledge Pilot 30/30             DONE
    ↓
M5  Knowledge / Review Profiling           DONE
    ↓
M6  DB Logical Schema / Identity           DONE
    ↓
M7  SQLite Materialization                 DONE · REAL-RUN PASS
    ↓
M8  BGE-M3 Embedding                       DONE · REAL-RUN PASS
    ↓
M9  FAISS + Active Retrieval               DONE · REAL-RUN PASS
    ↓
M10 Evidence Builder + MCP                 DONE · REAL-RUN PASS
    ↓
M11 OpenCode MCP Integration               DONE · USER REAL-RUN PASS
```

## 2. 운영 서비스 — TWO LOOP

지속 운영에서는 Jira Source 최신화와 느리고 변동성이 큰 OpenCode 지식화를 하나의 직렬 Run으로 묶지 않습니다.

```text
Loop A · SOURCE SYNC
source_sync_run
→ Project Discovery
→ Initial / Delta / Catch-up
→ Jira Download
→ RAW / ANALYSIS / Knowledge Input
→ semantic_v2 source_hash
→ NEW / CHANGED / UNCHANGED
→ NEW/CHANGED durable sync_issue_change
→ SOURCE_COMMITTED
→ committed_watermark advance

              ↓ durable backlog

Loop B · KNOWLEDGE PROCESSING / PUBLISH
processing_run
→ backlog Work Item
→ OpenCode Knowledge Generation
→ Review / Evidence
→ Knowledge DB
→ BGE-M3 Embedding
→ FAISS staging / mapping
→ Atomic Publish
→ PUBLISHED

Always-on Retrieval
Published Corpus → FAISS → Evidence/MCP → Team OpenCode
```

두 Loop는 서로 기다리지 않습니다. OpenCode가 느리거나 실패해도 Jira Source Sync는 계속 가능하고, Jira가 일시 장애여도 이미 쌓인 Processing backlog는 처리할 수 있습니다.

## 3. 핵심 불변 원칙

1. **RAW가 사실의 최종 기준**입니다.
2. History Storage와 Active Retrieval을 분리합니다.
3. Generation과 Retry Attempt를 구분합니다.
4. Knowledge / Embedding / Retrieval identity를 서로 섞지 않습니다.
5. FAISS position을 Knowledge identity로 사용하지 않습니다.
6. Knowledge는 `ke_` Evidence를 통해 실제 Jira 근거로 round-trip할 수 있어야 합니다.
7. MCP는 검색/근거 복원만 담당하고 생성형 LLM을 포함하지 않습니다.
8. 운영 기본은 **delta-first**이며 full rebuild는 복구/마이그레이션/검증 경로입니다.
9. **Jira Source Lifecycle ≠ Knowledge Lifecycle** 입니다.
10. **SOURCE_COMMITTED ≠ PUBLISHED** 입니다.
11. Source Loop와 Processing Loop는 독립적인 Run / Scheduler / 실패 경계를 가집니다.
12. 새 Publish가 완성될 때까지 last-known-good Published Knowledge를 계속 제공합니다.
13. Watermark는 Project Source Commit보다 먼저 전진하지 않습니다.
14. 실제 durable 산출물이 State의 `completed/published` 표시보다 먼저입니다.
15. 설계/코드/Milestone 상태 변경은 HTML 문서와 같은 작업 단위에서 동기화합니다.

## 4. Identity

```text
Jira identity
project_id / jira_id

Operational State
sr_   Source Sync Run
pr_   Processing Run
sw_   Semantic Work Item

Knowledge
jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_

Embedding / Retrieval
ec_   Embedding Contract
emb_  Embedding Artifact
rc_   Retrieval Contract
fi_   FAISS Index Artifact

FAISS position ≠ emb_ ≠ ki_
```

`sw_`는 `jira_id + source_hash + source_hash_profile`에서 결정적으로 생성합니다. 같은 semantic state를 여러 Source Run에서 다시 만나도 같은 Work Item을 재사용합니다.

## 5. Operational State Schema v2

기존 `data/state/collector.db`를 **명시적 Versioned Migration**으로 확장합니다.

```text
STATE_SCHEMA_VERSION = 2
PRAGMA user_version = 2

Operational Domain Tables
source_sync_run
project_state
source_project_run
sync_issue_change
processing_run

Technical Metadata
state_schema_migration
```

기존 `collection_runs`, `project_runs`, `issue_checkpoints`, `artifacts`는 첫 Migration에서 삭제하거나 의미를 바꾸지 않습니다.

State Schema v1은 실제 구현 전에 2-Loop 채택으로 대체되었으며 [v1 Historical Baseline](docs/architecture/jira_sync_state_schema_contract_v1_baseline.html)으로만 보존합니다.

## 6. Sync Contract 핵심

```text
D1  Project별 committed Watermark
D2  5분 Overlap + fixed upper + updated/id stable order
D3  NEW / CHANGED / UNCHANGED
D4  source_hash_profile = semantic_v2
D5  Loop별 Checkpoint / Resume
D6  Project Registry + Knowledge Retention
D7  SOURCE_COMMITTED ≠ PUBLISHED
D8  Run 상태 = Loop-local completed / partial / failed
D9  Two-Loop Operational Architecture
```

### Delta Source Query

```text
lower = committed_watermark - 5m
upper = source_sync_run 시작 시 고정

updated >= lower
updated < upper
ORDER BY updated ASC, id ASC
```

Jira `updated`는 후보 탐색 신호일 뿐 실제 semantic change는 `semantic_v2 source_hash`로 판정합니다.

## 7. 운영 최신성 / Backpressure

2-Loop 시스템에는 하나의 전체 `run_status`를 두지 않습니다.

```text
Source Lag
→ Jira Source를 어디까지 안전하게 읽었나?

Publish Lag
→ Source Head와 Published Head가 얼마나 차이나나?

Backlog Depth
→ Loop B가 아직 처리하지 못한 Work Item이 몇 개인가?

Oldest Pending Age
→ 가장 오래 기다리는 Work Item은 얼마나 오래됐나?
```

추가로 Processing Throughput, OpenCode latency/error를 시간대별로 측정합니다.

2-Loop는 병목을 없애는 구조가 아니라 **느린 Processing 병목을 Source 최신화에서 격리하고 관측 가능하게 만드는 구조**입니다.

## 8. MVP 핵심 숫자

```text
Issue                         30
Comment                      278
Attachment metadata           79
Canonical Relationship         6
Custom Field Catalog         220
Custom Field Values          447

Knowledge Item               285
M5 Raw Evidence Ref          503
M7 Canonical Evidence Row    502
Review Attempt                37
M8 Embedding                 285
M9 FAISS Vector              285
```

M5 raw Evidence 503 중 historical duplicate 1회를 M7에서 canonicalize해 502 row를 저장합니다.

## 9. M7 SQLite — DONE / PASS

```text
Issue / Generation       30 / 30
Attempt / Review         37 / 37
Knowledge Item          285
Evidence raw/canonical  503 / 502
Evidence Failure          0
FK Failure                0
Integrity                OK
Idempotent               true
```

```text
Issue
└─ Issue Version · iv_
   └─ Knowledge Generation · kg_
      └─ Knowledge Attempt · ka_ + attempt_no
         ├─ Knowledge Item · ki_
         │  └─ Knowledge Evidence · ke_
         └─ Knowledge Review
```

## 10. M8 BGE-M3 — DONE / PASS

```text
Knowledge Item 1개 = Embedding Unit 1개
text_profile       statement_v1
model              BAAI/bge-m3
dimension          1024
batch max          64
corpus_rows         285
embedding_rows      285
batch_count           5
```

## 11. M9 FAISS — DONE / PASS

```text
Index       IndexFlatIP
Metric      cosine = L2 normalize + inner product
Query       raw_query_v1 = query.strip()
Top-k       3
Threshold   none
Reranker    none
Mapping     FAISS position → emb_ → ki_
```

```text
vector_count                  285
dimension                    1024
mapping/hash/norm failure       0
same-source rebuild            PASS
same-query vector              PASS
same-query ranking             PASS
same-query scores              PASS
```

## 12. M10 Evidence + MCP — DONE / PASS

```text
질문 → BGE-M3 → FAISS Top-3 Knowledge
→ ki_ active/accepted 재검증
→ ke_ Evidence resolve
→ 실제 Jira source 복원
→ Evidence Package
→ MCP
```

MCP Tools:

```text
search_jira_knowledge
get_jira_issue
```

MCP에는 생성형 LLM이 없습니다.

## 13. M11 OpenCode Integration — DONE / PASS

```text
M11-01 .env service configuration                PASS
M11-02 local stdio OpenCode 연결                 PASS
M11-03 OpenCode Tool 2개 discovery              PASS
M11-04 명시적 MCP Tool call                     PASS
M11-05 일반 업무 질문에서 자동 Tool selection   PASS
M11-06 description/comment Evidence 추적         PASS
```

여기까지가 Functional MVP입니다.

## 14. Central Remote MCP

Central MCP는 두 Loop를 실행하는 엔진이 아닙니다.

```text
Loop A / Loop B
→ 새 Published Corpus를 준비/전환

Central MCP
→ 현재 Published Corpus 읽기
→ FAISS / Evidence Resolver
→ 팀원 OpenCode에 Tool 제공
```

새 Processing/Publish가 실패해도 마지막 정상 Published Corpus를 계속 제공합니다.

상세: [MCP Service Target](docs/architecture/jira_knowledge_mcp_service_target.html)

## 15. 다음 결정과 구현 순서

### 다음 아키텍처 결정

**Intermediate Version supersede policy**

```text
Source Loop
V2 → V3 → V4

Processing Loop가 아직 V2를 시작하지 않음

선택 필요
A. V2/V3/V4 모두 Knowledge 처리
B. Source Version은 모두 보존하되 미시작 V2/V3 Work는 supersede하고 V4 처리
```

이 정책은 아직 Freeze하지 않았습니다.

### 그 다음 구현

```text
State Schema v2 explicit Migration
→ StateStore v2
→ Loop A Delta Source Sync
→ durable backlog producer
→ Loop B processing_run + Single Worker
→ OpenCode / Review / Embedding / Publish
→ Source Lag / Publish Lag / Backlog Monitoring
→ Central Remote MCP Operations
```

Multi-worker claim/lease와 외부 MQ는 실제 Single Worker 처리량을 측정한 뒤 결정합니다.

## 16. 주요 문서

- [Documentation Hub](docs/index.html)
- [2-Loop Operational Architecture](docs/architecture/jira_operational_two_loop_architecture.html)
- [Sync Contract v2](docs/architecture/jira_sync_contract.html)
- [Sync Contract 쉬운 가이드](docs/architecture/jira_sync_contract_easy_guide.html)
- [Operational State Schema v2](docs/architecture/jira_sync_state_schema_contract.html)
- [Full Pipeline](docs/architecture/jira_knowledge_pipeline_full_explained.html)
- [Operational Service Phase](docs/architecture/jira_knowledge_operational_service_phase.html)
- [MCP Service Target](docs/architecture/jira_knowledge_mcp_service_target.html)
- [Current Status](docs/status/jira_knowledge_db_current_status.html)
- [Latest Handoff](docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html)
- [Pipeline Overview](docs/PIPELINE_OVERVIEW.html)
- [Relationship Map](docs/architecture/jira_data_relationship_map.html)
- [Documentation Policy](docs/DOCUMENTATION_POLICY.html)

## 17. 로컬 MVP Artifact

```text
M7 SQLite
data/knowledge_db/validation/20260804T043628Z.sqlite3

M8 corpus
data/embedding/runs/20260804T043628Z/corpus.statement_v1.jsonl

M8 embeddings
data/embedding/runs/20260804T043628Z/embeddings.statement_v1.bge_m3.jsonl

M9 retrieval
data/retrieval/runs/20260804T043628Z/
├─ index.faiss
├─ index.mapping.jsonl
└─ index.manifest.json
```

`data/`, `.env`, local config, DB는 Git에서 제외합니다. Public repo에는 실제 Jira Issue Key/raw body/사내 endpoint/custom header/token/로컬 절대경로를 기록하지 않습니다.
