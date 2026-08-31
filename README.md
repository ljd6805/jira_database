# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Knowledge 추출/검토 → Versioned SQLite Knowledge DB → BGE-M3 Embedding → FAISS Retrieval → Evidence/MCP → OpenCode 실제 소비자 검증**까지 발전시킨 프로젝트입니다.

> 📚 사람이 읽는 공식 문서는 [Documentation Hub](docs/index.html)에서 시작하세요. Hub가 연결하는 로컬 문서는 HTML입니다.

현재 기준:

```text
M0~M11 Functional MVP                  DONE / PASS
Two-Loop Operational Architecture      FROZEN
D10 Latest-Only Processing             FIXED
현재 운영 Sync 규칙 · 개정 3           FROZEN
현재 Operational State 설계 · 개정 3   FROZEN
State Migration / StateStore foundation IMPLEMENTED · UNIT PASS
실제 local collector.db Migration       NOT RUN YET
Loop A Delta Integration                NEXT
```

현재 최상위 기준 문서:

- [Operational State 개정 3 구현 보고서](docs/status/OPERATIONAL_STATE_REV3_FOUNDATION_IMPLEMENTATION.html)
- [현재 운영 Sync Contract · 개정 3](docs/architecture/jira_sync_contract.html)
- [D10 Latest-Only Processing](docs/architecture/jira_sync_contract_decision10_latest_only_processing.html)
- [현재 Operational State Schema · 개정 3](docs/architecture/jira_sync_state_schema_contract.html)
- [2-Loop Operational Architecture](docs/architecture/jira_operational_two_loop_architecture.html)
- [버전 표기 가이드](docs/VERSION_TERMINOLOGY_GUIDE.html)

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

## 2. 운영 서비스 — TWO LOOP + LATEST ONLY

Jira Source 최신화와 느리고 변동성이 큰 OpenCode 지식화를 하나의 직렬 Run으로 묶지 않습니다.

```text
Loop A · SOURCE SYNC
source_sync_run
→ Project Discovery
→ Initial / Delta / Catch-up
→ Jira Download
→ RAW / ANALYSIS / Knowledge Input
→ semantic_v2 source_hash
→ NEW / CHANGED / UNCHANGED
→ 모든 Source Version 보존
→ NEW/CHANGED durable sync_issue_change
→ SOURCE_COMMITTED
→ committed_watermark + Source Ready
→ 같은 jira_id의 이전 미완료 Work superseded

              ↓ latest-only durable backlog

Loop B · KNOWLEDGE PROCESSING / PUBLISH
processing_run
→ latest + source-ready Work Item만 claim
→ OpenCode Knowledge Generation
→ latestness re-check
→ Review / Evidence
→ Knowledge DB
→ BGE-M3 Embedding
→ FAISS staging / mapping
→ latestness re-check
→ Atomic Publish
→ PUBLISHED

Always-on Retrieval
Published Corpus → FAISS → Evidence/MCP → Team OpenCode
```

두 Loop는 서로 기다리지 않습니다. OpenCode가 느려도 Jira Source Sync는 계속되고, 중간 Source Version은 History로 남지만 비싼 AI 처리는 최신 Version만 수행합니다.

## 3. Latest-Only Processing

```text
Source History
상태 A → B → C → D
모두 보존

Knowledge Processing
A already Published
B pending → superseded
C pending → superseded
D latest  → process
```

구버전 Work가 이미 OpenCode 처리 중이면 외부 호출을 기본적으로 강제 취소하지 않습니다. 응답 후 최신성을 다시 검사하고 stale이면 Active Knowledge 저장, Embedding, Publish를 중단합니다.

구조화 로그:

```text
work_item_superseded
processing_skip_superseded
stale_inflight_detected
latest_processing_started
work_item_reactivated
```

로그에는 Jira 원문/댓글 본문을 넣지 않고 identity/run/stage/reason/timestamp만 기록합니다.

## 4. Operational State foundation — IMPLEMENTED

첫 운영 구현 단위가 완료됐습니다.

