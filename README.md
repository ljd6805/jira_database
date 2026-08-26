# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Issue 단위 Knowledge Input → Knowledge 추출/검토 → Profiling → Versioned SQLite Knowledge DB → Embedding → Vector Retrieval → MCP**로 발전시키는 프로젝트입니다.

> 📚 **프로젝트 문서는 [Documentation Hub](docs/index.html)에서 시작하세요.**  
> 초기 구상부터 M0~M8 현재 상태, 관계 맵, M9/M10 향후 단계까지 한 흐름으로 연결되어 있습니다.

현재 기준:

```text
M0~M7   DONE
M8      CURRENT / M8-01 PASS / M8-02 IMPLEMENTED / M8-03 REAL API NEXT
M9      PLAN
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
M7  SQLite Materialization                  DONE
    ↓
M8  Embedding Unit / Chunk + BGE-M3         CURRENT
    ├─ M8-01 corpus 285                    PASS
    ├─ M8-02 contract/adapter              IMPLEMENTED
    └─ M8-03 real BGE-M3                   NEXT
    ↓
M9  FAISS + Active Retrieval                PLAN
    ↓
M10 Evidence Builder + MCP                  Functional MVP Gate
```

## 2. 핵심 원칙

1. **RAW가 사실의 최종 기준**입니다.
2. **결정적 처리와 LLM 해석을 분리**합니다.
3. Knowledge는 검색용 의미 압축이며 **Evidence로 원문까지 round-trip**할 수 있어야 합니다.
4. **History Storage와 Active Retrieval을 분리**합니다.
5. Vector ID를 Knowledge identity로 사용하지 않습니다.
6. Generation과 Retry Attempt를 구분하고 deterministic ID를 부여합니다.
7. 과거 artifact의 계약 drift는 사후 수정하지 않고 compatibility layer로 보존합니다.
8. 설계/코드/Milestone 상태 변경은 Current 문서와 같은 작업 단위에서 갱신합니다.

문서 동기화 규칙: [`docs/DOCUMENTATION_POLICY.md`](docs/DOCUMENTATION_POLICY.md)

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

## 4. M6/M7 최종 DB 구조

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
M5 raw expected
Issue              30
Generation         30
Attempt            37
Knowledge Item    285
Evidence raw      503
Review             37

M7 canonical DB
Issue              30
Generation         30
Attempt            37
Knowledge Item    285
Evidence           502
Review             37

Active Generation  30
Review Required      0
Evidence Failure     0
FK Failure           0
SQLite Integrity    OK
Idempotent          true
Failures            []
```

M5의 `503`은 historical JSON raw 관찰값이며 M7은 duplicate Evidence 1회를 canonicalize해 `502` row를 저장합니다.

M7 상세 근거:

- [`docs/M7_SQLITE_MATERIALIZATION.md`](docs/M7_SQLITE_MATERIALIZATION.md)
- [`docs/M7_REAL_RUN_LOG.md`](docs/M7_REAL_RUN_LOG.md)
- [`docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md`](docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md)

## 6. Active / Historical 정책

```text
DB
→ Current + Historical Version/Generation/Attempt 보존

기본 Retrieval / Embedding corpus
→ state=active Generation의 accepted Attempt만 사용
```

새 candidate가 생겨도 PASS 전에는 기존 active를 유지합니다.

## 7. 현재 단계 · M8

### M8-01 · PASS

```text
Knowledge Item 1개 = Embedding Unit 1개
baseline Chunk 없음
text_profile = statement_v1

M7 active accepted Knowledge Item 285
→ corpus_rows: 285
```

### M8-02 · IMPLEMENTED

Embedding identity:

```text
Embedding Contract  ec_
Embedding Artifact  emb_

emb_ = H(knowledge_item_id, embedding_text_hash, ec_)
```

BGE-M3 contract:

```text
model               BAAI/bge-m3
API                 OpenAI-compatible
batch max           64
Pilot batch         64 + 64 + 64 + 64 + 29 = 5 requests
dense dimension     1024
usage limit         200 requests/min
```

검증/실패 정책:

- `data[].index`로 request↔response mapping
- index 누락/중복/범위 오류 차단
- 1024-dim이 아니면 실패
- network/429/5xx만 retry
- 모든 batch 성공 후에만 atomic final JSONL publish

구현:

```text
src/jira_collector/embedding/
├─ corpus.py
├─ contract.py
├─ client.py
├─ config.py
├─ artifact.py
└─ runner.py

tools/jira_knowledge/
├─ export_embedding_corpus.py
└─ embed_bge_m3.py
```

GitHub Actions pytest: **PASS**

### M8-03 · NEXT

`.env`에 실제 사내 endpoint를 넣고 real embedding Gate를 수행합니다.

```dotenv
BGE_M3_ENDPOINT=<사내 OpenAI-compatible embeddings endpoint>
BGE_M3_API_KEY=<필요한 경우>
```

```powershell
python tools/jira_knowledge/embed_bge_m3.py --corpus data/embedding/runs/20260804T043628Z/corpus.statement_v1.jsonl --output data/embedding/runs/20260804T043628Z/embeddings.statement_v1.bge_m3.jsonl --expected-count 285
```

성공 기대값:

```text
corpus_rows: 285
embedding_rows: 285
batch_count: 5
embedding_dimension: 1024
```

**M8에서는 FAISS를 구현하지 않습니다.** FAISS와 Top-k Retrieval은 M9 책임입니다.

## 8. 주요 문서

- [Documentation Hub](docs/index.html)
- [현재 상태와 향후 계획](docs/status/jira_knowledge_db_current_status.html)
- [Pipeline 전체 아키텍처](docs/PIPELINE_OVERVIEW.md)
- [Jira Knowledge 관계 맵](docs/architecture/jira_data_relationship_map.html)
- [M8 Design](docs/M8_EMBEDDING_CHUNK_BGE_M3.md)
- [M8 Decision Log](docs/M8_DECISION_LOG.md)

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
M8-01 PASS
  ↓
M8-02 IMPLEMENTED / CI PASS
  ↓
M8-03 실제 BGE-M3 endpoint 검증
  ↓
285 vectors / 5 batches / 1024-dim / mapping 확인
  ↓
M8 Gate
  ↓
M9 FAISS
```
