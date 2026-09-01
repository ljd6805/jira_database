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
StateStore foundation                   IMPLEMENTED · CI PASS
Legacy Migration capability             IMPLEMENTED · compatibility only
semantic_v2 source hash                 IMPLEMENTED · CI PASS
Loop A Delta Source Sync                IMPLEMENTED · REAL PASS
Loop B Knowledge Automation             IMPLEMENTED · REAL PASS
per-Work Knowledge DB materialization   IMPLEMENTED · REAL PASS
Incremental BGE-M3                      IMPLEMENTED · REAL PASS
G4 WAL-safe Atomic Publish              IMPLEMENTED · CI PASS

Bootstrap Policy
Smoke                                  data_smoke/ Fresh DB
Formal Real Test                       clean data/ Fresh Bootstrap
Legacy DB Migration                    NOT PLANNED for official test

Real Environment Gates
G1 Real Loop A                         PASS
G2 Real Internal OpenCode              PASS
G3 Real Incremental BGE-M3             PASS · BAAI/bge-m3 · 1024-d
G4 Real Atomic Publish                 NEXT
Real Skill-load verification           PENDING
Continuous Scheduling                  NOT IMPLEMENTED
```

현재 최상위 기준 문서:

- [Current Status](docs/status/jira_knowledge_db_current_status.html)
- [G3 Real BGE-M3 검증 기록](docs/status/G3_REAL_BGE_M3_VALIDATION.html)
- [G4 Atomic Publish 쉬운 설계](docs/architecture/G4_ATOMIC_PUBLISH_PROTOCOL.html)
- [Fresh Bootstrap / Smoke Policy](docs/architecture/jira_operational_fresh_bootstrap_smoke_policy.html)
- [OpenCode 자동화 쉬운 가이드](docs/architecture/jira_loop_b_opencode_automation_easy_guide.html)
- [Incremental Embedding 구현 보고서](docs/status/OPERATIONAL_INCREMENTAL_EMBEDDING_IMPLEMENTATION.html)
- [Loop B Knowledge Automation 구현 보고서](docs/status/LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html)
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
Loop A · SOURCE SYNC                         IMPLEMENTED / REAL PASS
source_sync_run
→ Project Discovery
→ Initial / Delta / Catch-up
→ committed_watermark - 5m
→ RAW / per-Issue ANALYSIS / Knowledge Input
→ semantic_v2 source_hash
→ NEW / CHANGED / UNCHANGED
→ 모든 Source Version 보존
→ NEW/CHANGED durable sync_issue_change
→ SOURCE_COMMITTED
→ committed_watermark + Source Ready
→ 같은 jira_id의 이전 미완료 Work superseded

              ↓ latest-only durable backlog

Loop B · KNOWLEDGE AUTOMATION                IMPLEMENTED / REAL PASS
processing_run
→ latest + source-ready Work Item claim
→ OpenCode jira-knowledge-orchestrator
→ jira-knowledge-worker
→ jira-knowledge-extraction Skill REQUIRED
→ Python Validator + jira-knowledge-reviewer
→ final Reviewer PASS
→ latestness re-check
→ stale이면 canonical 승격 중단
→ 최신이면 canonical Knowledge/Review atomic promotion
→ iv_ / kg_ State checkpoint
→ knowledge_status = completed

Loop B · KNOWLEDGE DB                        IMPLEMENTED / REAL PASS
→ per-Work Issue Version / Generation / Attempt
→ Knowledge Item / Evidence / Review
→ candidate + accepted_attempt_id
→ active 전환은 Publish까지 보류

Loop B · INCREMENTAL EMBEDDING               IMPLEMENTED / REAL PASS
→ candidate Generation accepted Knowledge Item corpus
→ BAAI/bge-m3 실제 호출
→ latestness re-check
→ Work별 corpus.jsonl / embeddings.jsonl atomic staging
→ 1024-d vector 검증
→ embedding_status = completed
→ work_status = pending

Loop B · G4 RETRIEVAL / PUBLISH              IMPLEMENTED / CI PASS
→ target + 현재 active Generation full snapshot
→ immutable FAISS / mapping / manifest bundle staging
→ Generation-set integrity Gate
→ latestness re-check + State WAL write lock
→ Knowledge DB active Generation service-head commit
→ State publish_status/work_status = published
→ crash/race fail-closed + retry convergence

Continuous Scheduling                        NOT IMPLEMENTED

Always-on Retrieval
Published Corpus → FAISS → Evidence/MCP → Team OpenCode
```