```text
src/jira_collector/state_schema.py
→ schema inspection / fingerprint
→ explicit migration / backup / integrity
→ unknown schema fail-closed

src/jira_collector/state_store.py
→ 기존 Collector State API 유지
→ Loop A Source state
→ Loop B Processing state
→ Source Ready / supersede / stale guard

tools/migrate_state_v3.py
→ legacy collector.db explicit migration

tests/test_state_schema_v3.py
→ migration / rollback / Latest-Only regression
```

### Silent migration 금지

새/빈 DB는 현재 Operational State 설계로 초기화하지만, 기존 known legacy `collector.db`는 일반 실행에서 자동 변경하지 않습니다.

```text
legacy collector.db
→ StateStore open
→ MigrationRequiredError
→ explicit migration 필요
```

실제 Migration 명령:

```bash
python tools/migrate_state_v3.py --database data/state/collector.db
```

> 이 명령을 실행하는 기능은 구현됐지만, 저장소 원격 작업만으로 실제 사용 중인 `data/state/collector.db`가 Migration됐다고 간주하지 않습니다. 실제 환경에서 writer를 중지하고 backup 결과와 기존 Resume 동작을 확인해야 합니다.

## 5. T3 Source Commit 원자성

```text
BEGIN

source_project_run.source_status = source_committed
project_state.committed_watermark = upper
현재 Work Item = Source Ready
이전 pending/failed/running Work = superseded

COMMIT
```

이 Transaction이 실패하면 Watermark/Ready/Supersede가 함께 rollback됩니다.

## 6. Identity

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

## 7. 현재 Operational State DB 구조

기존 `data/state/collector.db`를 **명시적 Versioned Migration**으로 확장하는 설계입니다.

```text
STATE_SCHEMA_VERSION = 3
PRAGMA user_version = 3

Operational Domain Tables
source_sync_run
project_state
source_project_run
sync_issue_change
processing_run

Latest-Only lifecycle
work_status
superseded_by_work_item_id
superseded_at
supersede_reason

processing_run
superseded_count

Technical Metadata
state_schema_migration
```

기존 `collection_runs`, `project_runs`, `issue_checkpoints`, `artifacts`는 첫 Migration에서 삭제하거나 의미를 바꾸지 않습니다.

과거 Operational State 설계 개정 1/2는 실제 배포 전에 후속 결정으로 대체된 historical baseline입니다.

## 8. 현재 운영 Sync 규칙

```text
D1  Project별 committed Watermark
D2  5분 Overlap + fixed upper + updated/id stable order
D3  NEW / CHANGED / UNCHANGED
D4  source_hash_profile = semantic_v2
D5  Loop별 Checkpoint / Resume
D6  Project Registry + Knowledge Retention
D7  SOURCE_COMMITTED ≠ PUBLISHED + Source Ready Gate
D8  Run 상태 = Loop-local completed / partial / failed
D9  Two-Loop Operational Architecture
D10 Latest-Only Knowledge Processing
```

Delta Source Query 계약:

```text
lower = committed_watermark - 5m
upper = source_sync_run 시작 시 고정

updated >= lower
updated < upper
ORDER BY updated ASC, id ASC
```

Jira `updated`는 후보 탐색 신호일 뿐 실제 semantic change는 `semantic_v2 source_hash`로 판정합니다.

Loop B Claim Gate:

```text
last_source_committed_run_id IS NOT NULL
AND last_source_committed_run_id = last_observed_source_run_id
AND work_status IN ('pending','failed')
AND superseded_by_work_item_id IS NULL
```

## 9. Operational State foundation 검증

새 State 테스트가 포함된 CI에서 구현 테스트는 모두 통과했습니다.

```text
새 DB 초기화 / 기존 Collector API       PASS
known legacy → explicit migration       PASS
SQLite backup / legacy row 보존         PASS
migration rerun no-op                    PASS
unknown schema fail-closed               PASS
Watermark + Ready Gate rollback          PASS
running 구버전 supersede / stale guard   PASS
A → B → A artifact reuse                 PASS
```

문서 Gate는 같은 시점에 문서 용어/Registry 변경과 충돌해 별도 동기화 중이며, 구현 완료 조건상 최종 전체 CI PASS까지 확인합니다.

