# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Knowledge 추출/검토 → Versioned SQLite Knowledge DB → BGE-M3 Embedding → FAISS Retrieval → Evidence/MCP → OpenCode 실제 소비자 검증**까지 발전시킨 프로젝트입니다.

> 📚 새 세션/사람이 읽는 문서는 [Documentation Hub](docs/index.html)에서 시작하세요. Hub가 연결하는 로컬 문서는 모두 HTML입니다.

현재 기준:

```text
M0~M11  DONE / PASS
        = Functional MVP 완료

Next Phase
Continuous Jira Knowledge Service
```

MVP 완료는 **[M11 Completion](docs/status/M11_COMPLETION.html)**, 이후 운영 서비스 전체 목표는 **[Operational Service Phase](docs/architecture/jira_knowledge_operational_service_phase.html)**, 중앙 MCP 구성요소는 **[Remote MCP Service Target](docs/architecture/jira_knowledge_mcp_service_target.html)** 에서 확인하세요.

## 1. 전체 흐름

```text
Functional MVP
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

1. **RAW가 사실의 최종 기준**입니다.
2. History Storage와 Active Retrieval을 분리합니다.
3. Generation과 Retry Attempt를 구분합니다.
4. `knowledge_attempt_id = ka_`는 `knowledge_generation_id + attempt_no`에서 결정적으로 생성됩니다.
5. Knowledge / Embedding / Retrieval identity를 서로 섞지 않습니다.
6. FAISS position을 Knowledge identity로 사용하지 않습니다.
7. Knowledge는 `ke_` Evidence를 통해 원문까지 round-trip할 수 있어야 합니다.
8. MCP는 검색/근거 복원만 담당하고 생성형 LLM을 포함하지 않습니다.
9. 운영 기본은 **delta-first**이며 full rebuild는 복구/마이그레이션/검증 경로입니다.
10. 설계/코드/Milestone 상태 변경은 문서와 같은 작업 단위에서 동기화합니다.
11. Documentation Hub의 로컬 링크는 HTML만 사용합니다.

Identity ladder:

```text
jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_

knowledge_attempt = ka_ + attempt_no
Embedding Contract   ec_
Embedding Artifact   emb_
Retrieval Contract   rc_
FAISS Index Artifact fi_

FAISS position ≠ emb_ ≠ ki_
```

## 3. MVP 핵심 숫자

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

이 Version/Generation/Attempt/Active 구분은 MVP 편의용이 아니라 이후 **지속 업데이트와 History 보존**을 위한 기반입니다.

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

```text
Index       IndexFlatIP
Metric      cosine = L2 normalize + inner product
Query       raw_query_v1 = query.strip()
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

## 7. Production Retrieval 방향 — DELTA FIRST

```text
unchanged → reuse
added     → cache 확인 → 필요 시 embed → add
changed   → old remove/tombstone → cache/embed → add
removed / no access → 정책 확정 후 active 처리
```

후속 후보:

```text
vector cache key = H(embedding_text_hash, embedding_contract_hash)
incremental exact index = IndexIDMap2(IndexFlatIP) + stable int64 vector_id
```

HNSW/IVF는 실제 latency/RAM/QPS/recall@k 측정 후 결정합니다.

## 8. M10 Evidence Builder + MCP — DONE / PASS

```text
질문 → BGE-M3 → FAISS Top-3 Knowledge
→ ki_ active/accepted 재검증
→ ke_ Evidence resolve
→ 실제 Jira source 복원
→ Evidence Package
→ MCP
```

확정 계약:

```text
Evidence Type      summary / description / comment / attachment / relationship / custom_field
Candidate Budget   Top-3
Stale Guard        active + accepted + content_available
MCP Tool           search_jira_knowledge
                   get_jira_issue
MCP Generative LLM 없음
SQLite             mode=ro + PRAGMA query_only=ON
External payload   source_path/source_page 제외
```

실제 Real-run:

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

## 9. M11 OpenCode MCP Integration — DONE / PASS

```text
M11-01 .env service configuration                PASS
M11-02 local stdio OpenCode 연결                 PASS
M11-03 OpenCode Tool 2개 discovery              PASS
M11-04 명시적 MCP Tool call                     PASS
M11-05 일반 업무 질문에서 자동 Tool selection   PASS
M11-06 근거 요청에서 description/comment 추적   PASS

M11 = DONE / PASS
```

실제 OpenCode에서 일반 업무 질문만으로 Jira MCP가 자동 호출됐고, 근거 요청에서는 Jira `description` 또는 `comment` Evidence까지 추적했습니다. 공개 저장소에는 실제 업무 질문, Issue key, Jira 원문을 기록하지 않습니다.

```text
tool_count: 2
tools: get_jira_issue, search_jira_knowledge
M11_STDIO_HANDSHAKE = PASS
```

여기까지가 **Functional MVP**입니다.

## 10. 최종 서비스 목표 — CONTINUOUS JIRA KNOWLEDGE SERVICE

