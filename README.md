# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Issue 단위 Knowledge Input → Knowledge 추출/검토 → Profiling → Versioned SQLite Knowledge DB → Embedding → Vector Retrieval → MCP**로 발전시키는 프로젝트입니다.

> 📚 사람이 읽는 프로젝트 문서는 [Documentation Hub](docs/index.html)에서 시작하세요. Hub가 연결하는 로컬 문서는 모두 HTML입니다.

현재 기준:

```text
M0~M8   DONE
M9      CURRENT / M9-01 DESIGN FROZEN / M9-02 IMPLEMENTED / M9-03 REAL-RUN NEXT
M10     Functional MVP Gate
```

## 1. 전체 흐름

```text
Jira REST API
    ↓
M0  RAW → ANALYSIS                          DONE
    ↓
M1  KNOWLEDGE INPUT                         DONE
    ↓
M2  Knowledge Schema v0.1 + Skill v0.9      DONE
    ↓
M3  Worker → Validator → Reviewer Loop      DONE
    ↓
M4  실제 Jira Knowledge Pilot 30/30 PASS    DONE
    ↓
M5  Knowledge / Review Profiling            DONE
    ↓
M6  DB Logical Schema                       DONE
    ↓
M7  SQLite Materialization                  DONE · REAL-RUN PASS
    ↓
M8  Embedding Unit / Chunk + BGE-M3         DONE · REAL-RUN PASS
    ├─ M8-01 corpus 285                    PASS
    ├─ M8-02 contract/adapter              PASS
    └─ M8-03 real embedding                PASS
    ↓
M9  FAISS + Active Retrieval                CURRENT
    ├─ M9-01 retrieval contract            DESIGN FROZEN
    ├─ M9-02 FAISS build/search            IMPLEMENTED · CI PASS
    └─ M9-03 real index/retrieval           NEXT
    ↓
M10 Evidence Builder + MCP                  Functional MVP Gate
```

## 2. 핵심 원칙

1. **RAW가 사실의 최종 기준**입니다.
2. 결정적 처리와 LLM 해석을 분리합니다.
3. Knowledge는 검색용 의미 압축이며 Evidence로 원문까지 round-trip할 수 있어야 합니다.
4. History Storage와 Active Retrieval을 분리합니다.
5. Vector/FAISS position을 Knowledge identity로 사용하지 않습니다.
6. Generation과 Retry Attempt를 구분합니다.
7. `knowledge_attempt_id = ka_`는 `knowledge_generation_id + attempt_no`에서 결정적으로 생성됩니다.
8. 설계/코드/Milestone 상태 변경은 Current 문서와 같은 작업 단위에서 갱신합니다.
9. Documentation Hub의 로컬 문서 링크는 `.html`만 허용합니다.

문서 정책: [Documentation Policy HTML](docs/DOCUMENTATION_POLICY.html)

## 3. 실제 Pilot 근거

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
Review JSON / Attempt         37
Final PASS                 30/30
```

Review 최종 Attempt:

```text
Attempt 1 PASS               24
Attempt 2 PASS                5
Attempt 3 PASS                1
재생성 Issue                  6
```

## 4. M6/M7 Authoritative DB 구조

```text
Pipeline Run
   └─ Issue Version Observation

Issue (jira_id authoritative)
   └─ Issue Version (iv_ · source_hash)
        └─ Knowledge Generation (kg_)
             └─ Knowledge Attempt (ka_ · attempt_no)
                  ├─ Knowledge Item (ki_)
                  │    └─ Knowledge Evidence (ke_)
                  └─ Knowledge Review
                       └─ Review Finding
```

Deterministic ID ladder:

```text
jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_
```

## 5. M7 Real-run Gate — PASS

```text
Issue              30
Generation         30
Attempt            37
Knowledge Item    285
Evidence raw      503
Evidence canonical 502
Review             37
Active Generation  30
Review Required      0
Evidence Failure     0
FK Failure           0
SQLite Integrity    OK
Idempotent          true
Failures            []
```

M5의 `503`은 historical raw Evidence 관찰값이며 M7은 duplicate 1회를 canonicalize해 `502` row를 저장합니다.

## 6. M8 Embedding — DONE / PASS

### M8-01 · Corpus

```text
Knowledge Item 1개 = Embedding Unit 1개
baseline Chunk 없음
text_profile = statement_v1

M7 active accepted Knowledge Item 285
→ corpus_rows = 285
```

### M8-02 · Embedding Contract / Adapter

```text
Embedding Contract  ec_
Embedding Artifact  emb_