두 Loop는 서로 기다리지 않습니다. OpenCode나 BGE-M3가 느려도 Jira Source Sync는 계속되고, 중간 Source Version은 History로 남지만 비싼 AI/Data Plane 처리는 최신 Version만 수행합니다.

## 3. Bootstrap / Smoke Policy

공식 시작 경로는 legacy DB Migration이 아니라 **Fresh Bootstrap**입니다.

```text
Smoke
→ config/settings.smoke.yaml
→ storage.data_root = ./data_smoke
→ 새 State DB / RAW / ANALYSIS / Knowledge Input
→ production/pilot data와 완전 격리
→ Migration 없음

Formal Real Test
→ 기존 파일럿 DB/index는 삭제 또는 별도 보관
→ clean ./data
→ 새 State DB / Knowledge DB
→ Migration 없음
→ Full Initial Ingest
→ Project별 Watermark 생성
→ 이후 Delta Sync

Legacy Compatibility
→ 기존 collector.db를 꼭 이어써야 할 때만
→ tools/migrate_state_v3.py 사용
```

파일럿 DB를 제거해도 M0~M11 HTML 완료 문서, Real-run 기록, Architecture/Decision 이력은 보존합니다.

상세: [Fresh Bootstrap / Smoke Policy](docs/architecture/jira_operational_fresh_bootstrap_smoke_policy.html)

## 4. Loop A Delta Source Sync — IMPLEMENTED

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

### Real Loop A Smoke

```bash
python tools/run_source_sync.py \
  --local-config config/settings.smoke.yaml \
  --max-issues-per-project 1
```

주의: `--max-issues-per-project 1`은 **접근 가능한 모든 Project에서 최대 1건씩**입니다. Smoke는 `data_smoke/`에 격리되므로 production Watermark를 오염시키지 않습니다. 생성된 Source-ready Work 중 한 건을 Real OpenCode Smoke에 사용합니다.

### 정식 Fresh Initial Ingest

깨끗한 `data/`에서 제한 옵션 없이 실행합니다.

```bash
python tools/run_source_sync.py
```

`--max-issues-per-project`는 정식 Initial Ingest에서는 사용하지 않습니다.

Legacy DB를 반드시 재사용할 때만:

```bash
python tools/migrate_state_v3.py --database data/state/collector.db
```

상세: [Loop A Implementation](docs/status/LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html)

## 5. Loop B Knowledge Automation — IMPLEMENTED

`sync_issue_change`에서 Source-ready + latest Work만 Single Worker로 Knowledge checkpoint까지 처리합니다.

```text
src/jira_collector/knowledge_processing.py
→ latest/source-ready Knowledge backlog 조회
→ claim_work_item
→ knowledge_status = running
→ opencode run --agent jira-knowledge-orchestrator
→ Work별 staging 경로에 Knowledge/Review 생성
→ jira-knowledge-worker
→ jira-knowledge-extraction Skill REQUIRED
→ deterministic Knowledge validation
→ jira-knowledge-reviewer
→ final Review PASS 확인
→ OpenCode 응답 후 latestness 재확인
→ stale이면 canonical promotion 중단
→ 최신이면 canonical Knowledge/Review 승격
→ iv_ / kg_ 계산
→ knowledge_status = completed
→ 다음 stage를 위해 work_status = pending
```

OpenCode stdout 문구가 아니라 **실제 JSON artifact + Python Validator + Reviewer PASS + latestness**가 성공 기준입니다.

실행:

```bash
python tools/run_knowledge_worker.py \
  --model-profile internal-opencode-knowledge-v1 \
  --limit 1
```

현재 정확한 상태:

```text
Knowledge Automation code          IMPLEMENTED / CI PASS
Real Internal OpenCode Run         PASS
Actual Skill-load verification     PENDING
Continuous Scheduler/Daemon        NOT IMPLEMENTED
```

상세:
- [Loop B Knowledge Automation](docs/status/LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html)
- [OpenCode 자동화 쉬운 가이드](docs/architecture/jira_loop_b_opencode_automation_easy_guide.html)

## 6. Operational Knowledge DB + Incremental Embedding — REAL PASS

Knowledge Worker가 만든 Work 하나를 기존 M7 full-run loader에 억지로 넣지 않고 전용 incremental materializer로 적재합니다.

