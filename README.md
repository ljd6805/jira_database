# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Knowledge 추출/검토 → Versioned SQLite Knowledge DB → BGE-M3 Embedding → FAISS Retrieval → Evidence/MCP**로 발전시키는 프로젝트입니다.

> 📚 새 세션/사람이 읽는 문서는 [Documentation Hub](docs/index.html)에서 시작하세요. Hub가 연결하는 로컬 문서는 모두 HTML입니다.

현재 기준:

```text
M0~M10  DONE / PASS
M11     OPENCODE MCP INTEGRATION · CURRENT
M11-01  .env SERVICE CONFIG · PASS
M11-02  OPENCODE LOCAL STDIO CONNECTION · PASS
M11-03  TOOL DISCOVERY · PASS
M11-04  EXPLICIT TOOL CALL · PASS
M11-05  AUTO TOOL SELECTION · NEXT
```

M10 최종 완료 기록은 **[M10 Completion](docs/status/M10_COMPLETION.html)**, 현재 M11 계획은 **[M11 OpenCode MCP Integration](docs/status/M11_OPENCODE_MCP_INTEGRATION.html)**, 최종 팀 서비스 방향은 **[Remote MCP Service Target](docs/architecture/jira_knowledge_mcp_service_target.html)** 에서 확인하세요.

## 1. 전체 흐름

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
M6  DB Logical Schema / Identity            DONE
    ↓
M7  SQLite Materialization                  DONE · REAL-RUN PASS
    ↓
M8  BGE-M3 Embedding                        DONE · REAL-RUN PASS
    ↓
M9  FAISS + Active Retrieval                DONE · REAL-RUN PASS
    ↓
M10 Evidence Builder + MCP                  DONE · REAL-RUN PASS
    ↓
M11 OpenCode MCP Integration                CURRENT · M11-01~04 PASS
```

## 2. 핵심 불변 원칙

1. **RAW가 사실의 최종 기준**입니다.
2. History Storage와 Active Retrieval을 분리합니다.
3. Generation과 Retry Attempt를 구분합니다.
4. `knowledge_attempt_id = ka_`는 `knowledge_generation_id + attempt_no`에서 결정적으로 생성됩니다.
5. Knowledge / Embedding / Retrieval identity를 서로 섞지 않습니다.
6. FAISS position을 Knowledge identity로 사용하지 않습니다.
7. Knowledge는 `ke_` Evidence를 통해 원문까지 round-trip할 수 있어야 합니다.
8. MCP는 검색/근거 복원만 담당하고 생성형 LLM을 포함하지 않습니다.
9. 설계/코드/Milestone 상태 변경은 문서와 같은 작업 단위에서 동기화합니다.
10. Documentation Hub의 로컬 링크는 HTML만 사용합니다.

Identity ladder:

```text
jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_

Embedding Contract   ec_
Embedding Artifact   emb_
Retrieval Contract   rc_
FAISS Index Artifact fi_
```

## 3. Pilot 핵심 숫자

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

## 4. M7 SQLite — DONE / PASS

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

Authoritative 구조:

```text
Issue
└─ Issue Version · iv_
   └─ Knowledge Generation · kg_
      └─ Knowledge Attempt · ka_ + attempt_no
         ├─ Knowledge Item · ki_
         │  └─ Knowledge Evidence · ke_
         └─ Knowledge Review
```

## 5. M8 BGE-M3 Embedding — DONE / PASS

```text
Knowledge Item 1개 = Embedding Unit 1개
text_profile       statement_v1
chunk baseline     없음
model              BAAI/bge-m3
dimension          1024
batch max          64
corpus_rows         285
embedding_rows      285
batch_count           5
```

## 6. M9 FAISS + Active Retrieval — DONE / PASS

Final Pilot contract:

```text
Index       IndexFlatIP
Metric      cosine = L2 normalize + inner product
Query       raw_query_v1 = query.strip()
Order       embedding_id ascending
Top-k       3
Threshold   none
Reranker    none
Mapping     FAISS position → emb_ → ki_
```

Real Gate:

```text
vector_count                  285
dimension                    1024
mapping/hash/norm failure       0
same-source rebuild            PASS
same-query vector              PASS
same-query ranking             PASS
same-query scores              PASS
```

서로 다른 실제 query 2개에서 Rank 1/2는 유효했고 Rank 3에는 noise가 관찰됐습니다. 따라서 global cosine threshold나 reranker는 아직 근거 없이 추가하지 않습니다.

## 7. 정식 서비스 Retrieval 방향 — DELTA FIRST

Pilot의 full rebuild는 운영 기본 정책이 아닙니다.

```text
unchanged → reuse
added     → cache 확인 → 필요 시 embed → add
changed   → old remove/tombstone → cache/embed → add
removed   → remove/tombstone
```

후속 production-hardening 후보:

```text
vector cache key
= H(embedding_text_hash, embedding_contract_hash)

incremental exact index
= IndexIDMap2(IndexFlatIP) + stable int64 vector_id
```

HNSW/IVF 전환은 실제 latency/RAM/QPS/recall@k 측정 후 결정합니다.

## 8. M10 Evidence Builder + MCP — DONE / PASS

M10 역할:

```text
M9
질문 → Top-3 Knowledge candidate
        ↓
M10
ki_ active/accepted 재검증
→ ke_ Evidence resolve
→ 실제 Jira source 복원
→ Evidence Package
→ MCP
        ↓
