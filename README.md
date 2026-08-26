# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Issue 단위 Knowledge Input → Knowledge 추출/검토 → Profiling → Versioned SQLite Knowledge DB → Embedding → Vector Retrieval → MCP**로 발전시키는 프로젝트입니다.

> 📚 **프로젝트 문서는 [Documentation Hub](docs/index.html)에서 시작하세요.**  
> 초기 구상부터 M0~M8 현재 상태, 관계 맵, M9/M10 향후 단계까지 한 흐름으로 연결되어 있습니다.

현재 기준:

```text
M0~M7   DONE
M8      CURRENT / M8-01 CORPUS IMPLEMENTED
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
    └─ M8-01 corpus exporter 구현 완료
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

Run-scoped source entity:

```text
comment
attachment
relationship
custom_field_catalog
custom_field_value
```

Deterministic ID ladder:

```text
jira_id → iv_ → kc_ → kg_ → ka_ → ki_ → ke_
```

## 5. M7 Real-run Gate — PASS

대상 Run:

```text
20260804T043628Z
```

최종 검증:

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

M5의 `503`은 historical JSON의 raw 관찰값입니다. Pilot에는 duplicate Evidence가 1회 있었고, M7은 M6의 `UNIQUE(knowledge_item_id, evidence_ref)` 계약을 유지하며 첫 occurrence만 적재해 canonical DB row를 `502`로 만듭니다. 실제 Jira 식별자는 공개 문서에 기록하지 않습니다.

M7 상세 근거:

- [`docs/M7_SQLITE_MATERIALIZATION.md`](docs/M7_SQLITE_MATERIALIZATION.md)
- [`docs/M7_REAL_RUN_LOG.md`](docs/M7_REAL_RUN_LOG.md)
- [`docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md`](docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md)
- [`docs/status/M7_SQLITE_MATERIALIZATION.html`](docs/status/M7_SQLITE_MATERIALIZATION.html)

## 6. Active / Historical 정책

```text
DB
→ Current + Historical Version/Generation/Attempt 보존

기본 Retrieval
→ state=active Generation의 accepted Attempt만 사용

History Retrieval
→ 감사 / 재현 / 변화 분석 / temporal query에서 사용
```

새 candidate가 생겨도 PASS 전에는 기존 active를 유지합니다.

## 7. 현재 단계 · M8

M8은 **Embedding Unit / Chunk 전략 + BGE-M3** 단계입니다.

M8-01에서 다음 baseline을 고정하고 구현했습니다.

```text
Corpus
→ state=active
→ accepted_attempt_id 존재
→ accepted Attempt content_available=1
→ Knowledge Item만 포함

Embedding Unit
→ Knowledge Item 1개 = Embedding Unit 1개

Chunk
→ baseline에서는 없음
→ tokenizer/검색 품질 근거가 있을 때만 추가

Text Profile
→ statement_v1
→ embedding_text = statement.strip()
→ embedding_text_hash = SHA-256(UTF-8 text)
```

구현:

```text
src/jira_collector/embedding/corpus.py
tools/jira_knowledge/export_embedding_corpus.py
tests/embedding/test_corpus.py
```

Synthetic filtering/order/hash test는 CI PASS입니다. 다음 Gate는 실제 M7 DB에서 corpus가 정확히 **285 row**인지 확인하는 것입니다.

FAISS는 M9 책임이며 M8에 섞지 않습니다.

## 8. 주요 문서

**공식 단일 진입점:**

- [Documentation Hub](docs/index.html) — Baseline → M0~M8 → M9/M10 전체 여정
- [Baseline Jira → BGE-M3 RAG → MCP 최소 구현 계획](docs/planning/jira_rag_mcp_minimum_implementation_plan.html)

Current Source of Truth:

- [현재 상태와 향후 계획](docs/status/jira_knowledge_db_current_status.html)
- [Pipeline 전체 아키텍처](docs/PIPELINE_OVERVIEW.md)
- [Jira Knowledge 관계 맵](docs/architecture/jira_data_relationship_map.html)
- [Documentation Policy](docs/DOCUMENTATION_POLICY.md)

설계/완료 기록:

- [M6 DB Logical Schema](docs/DB_LOGICAL_SCHEMA.md)
- [M6 Decision Log](docs/M6_DECISION_LOG.md)
- [M7 SQLite Materialization](docs/M7_SQLITE_MATERIALIZATION.md)
- [M7 Completion Record](docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md)
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

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Jira API 제한 기본값:

```yaml
jira:
  rate_limit:
    requests_per_minute: 20
    max_concurrency: 1
```

## 10. 다음 액션

```text
M8-01 구현 완료
  ↓
실제 M7 SQLite에서 active accepted corpus export
  ↓
corpus_rows = 285 확인
  ↓
M8-01 PASS
  ↓
M8-02
→ deterministic embedding contract / embedding_id
→ BGE-M3 adapter
→ batch <= 64
→ dense dimension = 1024
```