```text
per-Work Knowledge DB
→ Issue Version / Generation / Attempt
→ Knowledge Item / Evidence / Review
→ candidate + accepted_attempt_id
→ latestness 확인
→ active 전환은 Publish 단계까지 보류

Incremental Embedding
→ candidate Generation의 accepted Item만 corpus 생성
→ BAAI/bge-m3 실제 호출
→ API 응답 후 latestness 재확인
→ corpus/embedding artifact atomic staging
→ 1024-d vector / Generation identity 사후검증
→ embedding_status = completed
→ Publish가 이어받도록 work_status = pending
```

실제 G3 결과:

```text
G3_REAL_BGE_M3 = PASS
processing_run_id = pr_6237ead6ee92424ba2fb27a57f6605a9
selected_count = 1
embedding_completed_count = 1
failed_count = 0
embedding_backlog = 1 → 0
model = BAAI/bge-m3
dimension = 1024
generation_state = candidate
work_status = pending
publish_status = pending
```

실행:

```bash
python tools/run_embedding_worker.py \
  --knowledge-db data/knowledge_db/your.sqlite3 \
  --artifact-root data/embedding/operational \
  --limit 1
```

`run_embedding_worker.py`는 Jira 인증을 다시 요구하지 않습니다. State DB, Knowledge DB, BGE-M3 설정만 소비합니다.

상세:
- [G3 Real BGE-M3 Validation](docs/status/G3_REAL_BGE_M3_VALIDATION.html)
- [Incremental Embedding Implementation](docs/status/OPERATIONAL_INCREMENTAL_EMBEDDING_IMPLEMENTATION.html)

## 7. G4 Atomic Publish — IMPLEMENTED / CI PASS

State 개정 3은 WAL을 사용하므로 Knowledge DB와 State DB를 SQLite `ATTACH`로 한 cross-file transaction에 묶는 초기 설계는 폐기했습니다. State WAL은 그대로 유지합니다.

```text
publish-ready latest Work
→ target + current active Generation full snapshot 계산
→ immutable Retrieval bundle staging
→ source embedding / FAISS / mapping / manifest 검증
→ Generation 집합 검증
→ latestness re-check
→ State BEGIN IMMEDIATE
→ Knowledge DB transaction
   old active(target Jira) → historical
   target candidate        → active      ← service-facing commit point
→ State
   work_status             → published
   publish_status          → published
   processing_run          → completed
```

Active Retrieval은 별도 mutable pointer가 아니라 **Knowledge DB의 active accepted Generation 집합과 정확히 같은 Generation 집합을 가진 검증된 immutable bundle**로 결정합니다.

실행:

```bash
python tools/run_publish_worker.py \
  --state-db data/state/collector.db \
  --knowledge-db data/knowledge_db/your.sqlite3 \
  --embedding-root data/embedding/operational \
  --retrieval-root data/retrieval/operational
```

G4 CI는 Initial Publish, full snapshot 교체, State WAL 유지, Knowledge commit 후 State checkpoint 실패 복구, staging 중 동시 Publish race의 fail-closed/retry를 검증합니다.

상세: [G4 Atomic Publish Protocol](docs/architecture/G4_ATOMIC_PUBLISH_PROTOCOL.html)

## 8. semantic_v2 — IMPLEMENTED

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

## 9. Latest-Only Processing

```text
Source History
상태 A → B → C → D
모두 보존

Knowledge / Data Plane
B pending/running → superseded 가능
C pending         → superseded
D latest          → Knowledge → DB candidate → Embedding → Publish
```

구버전 Work가 이미 OpenCode/BGE-M3 처리 중이면 외부 호출을 강제 취소하지 않습니다. 응답 후 최신성을 다시 검사하고 stale이면 다음 canonical/Publish 경로를 중단합니다.

A→B→A처럼 과거 semantic state가 다시 최신이 되면 기존 Work identity와 완성 artifact를 재사용할 수 있습니다.

구조화 로그:

```text
work_item_superseded
processing_skip_superseded
stale_inflight_detected
latest_processing_started
work_item_reactivated
```

로그에는 Jira 원문/댓글 본문을 넣지 않고 identity/run/stage/reason/timestamp만 기록합니다.

## 10. Operational State foundation — IMPLEMENTED

