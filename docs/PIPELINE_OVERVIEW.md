# Jira Knowledge Pipeline 전체 아키텍처 · Markdown Companion

기준일: 2026-08-28  
현재 단계: **M0~M11 DONE / PASS · Two-Loop Operational Architecture FROZEN**

> 사람용 공식 문서는 [`docs/PIPELINE_OVERVIEW.html`](PIPELINE_OVERVIEW.html)과 [Documentation Hub](index.html)를 기준으로 합니다. 이 Markdown은 검색/개발 편의용 companion입니다.

## 현재 전체 구조

```text
Functional MVP · DONE / PASS
Jira REST API
→ RAW / ANALYSIS
→ Knowledge Input
→ Knowledge / Review
→ Versioned SQLite
→ BGE-M3
→ FAISS
→ Evidence / MCP
→ OpenCode

Operational Service · TWO-LOOP

Loop A · SOURCE SYNC
source_sync_run
→ Project Discovery
→ Initial / Delta / Catch-up
→ Jira Download
→ RAW / ANALYSIS / Knowledge Input
→ semantic_v2
→ NEW / CHANGED / UNCHANGED
→ sync_issue_change durable backlog
→ SOURCE_COMMITTED / Watermark

Loop B · KNOWLEDGE PROCESSING / PUBLISH
processing_run
→ backlog Work Item
→ OpenCode Knowledge
→ Review / Evidence
→ Knowledge DB
→ BGE-M3 / FAISS staging
→ Atomic Publish
→ PUBLISHED

Always-on Retrieval
Published Corpus → MCP → Team OpenCode
```

## 현재 Contract

```text
Sync Contract v2
D1 Project별 committed Watermark
D2 5분 Overlap + fixed upper + stable order
D3 NEW / CHANGED / UNCHANGED
D4 source_hash semantic_v2
D5 Loop별 Checkpoint / Resume
D6 Project Registry / Knowledge Retention
D7 SOURCE_COMMITTED ≠ PUBLISHED
D8 Run status = Loop-local
D9 Two-Loop Operational Architecture

Operational State Schema v2
source_sync_run
project_state
source_project_run
sync_issue_change
processing_run
```

State Schema v1의 단일 `sync_run` 구조는 실제 배포 전에 superseded 되었으며 구현 기준이 아닙니다.

## 핵심 불변 원칙

- RAW가 사실의 최종 기준이다.
- History Storage와 Active Retrieval을 분리한다.
- `jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_` identity를 유지한다.
- `FAISS position ≠ emb_ ≠ ki_`다.
- Jira Source Lifecycle ≠ Knowledge Lifecycle.
- SOURCE_COMMITTED ≠ PUBLISHED.
- Source Loop와 Processing Loop는 서로 기다리지 않는다.
- 새 Publish 전까지 last-known-good Published Knowledge를 계속 제공한다.
- 운영 상태는 Source Lag / Publish Lag / Backlog / Oldest Pending Age로 본다.

## MVP 핵심 숫자

```text
Issue                         30
Knowledge Item               285
M5 Raw Evidence Ref          503
M7 Canonical Evidence Row    502
Review Attempt                37
M8 Validated Embedding       285
Embedding dimension         1024
M9 FAISS vector_count        285
```

## 다음 결정

**Intermediate Version supersede policy**

```text
Source Loop
V2 → V3 → V4

Processing Loop가 아직 V2 미시작

A. V2/V3/V4 모두 처리
B. Source Version은 모두 보존하되 미시작 V2/V3 Work를 supersede하고 V4 처리
```

이 정책은 아직 Freeze하지 않았습니다.

그 다음 구현 순서:

```text
State Schema v2 explicit Migration
→ StateStore v2
→ Loop A Delta Source Sync
→ durable backlog producer
→ Loop B Single Worker
→ Knowledge / Embedding / Publish
→ lag/backlog monitoring
→ Central Remote MCP Operations
```