최종 서비스는 Remote MCP 하나가 아닙니다. Jira의 변화가 자동으로 전체 지식 파이프라인에 반영돼야 합니다.

```text
Jira
 ↓ Project Discovery
신규/기존/접근 상태 확인
 ↓
Delta Issue Sync
신규·수정 Issue / comment / relationship / field
 ↓
RAW / Issue Version
source_hash 동일 → reuse
source_hash 변경 → 새 Version
 ↓ 변경분만
Knowledge / Evidence
 ↓ 변경분만
Embedding / FAISS
 ↓ latest Active corpus
Central Remote MCP / HTTPS
 ↓
팀원 OpenCode
```

### 서비스해야 하는 네 축

1. **지속적인 Jira 업데이트** — 마지막 성공 sync 이후 변경분을 반복 수집하고 실패 후 재개합니다.
2. **Project 추가/변화** — 접근 가능한 프로젝트 전체를 매 sync discovery하여 새 프로젝트를 자동 편입합니다.
3. **변경사항 하위 파이프라인 전파** — 변경된 Version만 Knowledge→Embedding→FAISS까지 갱신합니다.
4. **중앙 MCP 서비스** — 팀원 PC에 DB/FAISS/.env를 복제하지 않고 중앙 Remote MCP를 사용합니다.

상세: [Operational Service Phase](docs/architecture/jira_knowledge_operational_service_phase.html)

## 11. 중앙 Remote MCP — 서비스의 조회 경계

```text
팀원 A OpenCode ─┐
팀원 B OpenCode ─┼── Remote MCP / HTTPS ─→ 중앙 jira-knowledge MCP
팀원 C OpenCode ─┘                          ├─ SQLite
                                           ├─ FAISS
                                           ├─ .env
                                           └─ BGE-M3 API
```

OpenCode 1.18.12 Remote MCP와 MCP Python SDK 2.1.1의 Streamable HTTP/SSE 지원을 활용할 수 있습니다. 다만 **Remote MCP 서버화만 먼저 해서는 운영 서비스가 완성되지 않습니다.** Background sync가 최신 Active corpus를 유지해야 합니다.

## 12. 서비스 설정 정책

```text
기본 서비스 설정   .env
OS 환경 변수       .env보다 우선 · CI/진단/일시 override
명시적 test env    .env를 읽지 않음
```

서비스 `.env`:

```text
JIRA_KNOWLEDGE_DB_PATH
JIRA_RETRIEVAL_ARTIFACT_DIR
BGE_M3_ENDPOINT
BGE_M3_API_KEY       optional
BGE_M3_HEADERS_JSON  optional
```

`M10_REAL_RUN_QUERY`는 검증 전용이며 서비스 `.env`에는 넣지 않습니다.

## 13. 운영 서비스에서 아직 결정해야 할 것

- sync 주기와 scheduling 방식
- 마지막 성공 sync / 안전 overlap / watermark 상세 계약
- Jira 삭제와 서비스 계정 권한 상실의 구분 및 active 비활성화 정책
- 팀원별 Jira 접근권한 재현 필요 여부
- Knowledge/Embedding/FAISS delta update의 원자적 전환 방식
- Remote MCP 인증/TLS/접근 제어
- retry/timeout/concurrency
- sync/MCP health, 로그, 운영 모니터링

특히 **사용자별 Jira 권한 재현은 MVP에서 제외했던 항목**이므로 팀 공용 중앙 서비스 전에 반드시 정책을 확정해야 합니다.

## 14. 다음 단계

다음 단계는 **Continuous Jira Knowledge Service**를 어떤 Milestone으로 나눌지 설계하는 것입니다.

```text
Project Discovery / Sync State
→ Delta Jira Collection
→ Incremental Knowledge Update
→ Incremental Embedding / FAISS
→ Central Remote MCP
→ Scheduling / Retry / Observability
→ Team Pilot
```

다음 Milestone 번호는 각 단계의 목적과 Completion Gate를 먼저 합의한 뒤 확정합니다.

## 15. 주요 문서

- [Documentation Hub](docs/index.html)
- [Operational Service Phase](docs/architecture/jira_knowledge_operational_service_phase.html)
- [Remote MCP Service Target](docs/architecture/jira_knowledge_mcp_service_target.html)
- [M11 Completion](docs/status/M11_COMPLETION.html)
- [M11 OpenCode MCP Integration](docs/status/M11_OPENCODE_MCP_INTEGRATION.html)
- [M11 Connection Closed Troubleshooting](docs/status/M11_TROUBLESHOOTING_OPENCODE_CONNECTION_CLOSED.html)
- [M10 Completion](docs/status/M10_COMPLETION.html)
- [Current Status](docs/status/jira_knowledge_db_current_status.html)
- [Pipeline Overview](docs/PIPELINE_OVERVIEW.html)
- [Relationship Map](docs/architecture/jira_data_relationship_map.html)
- [Documentation Policy](docs/DOCUMENTATION_POLICY.html)

## 16. 로컬 MVP Artifact

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
