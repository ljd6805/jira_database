# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Knowledge 추출/검토 → Versioned SQLite Knowledge DB → BGE-M3 Embedding → FAISS Retrieval → Evidence/MCP → OpenCode 실제 소비자 검증**까지 발전시킨 프로젝트입니다.

> 📚 사람이 읽는 공식 문서는 [Documentation Hub](docs/index.html)에서 시작하세요. Hub가 연결하는 로컬 문서는 HTML입니다.

현재 기준:

```text
M0~M11 Functional MVP                   DONE / PASS
Two-Loop Operational Architecture       FROZEN
D10 Latest-Only Processing              FIXED
현재 운영 Sync 규칙 · 개정 3            FROZEN
현재 Operational State 설계 · 개정 3    FROZEN
State Migration / StateStore foundation IMPLEMENTED · CI PASS
semantic_v2 source hash                 IMPLEMENTED · CI PASS
Loop A Delta Source Sync                IMPLEMENTED · CI PASS
Loop B Latest-Only Knowledge Worker     IMPLEMENTED · CI PASS
실제 local collector.db Migration        NOT RUN YET
실제 사내 Jira Loop A Run               NOT RUN YET
실제 사내 OpenCode Knowledge Run        NOT RUN YET
Operational Data Plane Integration      NEXT
```

현재 최상위 기준 문서:

- [Loop B Latest-Only Knowledge Worker 구현 보고서](docs/status/LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html)
- [Loop A Delta Source Sync 구현 보고서](docs/status/LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html)
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
Loop A · SOURCE SYNC                         IMPLEMENTED / CI PASS
source_sync_run
→ Jira serverInfo / fixed upper
→ Project Discovery
→ Initial / Delta / Catch-up
→ committed_watermark - 5m
→ Jira Download
→ RAW / per-Issue ANALYSIS / Knowledge Input
→ semantic_v2 source_hash
→ NEW / CHANGED / UNCHANGED
→ 모든 Source Version 보존
→ NEW/CHANGED durable sync_issue_change
→ SOURCE_COMMITTED
→ committed_watermark + Source Ready
→ 같은 jira_id의 이전 미완료 Work superseded

              ↓ latest-only durable backlog

Loop B · KNOWLEDGE STAGE                     IMPLEMENTED / CI PASS
processing_run
→ latest + source-ready Work Item claim
→ OpenCode jira-knowledge-orchestrator
→ staging Knowledge / Review
→ Python Validator + final Reviewer PASS
→ latestness re-check
→ stale이면 canonical 승격 중단
→ 최신이면 canonical Knowledge/Review atomic promotion
→ iv_ / kg_ State checkpoint
→ knowledge_status = completed

Loop B · DATA PLANE                          NEXT
→ per-Work Knowledge DB materialization
→ BGE-M3 incremental Embedding
→ FAISS staging / mapping
→ latestness re-check
→ Atomic Publish
→ PUBLISHED

Always-on Retrieval
Published Corpus → FAISS → Evidence/MCP → Team OpenCode
```

두 Loop는 서로 기다리지 않습니다. OpenCode가 느려도 Jira Source Sync는 계속되고, 중간 Source Version은 History로 남지만 비싼 AI 처리는 최신 Version만 수행합니다.

## 3. Loop A Delta Source Sync — IMPLEMENTED

운영용 Source Sync는 기존 파일럿 `collect/resume` 경로와 분리해 추가했습니다.

```text
src/jira_collector/source_sync.py
→ Jira server clock fixed upper
→ project_id authoritative Discovery
→ initial / delta / catch-up / unavailable
→ lower = committed_watermark - 5m
→ updated >= lower AND updated < upper
→ ORDER BY updated ASC, id ASC
→ RAW detail/comments durable
→ Issue / Comment / Structure Parser 재사용
→ per-Issue ANALYSIS
→ Knowledge Input
→ semantic_v2
→ NEW / CHANGED / UNCHANGED
→ candidate cursor checkpoint
→ Project Source Commit
→ same-run Resume
```

실행:

```bash
python tools/migrate_state_v3.py --database data/state/collector.db
python tools/run_source_sync.py
python tools/run_source_sync.py --resume-source-run-id sr_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# 테스트/파일럿 전용
python tools/run_source_sync.py --max-issues-per-project 30
```

상세: [Loop A Implementation](docs/status/LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html)

## 4. Loop B Latest-Only Knowledge Worker — IMPLEMENTED

`sync_issue_change`에서 Source-ready + latest Work만 Single Worker로 Knowledge checkpoint까지 처리합니다.

```text
src/jira_collector/knowledge_processing.py
→ latest/source-ready Knowledge backlog 조회
→ claim_work_item
→ knowledge_status = running
→ opencode run --agent jira-knowledge-orchestrator
→ Work별 staging 경로에 Knowledge/Review 생성
→ deterministic Knowledge validation
→ final Review PASS 확인
→ OpenCode 응답 후 latestness 재확인
→ stale이면 canonical promotion 중단
→ 최신이면 canonical Knowledge/Review 승격
→ iv_ / kg_ 계산
→ knowledge_status = completed
→ Embedding/Publish가 남아 있으므로 work_status = pending
```

OpenCode stdout 문구가 아니라 **실제 JSON artifact + Python Validator + Reviewer PASS + latestness**가 성공 기준입니다.

실행:

```bash
python tools/run_knowledge_worker.py \
  --model-profile internal-opencode-knowledge-v1

