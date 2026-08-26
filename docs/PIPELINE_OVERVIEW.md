# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-26  
현재 단계: **M0~M9 DONE / PASS · M10 NEXT / DESIGN NOT STARTED**

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
Evidence Builder + MCP                 M10 NEXT · DESIGN NOT STARTED
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

Real Build:

```text
vector_count                  285
dimension                    1024
mapping_failure_count           0
hash_failure_count              0
normalization_failure_count     0
```

Rebuild:

```text
same rc_          PASS
same fi_          PASS
same source SHA   PASS
same mapping SHA  PASS
```

Real Query:

```text
Case 1: Rank 1/2 유효, Rank 3 noise
Case 2: Rank 1/2 유효, Rank 3 noise
```

Same-query reproducibility:

```text
vector_exact_equal=True
max_abs_diff=0
cosine=1.000000000
ranking_equal=True
scores_exact_equal=True
```

```text
M9 = DONE / PASS
```

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

## 8. M10 · Evidence Builder + MCP — NEXT

M9 output:

```text
rank
score
faiss_position
embedding_id
knowledge_item_id
category
```

M10 책임:

```text
ki_ → Knowledge statement
ke_ → Evidence source
→ Evidence package
→ MCP
```

M10에서 아직 결정하지 않은 항목:

```text
Evidence Package schema
Evidence resolver contract
MCP tool surface
candidate/evidence budget
quality/integrity Gate
error contract
```

M10에서는 Evidence 없이 LLM 답변만 만드는 것을 완료로 보지 않는다. `ki_ → ke_ → Jira source` round-trip이 핵심이다.

---

## 9. 새 세션 시작 규칙

```text
1. docs/status/M10_START_HERE.html 읽기
2. Current Status / Pipeline / M9 Final Log 확인
3. M10 책임 경계 확인
4. Evidence Package / Resolver / MCP 계약 설계
5. 사용자 승인 후 구현
```

프로세스:

```text
DESIGN → IMPLEMENTATION → VALIDATION → DOCUMENTATION SYNC
```

---

## 10. Current Source of Truth

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/status/M10_START_HERE.html
docs/architecture/jira_data_relationship_map.*
```

M9 final records:

```text
docs/M9_FAISS_ACTIVE_RETRIEVAL.md
docs/M9_DECISION_LOG.md
docs/M9_REAL_RETRIEVAL_LOG.md
docs/status/M9_FAISS_ACTIVE_RETRIEVAL.html
docs/M9_REAL_RETRIEVAL_LOG.html
```