emb_ = H(knowledge_item_id, embedding_text_hash, ec_)
```

실환경 계약:

```text
model               BAAI/bge-m3
API                 TEI / OpenAI-compatible
batch max           64
Pilot batch         64 + 64 + 64 + 64 + 29 = 5
dense dimension     1024
usage limit         200 requests/min
custom header       supported at runtime
```

### M8-03 · Real Embedding Gate

실제 사내 BGE-M3 전체 Pilot 실행:

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

Artifact integrity:

```text
validation: PASS
unique_knowledge_item_ids: 285
unique_embedding_ids: 285
contract_count: 1
mapping_failure_count: 0
identity_failure_count: 0
dimension_failure_count: 0
non_finite_vector_count: 0
zero_norm_vector_count: 0
temp_artifact_exists: false
```

Semantic sanity:

```text
Sample 1  PASS
Sample 2  PASS · 매우 양호
Sample 3  PASS · Top-3가 모두 의미상 타당
```

Sample 3은 cosine score가 `0.5918 / 0.5908 / 0.5900`으로 촘촘했습니다. 이는 실패가 아니라 **dense semantic neighborhood**로 기록하며, M9에서 Top-1만 과신하지 않고 Top-k 후보군 + Evidence를 검토하는 근거로 넘깁니다.

**M8 = DONE / PASS**

M8 상세 근거(사람용 HTML):

- [M8 Final Contract](docs/M8_EMBEDDING_CHUNK_BGE_M3.html)
- [M8 Decision Log](docs/M8_DECISION_LOG.html)
- [M8 Real Embedding Log](docs/M8_REAL_EMBEDDING_LOG.html)
- [M8 Visual](docs/status/M8_EMBEDDING_CHUNK_BGE_M3.html)
- [M8 Troubleshooting](docs/status/M8_REAL_EMBEDDING_TROUBLESHOOTING.html)

## 7. M9 FAISS + Active Retrieval — CURRENT

### M9-01 · DESIGN FROZEN

```text
Index       IndexFlatIP
Metric      cosine = L2 normalize + inner product
Normalize   database/query 모두 L2
Order       embedding_id ascending
Top-k       3
Threshold   none
Reranker    none
Update      full rebuild
Mapping     FAISS position → emb_ → ki_
Publish     index + mapping + manifest-last
```

`IndexFlatIP`는 Pilot exact baseline/test oracle입니다. 규모가 커지면 p95 latency, RAM, QPS, rebuild 시간, recall@k를 측정해 `IndexHNSWFlat`/`IndexIVFFlat` 등 ANN으로 전환할 수 있게 계약을 열어둡니다.

### M9-02 · IMPLEMENTED / CI PASS

구현:

```text
src/jira_collector/retrieval/
├─ contract.py      rc_ / fi_ deterministic identity
├─ source.py        M8 embedding loader / source SHA-256
├─ artifact.py      L2 normalize / IndexFlatIP / mapping / manifest-last publish
├─ validation.py    hash / mapping / dimension / normalization Gate
├─ search.py        exact cosine Top-k search
└─ query.py         동일 BGE-M3 contract의 query embedding

tools/jira_knowledge/
├─ build_faiss_index.py
├─ validate_m9_retrieval_artifact.py
└─ search_faiss.py
```

의존성:

```text
numpy >= 1.26, < 3.0
faiss-cpu >= 1.15, < 2.0
```

Synthetic CI에서 다음을 확인합니다.

```text
canonical embedding_id order
L2-normalized IndexFlatIP build
exact cosine Top-k
rc_ / fi_ deterministic identity
rebuild mapping idempotency
index/mapping SHA corruption detection
M8 source ↔ mapping round-trip
query model/profile/dimension mismatch 차단
```

### M9-03 · REAL-RUN NEXT

실제 M8 Pilot artifact 285개로 FAISS index를 만들고 다음을 확인합니다.

```text
vector_count = 285
dimension = 1024
mapping_rows = 285
unique emb_ = 285
unique ki_ = 285
hash/mapping/dimension/normalization failure = 0
same source rebuild → same rc_ / fi_ / mapping
실제 BGE-M3 query → Top-3 semantic sanity
```

## 8. 주요 문서

- [Documentation Hub](docs/index.html)
- [현재 상태](docs/status/jira_knowledge_db_current_status.html)
- [Pipeline 전체 아키텍처](docs/PIPELINE_OVERVIEW.html)
- [Jira Knowledge 관계 맵](docs/architecture/jira_data_relationship_map.html)
- [Documentation Policy](docs/DOCUMENTATION_POLICY.html)
- [M8 최종 계약](docs/M8_EMBEDDING_CHUNK_BGE_M3.html)
- [M8 실환경 검증 로그](docs/M8_REAL_EMBEDDING_LOG.html)
- [M9 FAISS 설계 Visual](docs/status/M9_FAISS_ACTIVE_RETRIEVAL.html)

## 9. 설치

Python 3.11 이상.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## 10. 다음 액션

```text
M8 DONE
  ↓
M9-01 DESIGN FROZEN
  ↓
M9-02 IMPLEMENTED / CI PASS
  ↓
M9-03 실제 285 FAISS build + real query Gate
```
