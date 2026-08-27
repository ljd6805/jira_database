# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-27  
현재 단계: **M0~M9 DONE / PASS · M10 IMPLEMENTATION PASS / REAL-RUN NEXT**

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
Evidence Builder + MCP                 M10 IMPLEMENTATION PASS · REAL-RUN NEXT
```

---

## 2. 핵심 불변 원칙

### RAW = Source of Truth

뒤 계층은 앞 계층에서 다시 만들 수 있는 파생물이어야 한다.

```text
RAW → ANALYSIS → KNOWLEDGE → DB → EMBEDDING → RETRIEVAL → EVIDENCE PACKAGE
```

### History와 Active Retrieval 분리

```text
DB
→ Current + Historical Version/Generation/Attempt 보존

Embedding / Retrieval
→ active Generation의 accepted Attempt snapshot만 기본 사용
```

### Identity 보존

```text
jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_
```

`knowledge_attempt_id(ka_)`는 `knowledge_generation_id + attempt_no`로 결정된다.

```text
Embedding Contract   ec_
Embedding Artifact   emb_
Retrieval Contract   rc_
FAISS Index Artifact fi_
```

```text
FAISS position ≠ embedding_id ≠ knowledge_item_id
```

### MCP는 검색/근거 계층

```text
MCP
→ BGE-M3 query embedding
→ M9 retrieval
→ M10 Evidence resolve
→ structured Evidence Package

Agent / LLM
→ Evidence Package를 읽고 최종 자연어 답변
```

MCP 내부에 별도 생성형 LLM을 두지 않는다.

---

## 3. Pilot 근거

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

M5 raw Evidence 503 중 historical duplicate 1회를 M7에서 canonicalize해 502 row를 저장한다.

---

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

```text
Issue
└─ Issue Version · iv_
   └─ Knowledge Generation · kg_
      └─ Knowledge Attempt · ka_ + attempt_no
         ├─ Knowledge Item · ki_
         │  └─ Knowledge Evidence · ke_
         └─ Knowledge Review
```

---

## 5. M8 Embedding — DONE / PASS

```text
Knowledge Item 1개 = Embedding Unit 1개
text_profile       statement_v1
chunk baseline     없음
model              BAAI/bge-m3
dimension          1024
corpus_rows         285
embedding_rows      285
batch_count           5
```

Integrity:

```text
unique ki_          285
unique emb_         285
mapping failure       0
identity failure      0
dimension failure     0
non-finite vector     0
zero-norm vector      0
```

---

## 6. M9 Retrieval — DONE / PASS

Final Pilot contract:

```text
Index       IndexFlatIP
Metric      cosine
Normalize   DB/query 모두 L2
Query       raw_query_v1
Order       embedding_id ascending
Top-k       3
Threshold   none
Reranker    none
Mapping     faiss_position → emb_ → ki_
```

Artifact:

```text
index.faiss
index.mapping.jsonl
index.manifest.json
```

Real Build / Rebuild / Query:

```text
vector_count                  285
dimension                    1024
mapping/hash/norm failure       0
same rc_                       PASS
same fi_                       PASS
same-query vector              PASS
same-query ranking             PASS
same-query scores              PASS
```

실제 Query 2건에서 Rank 1/2는 유효했고 Rank 3에는 noise가 관찰됐다. 따라서 global cosine threshold나 reranker는 아직 임의 추가하지 않는다.

---

## 7. 정식 서비스 Retrieval Update 방향

Pilot full rebuild와 운영 update를 분리한다.

```text
Pilot       full rebuild → deterministic/integrity/reproducibility 검증
Production  delta-first  → added/changed/removed만 처리
```

후속 production-hardening 후보:

```text
vector_cache_key
= H(embedding_text_hash, embedding_contract_hash)

