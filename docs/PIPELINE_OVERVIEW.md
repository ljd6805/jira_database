# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-27  
현재 단계: **M0~M11 DONE / PASS**

> Documentation Hub가 직접 연결하는 문서는 HTML을 기준으로 합니다. 이 Markdown은 검색/로그/개발 편의용 보조 문서입니다.

## 1. 전체 흐름

```text
Jira REST API
    ↓
RAW / ANALYSIS                         M0 DONE
    ↓
KNOWLEDGE INPUT                        M1 DONE
    ↓
Knowledge Schema + Skill               M2 DONE
    ↓
Worker → Validator → Reviewer         M3 DONE
    ↓
Real Knowledge Pilot                  M4 DONE
    ↓
Profiling                              M5 DONE
    ↓
Logical Identity / Version             M6 DONE
    ↓
SQLite Materialization                 M7 DONE · REAL-RUN PASS
    ↓
BGE-M3 Embedding                       M8 DONE · REAL-RUN PASS
    ↓
FAISS + Active Retrieval               M9 DONE · REAL-RUN PASS
    ↓
Evidence Builder + MCP                 M10 DONE · REAL-RUN PASS
    ↓
OpenCode MCP Consumer Pilot            M11 DONE · USER REAL-RUN PASS
    ↓
중앙 Remote MCP 서비스화                NEXT TARGET · 번호 미정
```

## 2. 핵심 불변 원칙

```text
RAW → ANALYSIS → KNOWLEDGE → DB → EMBEDDING → RETRIEVAL → EVIDENCE PACKAGE → MCP CONSUMER
```

- RAW가 사실의 최종 기준이다.
- History Storage와 Active Retrieval을 분리한다.
- `knowledge_generation`과 retry `knowledge_attempt`를 구분한다.
- Identity는 `jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_`를 유지한다.
- `knowledge_attempt = ka_ + attempt_no` 관계를 유지한다.
- `FAISS position ≠ embedding_id(emb_) ≠ knowledge_item_id(ki_)`다.
- MCP는 검색/근거 복원만 담당하고 생성형 LLM은 외부 Agent에 둔다.
- Local stdio는 기능/호환성 Pilot이고 최종 팀 서비스는 중앙 Remote MCP다.

## 3. Pilot 핵심 숫자

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

## 4. M9 / M10 / M11 역할 구분

```text
M9 Retrieval
질문 → BGE-M3 → FAISS → Top-3 Knowledge(ki_)

M10 Evidence/MCP
ki_ active/accepted 재검증
→ ke_ Evidence resolve
→ 실제 Jira source 복원
→ Evidence Package
→ MCP 2 tools

M11 OpenCode Consumer Pilot
OpenCode local stdio 연결
→ Tool 2개 discovery
→ 명시적 Tool call
→ 일반 업무 질문에서 자동 Tool selection
→ 후속 근거 요청에서 description/comment Evidence 추적

최종 서비스
팀원 OpenCode → 중앙 Remote MCP / HTTPS
```

FAISS는 Jira 원문을 직접 검색하지 않는다. Knowledge vector를 검색하고, 실제 원문 근거는 SQLite에서 `ki_ → ke_ → source`로 복원한다.

## 5. M10 최종 계약

```text
Evidence Package       candidate 중심
Evidence Resolver      summary / description / comment / attachment / relationship / custom_field
Candidate Budget       Top-3
Threshold              none
Reranker               none
Stale Guard            active + accepted + content_available
Runtime Failure        broken candidate 격리 + typed warning
MCP Tool               search_jira_knowledge
                       get_jira_issue
MCP Generative LLM     없음
SQLite                 mode=ro + PRAGMA query_only=ON
External payload       source_path/source_page 제외
```

## 6. M10-05 실제 Real-run — PASS

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

## 7. M11 실제 OpenCode 검증 — PASS

```text
M11-01 .env service configuration                PASS
M11-02 local stdio OpenCode 연결                 PASS
M11-03 Tool 2개 discovery                        PASS
M11-04 명시적 Tool call                          PASS
M11-05 일반 업무 질문에서 자동 Tool selection    PASS
M11-06 근거 요청에서 description/comment 추적    PASS

M11 = DONE / PASS
```

MCP/Tool 이름을 말하지 않은 일반 업무 질문에서도 OpenCode가 Jira MCP를 스스로 호출했다. 이어진 근거 요청에서는 실제 Jira `description` 또는 `comment` Evidence를 가져와 제시했다.

공개 문서에는 실제 업무 질문, Issue key, Jira 원문을 기록하지 않는다.

별도 subprocess stdio 검증:

```text
tool_count: 2
tools: get_jira_issue, search_jira_knowledge
M11_STDIO_HANDSHAKE = PASS
```

## 8. Local Pilot과 최종 팀 서비스

```text
M11 Local Pilot · DONE
jira_database/.env + SQLite + FAISS + MCP
                ↓ stdio
             OpenCode

Next Target · Final Service
팀원 A OpenCode ─┐
팀원 B OpenCode ─┼── Remote MCP / HTTPS ─→ 중앙 jira-knowledge MCP
팀원 C OpenCode ─┘                          ├─ SQLite
                                           ├─ FAISS
                                           ├─ .env
                                           └─ BGE-M3
```

최종 서비스에서는 팀원 PC가 `jira_database` clone, SQLite/FAISS artifact, BGE secret을 가지지 않는 것을 목표로 한다.

## 9. 서비스 설정 정책

```text
기본 서비스 설정   .env
OS 환경 변수       .env보다 우선 · CI/진단/일시 override
명시적 test env    .env를 읽지 않음
```

최종 Remote 서비스의 중앙 서버 `.env`:

```text
JIRA_KNOWLEDGE_DB_PATH
JIRA_RETRIEVAL_ARTIFACT_DIR
BGE_M3_ENDPOINT
BGE_M3_API_KEY       optional
BGE_M3_HEADERS_JSON  optional
```

## 10. 정식 서비스 Retrieval Update 방향

```text
Pilot       full rebuild → deterministic/integrity/reproducibility 검증
Production  delta-first  → added/changed/removed만 처리
```

후속 production-hardening 후보:

```text
vector_cache_key = H(embedding_text_hash, embedding_contract_hash)
IndexIDMap2(IndexFlatIP) + stable int64 vector_id
HNSW / IVF benchmark
```

## 11. 보안 기록 원칙

실제 Query, Issue key, Jira 원문, 사내 endpoint/header/token, 로컬 절대경로는 공개 저장소에 기록하지 않는다. Real-run Completion에는 안전한 aggregate와 동작 형태만 남긴다.

## 12. Current Source of Truth

```text
README.md
docs/index.html
docs/PIPELINE_OVERVIEW.html
docs/status/jira_knowledge_db_current_status.html
docs/status/M11_COMPLETION.html
docs/status/M11_OPENCODE_MCP_INTEGRATION.html
docs/status/M10_COMPLETION.html
docs/architecture/jira_knowledge_mcp_service_target.html
docs/architecture/jira_data_relationship_map.*
```

다음 목표는 **중앙 Remote MCP 서비스화**다. Streamable HTTP, 서버 실행 방식, TLS/인증/접근 제어, logging/health, 동시 사용 검증, 팀원 OpenCode 원격 Pilot의 Completion Gate를 먼저 합의한 뒤 다음 Milestone 번호를 확정한다.
