# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Knowledge 추출/검토 → Versioned SQLite Knowledge DB → BGE-M3 Embedding → FAISS Retrieval → Evidence/MCP**로 발전시키는 프로젝트입니다.

> 📚 새 세션/사람이 읽는 문서는 [Documentation Hub](docs/index.html)에서 시작하세요. Hub가 연결하는 로컬 문서는 모두 HTML입니다.

현재 기준:

```text
M0~M10  DONE / PASS
NEXT    아직 정의하지 않음
```

M10 최종 완료 기록은 **[M10 Completion](docs/status/M10_COMPLETION.html)** 에서 확인하세요.

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

## 7. 정식 서비스 방향 — DELTA FIRST

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

각 값의 의미:

```text
tool_count 2
= MCP가 제공하는 기능 종류가 2개라는 뜻.
  search_jira_knowledge + get_jira_issue.
  Tool을 2번 호출했다는 뜻은 아님.

search_result_count 3
= FAISS Top-3 Knowledge 후보 3개.

Evidence_count 6
= 검색된 Knowledge 3개를 뒷받침하는 실제 Jira 근거 총 6개.
  Issue 6개나 Knowledge 6개라는 뜻은 아님.

warning_count 0
= stale / missing / invalid ref 등 깨진 candidate 없음.

path_leak_count 0
= source_path / source_page 등 내부 경로 노출 없음.

issue_lookup_ok true
= 검색 결과에서 실제 active Issue 재조회 성공.

failure_count 0
= Completion Gate 실패 항목 없음.
```

이 결과로 실제 **BGE-M3 → FAISS → ki_ → ke_ → Jira source → MCP response** 경로가 end-to-end로 검증됐습니다.

## 9. M10 Real-run에서 실제로 해결한 트러블슈팅

```text
1) ModuleNotFoundError: No module named 'mcp'
   → 현재 Python environment에 MCP SDK가 없었음.

2) M10_REAL_RUN_QUERY 환경 변수가 비어 있습니다
   → 실제 검색 질문 환경변수가 필요했음.

3) McpRuntimeSettingsError
   → M7 SQLite / M9 FAISS artifact 경로 환경변수가 필요했음.
```

Windows PowerShell에서 현재 테스트했고, 향후 Linux 포팅 명령도 HTML 트러블슈팅 문서에 함께 기록했습니다.

## 10. 주요 문서

- [Documentation Hub](docs/index.html)
- [M10 Completion](docs/status/M10_COMPLETION.html)
- [M10 Start Here](docs/status/M10_START_HERE.html)
- [M10 쉬운 확정 설계](docs/M10_EVIDENCE_MCP_DESIGN.html)
- [M10 Contract Freeze](docs/status/M10_EVIDENCE_MCP_CONTRACT.html)
- [M10 Resolver / Package PASS](docs/status/M10_EVIDENCE_RESOLVER_IMPLEMENTATION.html)
- [M10 MCP Implementation PASS](docs/status/M10_MCP_IMPLEMENTATION.html)
- [M10 Real-run PASS](docs/status/M10_REAL_RUN_GATE.html)
- [MCP Import Troubleshooting](docs/status/M10_TROUBLESHOOTING_MCP_IMPORT.html)
- [Query Troubleshooting](docs/status/M10_TROUBLESHOOTING_REAL_RUN_QUERY.html)
- [Runtime Settings Troubleshooting](docs/status/M10_TROUBLESHOOTING_RUNTIME_SETTINGS.html)
- [Current Status](docs/status/jira_knowledge_db_current_status.html)
- [Pipeline Overview](docs/PIPELINE_OVERVIEW.html)
- [Relationship Map](docs/architecture/jira_data_relationship_map.html)
- [Documentation Policy](docs/DOCUMENTATION_POLICY.html)

## 11. 로컬 Pilot Artifact

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

## 12. 다음 단계

M10까지 완료했습니다. 다음 Milestone은 아직 확정하지 않습니다. 운영화, Agent 연동, retrieval hardening 중 무엇을 다음 경계로 둘지는 별도 의사결정으로 정의합니다.