```text
src/jira_collector/state_schema.py
→ current Schema 개정 3 초기화
→ WAL journal mode
→ legacy schema inspection / fingerprint
→ explicit migration / backup / integrity
→ unknown schema fail-closed

src/jira_collector/state_store.py
→ 기존 Collector State API 유지
→ Loop A Source state
→ Loop B Processing state
→ Source Ready / supersede / stale guard

tools/migrate_state_v3.py
→ legacy DB를 꼭 재사용할 때만 사용하는 compatibility tool
```

새/빈 DB는 현재 Operational State 설계로 바로 초기화됩니다. 공식 Real Test는 이 Fresh Bootstrap 경로를 사용합니다.

기존 known legacy `collector.db`를 꼭 재사용하는 경우에만 일반 StateStore open이 `StateMigrationRequiredError`로 차단되고 explicit migration을 요구합니다.

## 11. 안전 경계

Loop A T3:

```text
BEGIN
source_project_run.source_status = source_committed
project_state.committed_watermark = upper
현재 Work Item = Source Ready
이전 pending/failed/running Work = superseded
COMMIT
```

Loop B Knowledge / Embedding:

```text
actual staging artifact 먼저
→ validator/latestness 확인
→ State completed 나중
```

G4 Publish:

```text
immutable Retrieval bundle 먼저
→ integrity + Generation-set Gate
→ latestness re-check
→ Knowledge active service-head commit
→ State published checkpoint
```

## 12. Same-Run Resume

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

## 13. Identity

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

## 14. 현재 Operational State DB 구조

```text
STATE_SCHEMA_VERSION = 3
PRAGMA user_version = 3
PRAGMA journal_mode = WAL

Operational Domain Tables
source_sync_run
project_state
source_project_run
sync_issue_change
processing_run

Technical Metadata
state_schema_migration
```

Legacy Migration을 사용하는 경우 기존 `collection_runs`, `project_runs`, `issue_checkpoints`, `artifacts`는 삭제하거나 의미를 바꾸지 않습니다.

## 15. 현재 운영 Sync 규칙

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

## 16. 구현 검증 / Real Environment Gate

```text
State schema / migration compatibility tests             PASS
Initial Ingest / Jira fixed upper                       PASS
Watermark - 5m / stable Delta JQL                       PASS
timestamp-only → UNCHANGED                              PASS
meaningful change → CHANGED + supersede                 PASS
Discovery failure isolation / same-run Resume           PASS
semantic_v2 package-scope metadata stability            PASS
Loop B latest + Source-ready selection                  PASS
Knowledge staging → canonical promotion                 PASS
Reviewer non-PASS 차단                                  PASS
per-Work Knowledge DB candidate materialization         PASS
Incremental Embedding success / retry                   PASS
Embedding Processing Run claim/release                  PASS
G4 immutable full Retrieval snapshot                    PASS
G4 State WAL preservation                              PASS
G4 checkpoint failure retry convergence                 PASS
G4 concurrent Publish snapshot race fail-closed         PASS
Documentation / pytest                                  PASS

G1 Real Loop A Smoke                                    PASS
G2 Real Internal OpenCode                               PASS
G3 Real Incremental BGE-M3                              PASS
G4 Real Atomic Publish                                  NEXT
Actual Skill-load trace                                 PENDING
Legacy Migration for official test                      NOT PLANNED
Continuous Scheduling                                   NOT IMPLEMENTED
```

## 17. 운영 최신성 / Backpressure

```text
Source Lag
Publish Lag
Latest Backlog Depth
Oldest Latest Pending Age
Supersede Ratio
OpenCode / BGE-M3 Latency / Error / Throughput
```

## 18. MVP 핵심 숫자

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

## 19. M7 Knowledge DB SQLite — DONE / PASS

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

## 20. M8 BGE-M3 — DONE / PASS

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

M8의 위 수치는 기존 Functional MVP Real Run 결과입니다. 운영 Incremental G3도 별도로 실제 BAAI/bge-m3 1024-d PASS를 확인했습니다.

## 21. M9 FAISS — DONE / PASS

```text
Index       IndexFlatIP
Metric      cosine = L2 normalize + inner product
Query       raw_query_v1 = query.strip()
Top-k       3
Threshold   none
Reranker    none
Mapping     FAISS position → emb_ → ki_
```

## 22. M10 Evidence + MCP — DONE / PASS

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

## 23. M11 OpenCode Integration — DONE / PASS