python tools/run_knowledge_worker.py \
  --model-profile internal-opencode-knowledge-v1 \
  --opencode-attach http://localhost:4096
```

`model_profile`은 Knowledge Generation identity에 포함되는 운영 계약 이름이므로 필수입니다.

상세: [Loop B Knowledge Worker](docs/status/LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html)

## 5. semantic_v2 — IMPLEMENTED

Jira `updated`는 Delta candidate trigger이고 semantic identity가 아닙니다.

```text
Package에는 보존하지만 source_hash에서 제외
- issue.updated_at
- comment.updated_at
- source_path
- source_page
- other_package_available

source_hash에 유지
- 실제 Issue / Comment 내용
- created_at
- author / status / 업무 context
- Attachment metadata
- Relationship 의미
- Custom Field 의미 값
```

따라서 timestamp만 바뀌거나 이번 run의 package 범위만 달라져도 UNCHANGED이고, 실제 업무 의미가 바뀌어야 CHANGED가 됩니다.

## 6. Latest-Only Processing

```text
Source History
상태 A → B → C → D
모두 보존

Knowledge Processing
A already Published
B pending/running → superseded 가능
C pending         → superseded
D latest          → process
```

구버전 Work가 이미 OpenCode 처리 중이면 외부 호출을 강제 취소하지 않습니다. 응답 후 최신성을 다시 검사하고 stale이면 canonical Knowledge 승격, Embedding, Publish를 중단합니다.

A→B→A처럼 미완료 stale-running A가 다시 최신이 되면 retryable checkpoint로 처리합니다. 이미 완성된 artifact가 있으면 기존 재사용 정책을 유지합니다.

구조화 로그:

```text
work_item_superseded
processing_skip_superseded
stale_inflight_detected
latest_processing_started
work_item_reactivated
```

로그에는 Jira 원문/댓글 본문을 넣지 않고 identity/run/stage/reason/timestamp만 기록합니다.

## 7. Operational State foundation — IMPLEMENTED

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
```

새/빈 DB는 현재 Operational State 설계로 초기화하지만, 기존 known legacy `collector.db`는 일반 실행에서 자동 변경하지 않습니다.

```text
legacy collector.db
→ StateStore open
→ StateMigrationRequiredError
→ explicit migration 필요
```

> 실제 사용 중인 `data/state/collector.db`가 Migration됐다고 간주하지 않습니다. 실제 환경에서 writer를 중지하고 backup 결과와 기존 Resume 동작을 확인해야 합니다.

## 8. 안전 경계

Loop A T3:

```text
BEGIN
source_project_run.source_status = source_committed
project_state.committed_watermark = upper
현재 Work Item = Source Ready
이전 pending/failed/running Work = superseded
COMMIT
```

Loop B Knowledge:

```text
staging artifact 먼저
→ Validator/Reviewer
→ latestness re-check
→ canonical artifact durable
→ State knowledge_status=completed 나중
```

Publish 단계에서도 actual active switch가 State `published`보다 먼저여야 합니다.

## 9. Same-Run Resume

```text
Source Run fixed upper = 최초 한 번 결정
candidate A 완료 → cursor durable
candidate B 실패 → Watermark 유지

resume(source_run_id)
→ 같은 fixed upper
→ 완료 Discovery snapshot 재사용
→ cursor 이전 candidate skip
→ B부터 재시도
→ Project 전체 성공 후 Watermark 전진
```