IndexIDMap2(IndexFlatIP)
+ stable int64 vector_id
```

Scale-up 시 `IndexHNSWFlat` / `IndexIVFFlat`을 Flat exact 결과와 `recall@k + latency + RAM + QPS`로 비교한다.

---

## 8. M10 Evidence Builder + MCP — IMPLEMENTATION PASS

### 아주 쉽게

```text
M9
“질문과 가까운 Knowledge는 이것입니다.”
        ↓
M10
“그 Knowledge의 실제 Jira 근거는 이 설명/댓글/관계입니다.”
        ↓
Agent
Knowledge + Evidence를 보고 최종 답변
```

### M10-01 Contract Freeze

```text
Evidence Package       candidate 중심
Evidence Resolver      M7의 6종 ref 계약 재사용
Runtime Failure        broken candidate 격리 + warning
Candidate Budget       M9 Top-3 유지
MCP Tool Surface       2 tools
Stale Guard            active accepted 재검증
```

### M10-02 / M10-03 Evidence

```text
M9 RetrievalCandidate
  ↓
ki_ active/accepted/content_available 확인
  ↓
ke_ Evidence
  ↓
summary / description / comment / attachment / relationship / custom_field
  ↓
EvidencePackage
```

주요 typed failure:

```text
KNOWLEDGE_NOT_FOUND
STALE_RETRIEVAL_INDEX
EVIDENCE_SOURCE_MISSING
EVIDENCE_REF_INVALID
CATEGORY_MISMATCH
```

### M10-04 MCP

외부 tool은 정확히 2개다.

```text
search_jira_knowledge(query, top_k=3)
get_jira_issue(issue_key)
```

보안 경계:

```text
Tool annotation
read_only_hint = true
open_world_hint = false

SQLite
mode=ro
PRAGMA query_only=ON

External payload
source_path/source_page 제외
```

MCP 내부에는 생성형 LLM이 없다.

CI:

```text
MCP Client tools/list         PASS
search tool call              PASS
get issue tool call           PASS
SQLite write rejection        PASS
path leak synthetic Gate      PASS
GitHub Actions pytest         133/133 PASS
```

---

## 9. M10-05 Real-run — NEXT

현재 구현을 실제 로컬 artifact와 사내 BGE-M3에 연결하는 마지막 Gate다.

```text
실제 질문
→ 실제 BGE-M3 query embedding
→ 실제 M9 index
→ Top-3 ki_
→ 실제 M7 SQLite
→ ke_ / Jira source
→ Evidence Package
→ MCP response
```

실행 도구:

```text
tools/jira_knowledge/validate_m10_real_run.py
```

필요 환경:

```text
JIRA_KNOWLEDGE_DB_PATH
JIRA_RETRIEVAL_ARTIFACT_DIR
BGE_M3_ENDPOINT
BGE_M3_API_KEY       optional
BGE_M3_HEADERS_JSON  optional
M10_REAL_RUN_QUERY
```

검증 도구는 실제 query/Issue key/Jira 원문을 stdout에 출력하지 않고 다음 안전한 집계만 남긴다.

```text
tool_count
search_result_count
evidence_count
warning_count
path_leak_count
issue_lookup_ok
failure_count
M10_REAL_RUN = PASS / FAIL
```

Real-run에서 `warning_count=0`, `path_leak_count=0`, 검색 결과/Evidence 존재, `get_jira_issue` round-trip이 모두 확인돼야 M10을 DONE으로 판정한다.

---

## 10. 작업 프로세스

```text
DESIGN → IMPLEMENTATION → VALIDATION → DOCUMENTATION SYNC
```

M10 현재 위치:

```text
DESIGN          PASS
IMPLEMENTATION  PASS
CI VALIDATION   PASS
REAL-RUN        NEXT
COMPLETION      BLOCKED UNTIL REAL-RUN PASS
```

---

## 11. Current Source of Truth

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/status/M10_START_HERE.html
docs/status/M10_EVIDENCE_MCP_CONTRACT.html
docs/status/M10_EVIDENCE_RESOLVER_IMPLEMENTATION.html
docs/status/M10_MCP_IMPLEMENTATION.html
docs/architecture/jira_data_relationship_map.*
```
