# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-27  
현재 단계: **M0~M11 DONE / PASS = Functional MVP 완료**

> Documentation Hub가 직접 연결하는 문서는 HTML을 기준으로 합니다. 이 Markdown은 검색/로그/개발 편의용 보조 문서입니다.

## 1. 전체 흐름

```text
Functional MVP · DONE
Jira REST API
 → RAW / ANALYSIS                         M0 DONE
 → KNOWLEDGE INPUT                        M1 DONE
 → Knowledge Schema + Skill               M2 DONE
 → Worker → Validator → Reviewer          M3 DONE
 → Real Knowledge Pilot                   M4 DONE
 → Profiling                              M5 DONE
 → Logical Identity / Version             M6 DONE
 → SQLite Materialization                 M7 REAL-RUN PASS
 → BGE-M3 Embedding                       M8 REAL-RUN PASS
 → FAISS + Active Retrieval               M9 REAL-RUN PASS
 → Evidence Builder + MCP                 M10 REAL-RUN PASS
 → OpenCode MCP Consumer Pilot            M11 USER REAL-RUN PASS

Operational Service · NEXT
Project Discovery
→ Delta Issue Sync
→ RAW / Issue Version update
→ changed Knowledge / Evidence only
→ changed Embedding / FAISS only
→ Central Remote MCP
→ scheduling / retry / health / monitoring
```

## 2. 핵심 불변 원칙

- RAW가 사실의 최종 기준이다.
- History Storage와 Active Retrieval을 분리한다.
- `knowledge_generation`과 retry `knowledge_attempt`를 구분한다.
- Identity는 `jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_`를 유지한다.
- `knowledge_attempt = ka_ + attempt_no` 관계를 유지한다.
- `FAISS position ≠ embedding_id(emb_) ≠ knowledge_item_id(ki_)`다.
- MCP는 검색/근거 복원만 담당하고 생성형 LLM은 외부 Agent에 둔다.
- 운영 기본은 **delta-first**다.
- Local stdio는 MVP 검증용이며 Remote MCP는 최종 운영 서비스의 한 구성요소다.

## 3. MVP 핵심 숫자

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

## 4. M9 / M10 / M11

```text
M9 Retrieval
질문 → BGE-M3 → FAISS → Top-3 Knowledge(ki_)

M10 Evidence/MCP
ki_ active/accepted 재검증
→ ke_ Evidence resolve
→ 실제 Jira source
→ Evidence Package
→ MCP 2 tools

M11 OpenCode Consumer Pilot
Tool discovery
→ 명시적 Tool call
→ 일반 업무 질문에서 자동 Tool selection
→ description/comment Evidence 추적
```

FAISS는 Jira 원문을 직접 검색하지 않는다. 실제 원문 근거는 SQLite에서 `ki_ → ke_ → source`로 복원한다.

## 5. M10 실제 Real-run — PASS

```text
tool_count: 2
search_result_count: 3
evidence_count: 6
warning_count: 0
path_leak_count: 0
issue_lookup_ok: true
failure_count: 0
M10_REAL_RUN = PASS
```

## 6. M11 실제 OpenCode 검증 — PASS

```text
M11-01 .env service configuration                PASS
M11-02 local stdio OpenCode 연결                 PASS
M11-03 Tool 2개 discovery                        PASS
M11-04 명시적 Tool call                          PASS
M11-05 일반 업무 질문에서 자동 Tool selection    PASS
M11-06 근거 요청에서 description/comment 추적    PASS

M11 = DONE / PASS
```

공개 문서에는 실제 업무 질문, Issue key, Jira 원문을 기록하지 않는다.

```text
tool_count: 2
tools: get_jira_issue, search_jira_knowledge
M11_STDIO_HANDSHAKE = PASS
```

## 7. M0~M11의 의미

M0~M11은 한 번 수집한 Pilot 데이터를 사용해 전체 기술 경로가 실제로 성립하는지 검증한 **Functional MVP**다.

```text
수집 → Knowledge → SQLite → Embedding → FAISS
→ Evidence/MCP → OpenCode 자동 사용
```

이후 단계에서는 Jira가 계속 변하는 운영 상황을 처리해야 한다.

## 8. 운영 서비스 목표

```text
Jira
 ↓ Project Discovery
신규/기존/접근 상태 확인
 ↓
Delta Issue Sync
 ↓
RAW / Issue Version
 ↓ 변경분만
Knowledge / Evidence
 ↓ 변경분만
Embedding / FAISS
 ↓ 최신 Active corpus
Central Remote MCP / HTTPS
 ↓
팀원 OpenCode
```

### 핵심 네 축

1. 지속적인 Jira 업데이트
2. 신규 Project 자동 discovery 및 변화 반영
3. Knowledge/Embedding/FAISS 증분 갱신
4. 중앙 Remote MCP 서비스

## 9. Production Update 방향

```text
unchanged → reuse
added     → cache/embed → add
changed   → old remove/tombstone → cache/embed → add
removed / no access → 정책 확정 후 active 처리

full rebuild = maintenance / recovery / migration
```

후속 후보:

```text
vector_cache_key = H(embedding_text_hash, embedding_contract_hash)
IndexIDMap2(IndexFlatIP) + stable int64 vector_id
HNSW / IVF benchmark
```

## 10. 아직 Freeze해야 할 운영 정책

- sync cadence / scheduling
- watermark / 안전 overlap 상세 계약
- Jira 삭제와 서비스 계정 권한 상실 구분
- 팀원별 Jira 권한 재현 필요 여부
- 증분 vector/index 원자적 전환
- Remote MCP 인증/TLS/접근 제어
- retry/timeout/concurrency
- sync/MCP health와 운영 모니터링

## 11. 서비스 설정 정책

```text
기본 서비스 설정   .env
OS 환경 변수       .env보다 우선
명시적 test env    .env를 읽지 않음

JIRA_KNOWLEDGE_DB_PATH
JIRA_RETRIEVAL_ARTIFACT_DIR
BGE_M3_ENDPOINT
BGE_M3_API_KEY       optional
BGE_M3_HEADERS_JSON  optional
```

## 12. Current Source of Truth

```text
README.md
docs/index.html
docs/PIPELINE_OVERVIEW.html
docs/status/jira_knowledge_db_current_status.html
docs/status/M11_COMPLETION.html
docs/status/M10_COMPLETION.html
docs/architecture/jira_knowledge_operational_service_phase.html
docs/architecture/jira_knowledge_mcp_service_target.html
docs/architecture/jira_data_relationship_map.*
```

다음 Milestone 번호는 아직 고정하지 않는다. 먼저 **Continuous Jira Knowledge Service**를 어떤 Milestone들로 나눌지와 각 Completion Gate를 합의한다.