## 10. 운영 최신성 / Backpressure

```text
Source Lag
→ Jira Source를 어디까지 안전하게 읽었나?

Publish Lag
→ Source Head와 Published Head가 얼마나 차이나나?

Latest Backlog Depth
→ 실제로 처리해야 하는 최신 Work Item이 몇 개인가?

Oldest Latest Pending Age
→ 가장 오래 기다리는 최신 Work는 얼마나 오래됐나?

Supersede Ratio
→ 중간 Source Version이 얼마나 자주 최신 Version에 밀리는가?
```

추가로 Processing Throughput, OpenCode latency/error를 시간대별로 측정합니다.

## 11. MVP 핵심 숫자

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

## 12. M7 Knowledge DB SQLite — DONE / PASS

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

## 13. M8 BGE-M3 — DONE / PASS

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

## 14. M9 FAISS — DONE / PASS

```text
Index       IndexFlatIP
Metric      cosine = L2 normalize + inner product
Query       raw_query_v1 = query.strip()
Top-k       3
Threshold   none
Reranker    none
Mapping     FAISS position → emb_ → ki_
```

## 15. M10 Evidence + MCP — DONE / PASS

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

## 16. M11 OpenCode Integration — DONE / PASS

```text
M11-01 .env service configuration                PASS
M11-02 local stdio OpenCode 연결                 PASS
M11-03 OpenCode Tool 2개 discovery              PASS
M11-04 명시적 MCP Tool call                     PASS
M11-05 일반 업무 질문에서 자동 Tool selection   PASS
M11-06 description/comment Evidence 추적         PASS
```

[M11 Completion](docs/status/M11_COMPLETION.html)

서비스 설정 키는 `.env.example`과 M11 문서에서 관리합니다:
`JIRA_KNOWLEDGE_DB_PATH`, `JIRA_RETRIEVAL_ARTIFACT_DIR`, `BGE_M3_ENDPOINT`.

## 17. Central Remote MCP

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

## 18. 다음 구현 순서

```text
Operational State foundation               IMPLEMENTED / UNIT PASS
Documentation Shell / Registry final Gate   CURRENT
Loop A Delta Source Sync integration        NEXT
Loop B latest-only Single Worker            LATER
Knowledge / Embedding / Atomic Publish      LATER
Structured Logging / Monitoring             LATER
Central Remote MCP Operations               LATER
```

Loop A에서는 기존 Collector를 `project_id Registry + committed Watermark + fixed upper + stable cursor + semantic_v2 + commit_source_project()`에 연결합니다.

Multi-worker claim/lease와 외부 MQ, 정확한 cadence/concurrency는 실제 Single Worker 처리량을 측정한 뒤 결정합니다.

## 19. 주요 문서

- [Documentation Hub](docs/index.html)
- [Operational State 개정 3 구현 보고서](docs/status/OPERATIONAL_STATE_REV3_FOUNDATION_IMPLEMENTATION.html)
- [현재 운영 Sync 규칙](docs/architecture/jira_sync_contract.html)
- [D10 Latest-Only](docs/architecture/jira_sync_contract_decision10_latest_only_processing.html)
- [현재 Operational State 설계](docs/architecture/jira_sync_state_schema_contract.html)
- [2-Loop Operational Architecture](docs/architecture/jira_operational_two_loop_architecture.html)
- [Full Pipeline](docs/architecture/jira_knowledge_pipeline_full_explained.html)
- [Operational Service Phase](docs/architecture/jira_knowledge_operational_service_phase.html)
- [MCP Service Target](docs/architecture/jira_knowledge_mcp_service_target.html)
- [Current Status](docs/status/jira_knowledge_db_current_status.html)
- [Latest Handoff](docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html)
- [Pipeline Overview](docs/PIPELINE_OVERVIEW.html)
- [Relationship Map](docs/architecture/jira_data_relationship_map.html)
- [버전 표기 가이드](docs/VERSION_TERMINOLOGY_GUIDE.html)
- [Documentation Policy](docs/DOCUMENTATION_POLICY.html)

## 20. 로컬 MVP Artifact

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