```text
M11-01 .env service configuration                PASS
M11-02 local stdio OpenCode 연결                 PASS
M11-03 OpenCode Tool 2개 discovery              PASS
M11-04 명시적 MCP Tool call                     PASS
M11-05 일반 업무 질문에서 자동 Tool selection   PASS
M11-06 description/comment Evidence 추적         PASS
```

[M11 Completion](docs/status/M11_COMPLETION.html)

서비스 설정 키는 `.env.example`에서 관리합니다.

```text
JIRA_KNOWLEDGE_DB_PATH
JIRA_RETRIEVAL_ARTIFACT_ROOT   ← G4 운영 권장, MCP 시작 시 active bundle 자동 선택
JIRA_RETRIEVAL_ARTIFACT_DIR    ← 기존 특정 M9 artifact 직접 지정 방식
BGE_M3_ENDPOINT
```

ROOT와 DIR을 함께 설정하면 ROOT가 우선합니다. 현재 G4는 요청 중 hot reload를 하지 않고 MCP 시작 시 coherent bundle 하나를 pin합니다.

## 24. Central Remote MCP

Central MCP는 두 Loop를 실행하는 엔진이 아닙니다.

```text
Loop A / Loop B
→ 새 Published Corpus를 준비/전환

Central MCP
→ 현재 Published Corpus 읽기
→ FAISS / Evidence Resolver
→ 팀원 OpenCode에 Tool 제공
```

새 Processing/Publish가 실패해도 matching active Retrieval head를 검증해서 읽습니다.

## 25. 다음 단계

```text
REAL GATE NEXT
보존한 data_smoke
→ G4 Atomic Publish 실제 실행
→ State published 확인
→ target Generation active 확인
→ active Retrieval bundle Generation set 확인
→ FAISS integrity / 1024 dimension 확인
→ G4 REAL PASS 확정

PENDING EVIDENCE
Actual Skill-load trace 보존

LATER
Continuous Scheduling / Monitoring
MCP safe reload / Remote MCP Operations / Team Pilot
```

G1/G2/G3의 실제 artifact와 checkpoint를 보존하기 위해 G4 검증 전 `data_smoke`를 초기화하지 않습니다.

## 26. 주요 문서

- [Documentation Hub](docs/index.html)
- [Current Status](docs/status/jira_knowledge_db_current_status.html)
- [G3 Real BGE-M3 Validation](docs/status/G3_REAL_BGE_M3_VALIDATION.html)
- [G4 Atomic Publish Protocol](docs/architecture/G4_ATOMIC_PUBLISH_PROTOCOL.html)
- [Fresh Bootstrap / Smoke Policy](docs/architecture/jira_operational_fresh_bootstrap_smoke_policy.html)
- [OpenCode 자동화 쉬운 가이드](docs/architecture/jira_loop_b_opencode_automation_easy_guide.html)
- [Incremental Embedding](docs/status/OPERATIONAL_INCREMENTAL_EMBEDDING_IMPLEMENTATION.html)
- [Loop B Knowledge Automation](docs/status/LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html)
- [Loop A Delta Source Sync](docs/status/LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html)
- [Operational State 구현 보고서](docs/status/OPERATIONAL_STATE_REV3_FOUNDATION_IMPLEMENTATION.html)
- [현재 운영 Sync 규칙](docs/architecture/jira_sync_contract.html)
- [D10 Latest-Only](docs/architecture/jira_sync_contract_decision10_latest_only_processing.html)
- [현재 Operational State 설계](docs/architecture/jira_sync_state_schema_contract.html)
- [2-Loop Operational Architecture](docs/architecture/jira_operational_two_loop_architecture.html)
- [Full Pipeline](docs/architecture/jira_knowledge_pipeline_full_explained.html)
- [Operational Service Phase](docs/architecture/jira_knowledge_operational_service_phase.html)
- [MCP Service Target](docs/architecture/jira_knowledge_mcp_service_target.html)
- [Latest Handoff](docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html)
- [Pipeline Overview](docs/PIPELINE_OVERVIEW.html)
- [Relationship Map](docs/architecture/jira_data_relationship_map.html)
- [버전 표기 가이드](docs/VERSION_TERMINOLOGY_GUIDE.html)
- [Documentation Policy](docs/DOCUMENTATION_POLICY.html)

## 27. 로컬 MVP Artifact

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

`data/`, `data_smoke/`, `.env`, local config, DB는 Git에서 제외합니다. Public repo에는 실제 Jira Issue Key/raw body/사내 endpoint/custom header/token/로컬 절대경로를 기록하지 않습니다.