Agent / LLM 최종 답변
```

**FAISS는 Jira 원문을 직접 검색하지 않습니다.** FAISS는 Knowledge vector를 검색하고, 실제 Jira 근거는 SQLite에서 `ki_ → ke_ → source`로 복원합니다.

확정 계약:

```text
Evidence Package     candidate 중심
Evidence Type        summary / description / comment / attachment / relationship / custom_field
Runtime Failure      broken candidate 격리 + warning
Candidate Budget     M9 Top-3 유지
MCP Tool             search_jira_knowledge
                     get_jira_issue
Stale Guard          active + accepted + content_available 재검증
MCP Generative LLM   없음
```

보안 경계:

```text
MCP annotation       read_only_hint=true
SQLite               mode=ro
PRAGMA               query_only=ON
External payload     source_path/source_page 제외
```

단계별 검증:

```text
M10-01 Contract Freeze             PASS
M10-02 Evidence Resolver           PASS
M10-03 Candidate Package Builder   PASS
M10-04 MCP 2-tool boundary         PASS
M10-05 Real-run                    PASS
```

실제 Real-run 결과:

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

## 9. M11 OpenCode MCP Integration — CURRENT

M11은 이 저장소 안에 Agent를 구현하는 단계가 아닙니다. M10에서 만든 MCP를 외부 OpenCode Agent가 실제로 소비할 수 있는지 검증합니다.

현재 확인:

```text
M11-01 .env service configuration   PASS
M11-02 local stdio OpenCode 연결    PASS
M11-03 OpenCode Tool 2개 discovery PASS
M11-04 명시적 MCP Tool call        PASS
M11-05 자동 Tool selection          NEXT
M11-06 Evidence 기반 답변           NEXT
```

Local stdio MCP는 사용자가 별도로 서버를 미리 띄우는 방식이 아닙니다. OpenCode가 `opencode.jsonc`의 `command`를 보고 MCP child process를 직접 실행합니다.

같은 `jira_database` 프로젝트 루트에서 local 연결을 확인했고, 별도 stdio subprocess validator에서도 다음을 확인했습니다.

```text
tool_count: 2
tools: get_jira_issue, search_jira_knowledge
M11_STDIO_HANDSHAKE = PASS
```

또한 실제 OpenCode Agent가 두 Tool을 발견하고, MCP 사용을 명시적으로 지시한 질문에서 실제 Tool call을 수행하는 것을 확인했습니다. 이 M11-03/04 결과는 사용자 환경 Real-run입니다.

## 10. 최종 팀 서비스 목표 — CENTRAL REMOTE MCP

Local stdio는 개발/호환성 Pilot용입니다. 최종 목표는 팀원 모두가 중앙 MCP 서버를 공용으로 사용하는 구조입니다.

```text
팀원 A OpenCode ─┐
팀원 B OpenCode ─┼── Remote MCP / HTTPS ─→ 중앙 jira-knowledge MCP
팀원 C OpenCode ─┘                          ├─ SQLite
                                           ├─ FAISS
                                           ├─ .env
                                           └─ BGE-M3 API
```

최종 서비스에서는 팀원 PC가 다음을 가질 필요가 없도록 합니다.

```text
jira_database clone
SQLite Knowledge DB
FAISS artifact
BGE-M3 endpoint/key
서버용 .env
```

OpenCode 1.18.12는 Remote MCP 설정을 지원하며 Streamable HTTP를 먼저 시도하고 SSE를 fallback으로 사용합니다. 현재 MCP Python SDK 2.1.1도 `streamable-http`와 `sse` 서버 transport를 지원합니다.

다만 M11에서는 먼저 local 환경에서 자동 Tool selection과 Evidence 기반 답변까지 검증합니다. 그 이후 Remote 서버화, 인증/TLS, logging/health/concurrency를 별도 서비스 단계로 진행합니다.

## 11. 서비스 설정 정책

```text
기본 서비스 설정   .env
OS 환경 변수       .env보다 우선 · CI/진단/일시 override
명시적 test env    .env를 읽지 않음
```

현재 local Pilot에서는 프로젝트 루트의 `.env`, 최종 Remote 서비스에서는 중앙 서버 배포 디렉터리의 `.env`를 사용합니다.

서비스 `.env`에는 다음을 둡니다.

```text
JIRA_KNOWLEDGE_DB_PATH
JIRA_RETRIEVAL_ARTIFACT_DIR
BGE_M3_ENDPOINT
BGE_M3_API_KEY       optional
BGE_M3_HEADERS_JSON  optional
```

`M10_REAL_RUN_QUERY`는 검증 전용이므로 실제 서비스 `.env`에는 기본적으로 넣지 않습니다.

## 12. 주요 문서

- [Documentation Hub](docs/index.html)
- [M11 OpenCode MCP Integration](docs/status/M11_OPENCODE_MCP_INTEGRATION.html)
- [Remote MCP Service Target](docs/architecture/jira_knowledge_mcp_service_target.html)
- [M11 Connection Closed Troubleshooting](docs/status/M11_TROUBLESHOOTING_OPENCODE_CONNECTION_CLOSED.html)
- [M10 Completion](docs/status/M10_COMPLETION.html)
- [Current Status](docs/status/jira_knowledge_db_current_status.html)
- [Pipeline Overview](docs/PIPELINE_OVERVIEW.html)
- [Relationship Map](docs/architecture/jira_data_relationship_map.html)
- [Documentation Policy](docs/DOCUMENTATION_POLICY.html)

## 13. 로컬 Pilot Artifact

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