## 10. Identity

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

Loop B Knowledge Generation은 `iv_ + Knowledge Contract(knowledge schema / skill / runtime / model_profile)`로 `kg_`를 결정합니다.

## 11. 현재 Operational State DB 구조

```text
STATE_SCHEMA_VERSION = 3
PRAGMA user_version = 3

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

## 12. 현재 운영 Sync 규칙

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

## 13. 구현 검증

```text
State Migration / backup / rollback / fail-closed       PASS
Initial Ingest / Jira fixed upper                       PASS
Watermark - 5m / stable Delta JQL                       PASS
timestamp-only → UNCHANGED                              PASS
meaningful change → CHANGED + supersede                 PASS
Discovery failure isolation / same-run Resume           PASS
semantic_v2 package-scope metadata stability            PASS
Loop B latest + Source-ready selection                  PASS
Knowledge staging → canonical promotion                 PASS
OpenCode 중 newer Source → stale result 차단             PASS
OpenCode failure → retryable failed state               PASS
Reviewer non-PASS 차단                                  PASS
A→B→A stale-running retry                               PASS
Source/Knowledge runner entrypoints                     PASS
```

아직 Real Environment Gate:

```text
실제 사용 중 collector.db Migration   PENDING
실제 사내 Jira Loop A Run             PENDING
실제 사내 OpenCode Knowledge Run      PENDING
```

## 14. 운영 최신성 / Backpressure

```text
Source Lag
Publish Lag
Latest Backlog Depth
Oldest Latest Pending Age
Supersede Ratio
OpenCode Latency / Error / Throughput
```

## 15. MVP 핵심 숫자

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

## 16. M7 Knowledge DB SQLite — DONE / PASS

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

## 17. M8 BGE-M3 — DONE / PASS

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

## 18. M9 FAISS — DONE / PASS

```text
Index       IndexFlatIP
Metric      cosine = L2 normalize + inner product
Query       raw_query_v1 = query.strip()
Top-k       3
Threshold   none
Reranker    none
Mapping     FAISS position → emb_ → ki_
```

## 19. M10 Evidence + MCP — DONE / PASS

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

## 20. M11 OpenCode Integration — DONE / PASS

```text
M11-01 .env service configuration                PASS
M11-02 local stdio OpenCode 연결                 PASS
M11-03 OpenCode Tool 2개 discovery              PASS
M11-04 명시적 MCP Tool call                     PASS
M11-05 일반 업무 질문에서 자동 Tool selection   PASS
M11-06 description/comment Evidence 추적         PASS
```

[M11 Completion](docs/status/M11_COMPLETION.html)

서비스 설정 키는 `.env.example`과 M11 문서에서 관리합니다: `JIRA_KNOWLEDGE_DB_PATH`, `JIRA_RETRIEVAL_ARTIFACT_DIR`, `BGE_M3_ENDPOINT`.

## 21. Central Remote MCP

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

## 22. 다음 구현 순서

```text
Operational State foundation               IMPLEMENTED / CI PASS
semantic_v2                                 IMPLEMENTED / CI PASS
Loop A Delta Source Sync                    IMPLEMENTED / CI PASS
Loop B latest-only Knowledge Worker         IMPLEMENTED / CI PASS
Operational per-Work Knowledge DB           NEXT
Incremental BGE-M3 / FAISS / Atomic Publish LATER
Monitoring / Remote MCP Operations          LATER
```

다음 구현에서는 기존 M7 full-run loader를 억지로 재사용하지 않고, **현재 Work Item 하나를 Knowledge DB에 incremental materialize하는 전용 경로**를 만든 뒤 Embedding/Publish로 이어갑니다.

Multi-worker claim/lease와 외부 MQ, 정확한 cadence/concurrency는 실제 Single Worker 처리량을 측정한 뒤 결정합니다.

## 23. 주요 문서

- [Documentation Hub](docs/index.html)
- [Loop B Knowledge Worker](docs/status/LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html)
- [Loop A Delta Source Sync](docs/status/LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html)
- [Operational State 구현 보고서](docs/status/OPERATIONAL_STATE_REV3_FOUNDATION_IMPLEMENTATION.html)
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

## 24. 로컬 MVP Artifact

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
