# Jira Knowledge Pipeline

Jira REST API에서 업무 원본을 읽기 전용으로 수집하고, **원본 보존 → 결정적 정규화 → Issue 단위 사실 패키지 → Knowledge 추출/검토 → Profiling → Versioned SQLite Knowledge DB → Vector Retrieval → MCP**로 발전시키는 프로젝트입니다.

현재 기준:

```text
M0~M6   DONE
M7      IMPLEMENTED / REAL-RUN VALIDATION PENDING
M8      BLOCKED UNTIL M7 REAL-RUN GATE
```

M6에서는 Issue Version, deterministic ID, Generation/Attempt, Evidence round-trip, Active/History 경계를 확정했고, M7에서 이를 SQLite Schema v1과 loader/integrity test로 구현했습니다.

```text
Jira REST API
    ↓
M0  [RAW] → [ANALYSIS]                       DONE
    ↓
M1  [KNOWLEDGE INPUT]                        DONE
    ↓
M2  Knowledge Schema v0.1 + Skill v0.9       DONE
    ↓
M3  Worker → Validator → Reviewer Loop       DONE
    ↓
M4  [KNOWLEDGE] + [REVIEW] 실제 Jira Pilot  DONE
    ↓
M5  Knowledge / Review Profiling             DONE
    ↓
M6  DB Logical Schema                        DONE
    ↓
M7  SQLite Materialization                   CURRENT · IMPLEMENTED
        └─ real 30-issue validation pending
    ↓
M8  Chunk + BGE-M3                           BLOCKED
    ↓
M9  FAISS + Active Retrieval
    ↓
M10 Evidence Builder + MCP                   Functional MVP Gate
```

## 1. 핵심 원칙

1. **RAW가 사실의 최종 기준**입니다.
2. **결정적 처리와 LLM 해석을 분리**합니다.
3. **Knowledge는 검색용 의미 압축이며 Evidence로 원문까지 round-trip**할 수 있어야 합니다.
4. **History Storage와 Active Retrieval을 분리**합니다.
5. **Vector ID를 Knowledge identity로 사용하지 않습니다.**
6. **Generation과 Retry Attempt를 구분하고 각 계층에 deterministic ID를 부여합니다.**
7. **코드/설계/Milestone 상태 변경은 Current 문서와 같은 작업 단위에서 갱신합니다.**

문서 동기화 규칙은 [`docs/DOCUMENTATION_POLICY.md`](docs/DOCUMENTATION_POLICY.md)를 기준으로 합니다.

---

## 2. 현재 상태

| Milestone | 상태 | 핵심 결과 |
|---|---|---|
| M0 | DONE | Jira 수집, RAW 보존, Issue/Comment/Structure ANALYSIS |
| M1 | DONE | Issue별 Knowledge Input 30 package, `source_hash` |
| M2 | DONE | Knowledge Schema v0.1, Extraction Skill v0.9 |
| M3 | DONE | Orchestrator → Worker → Validator → Reviewer |
| M4 | DONE | 실제 Jira 30/30 최종 PASS, Human Validation 5/5 |
| M5 | DONE | Knowledge 285 items, Evidence 503 refs, Review 37 files |
| M6 | DONE | Version/ID/Attempt/Active/History/Evidence Logical Contract |
| M7 | **CURRENT** | SQLite Schema/Loader/Integrity 구현 완료, 실제 30건 검증 대기 |
| M8 | BLOCKED | M7 real-run Gate 후 Chunk/BGE-M3 검토 |

전체 M0~M16 로드맵은 [현재 상태와 향후 계획](docs/status/jira_knowledge_db_current_status.html)을 기준으로 합니다.

---

## 3. 실제 파일럿 근거

실제 Jira 업무 원문은 Git에 기록하지 않고 aggregate 값만 남깁니다.

```text
Issue                         30
Comment                      278
Attachment metadata           79
Canonical Relationship         6
Custom Field Catalog         220
Custom Field Values          447

Knowledge Item               285
Evidence Ref                 503
Review JSON                   37
Final PASS                 30/30
```

Review 최종 Attempt:

```text
Attempt 1 PASS               24
Attempt 2 PASS                5
Attempt 3 PASS                1
재생성 Issue                  6
```

이 37개 Review Attempt는 M6/M7에서 `knowledge_attempt` history의 직접 근거가 됩니다.

---

## 4. 데이터 계층

### [RAW]

```text
data/raw/runs/<run_id>/...
```

Jira API 응답을 보존하는 사실 기준 계층입니다.

### [ANALYSIS]

```text
data/analysis/<run_id>/
├─ issues.jsonl
├─ comments.jsonl
├─ attachments.jsonl
├─ issue_relationships.jsonl
├─ custom_field_catalog.jsonl
├─ custom_field_values.jsonl
└─ summary.json
```

RAW를 LLM 없이 결정적으로 정규화합니다.

### [KNOWLEDGE INPUT]

```text
data/knowledge_input/runs/<run_id>/
├─ issues/<ISSUE_KEY>.json
├─ package_warnings.jsonl
└─ manifest.json
```

Issue 단위 최종 사실 입력입니다.

```text
Issue Package
├─ issue
├─ comments[]
├─ attachments[]
├─ relationships[]
├─ custom_fields[]
└─ source_hash
```

`source_hash`는 의미 데이터 기반 canonical SHA-256이며 Issue Version 변경 판단 기준입니다.

```text
source_hash unchanged
→ existing issue_version 재사용

source_hash changed
→ new issue_version
```

### [KNOWLEDGE / REVIEW]

```text
data/knowledge/runs/<run_id>/
├─ issues/<ISSUE_KEY>.json
└─ reviews/<ISSUE_KEY>.review.attempt<N>.json
```

Knowledge Schema v0.1:

```text
issue_summary
problem_or_goal[]
key_findings[]
actions_and_decisions[]
outcomes[]
open_items[]
```

각 item:

```text
statement
evidence_refs[]
```

Evidence type:

```text
summary
description
comment:<id>
attachment:<id>
relationship:<id>
custom_field:<id>
```

---

## 5. M6 최종 DB 논리 구조

M6-01~03을 거쳐 최종 구조는 다음으로 고정했습니다.

```text
Pipeline Run
   │
   └── Issue Version Observation
                │
Issue ── 1:N Issue Version
                │
                └── 1:N Knowledge Generation
                         │
                         └── 1:N Knowledge Attempt
                                  ├── 1:N Knowledge Item
                                  │        └── 1:N Knowledge Evidence
                                  └── 0..1 Knowledge Review
                                           └── 1:N Review Finding
```

### Issue identity

```text
jira_id
= authoritative Jira identity

issue_key
= human-readable / cross-layer locator
= 변경 가능
```

### Generation과 Attempt

`knowledge_generation`은 **Issue Version + Knowledge Contract에 대한 retry lineage**입니다.

```text
same issue_version + same contract
→ same knowledge_generation_id
```

실제 1차/2차/3차 재생성 회차는 `knowledge_attempt`입니다.

```text
Generation KG1
├─ Attempt 1 → KA1
├─ Attempt 2 → KA2
└─ Attempt 3 → KA3
```

따라서 재생성 회차까지 identity가 보존됩니다.

---

## 6. Deterministic ID 계층

M6-02에서 고정하고 M7 코드에 구현한 ID 계층입니다.

```text
jira_id
  ↓
issue_version_id           iv_
  = hash(jira_id + source_hash)

knowledge_contract_hash    kc_
  = hash(schema + skill + runtime + model_profile)

knowledge_generation_id    kg_
  = hash(issue_version_id + knowledge_contract_hash)

knowledge_attempt_id       ka_
  = hash(knowledge_generation_id + attempt_no)

knowledge_item_id          ki_
  = hash(knowledge_attempt_id + category + ordinal)

knowledge_evidence_id      ke_
  = hash(knowledge_item_id + ordinal + exact evidence_ref)
```

공통 canonicalization:

```text
id_schema_version = 1
entity kind 포함
JSON UTF-8
sort_keys=true
공백 제거 separators
SHA-256 full lowercase 64 hex
```

Timestamp는 ID material에 넣지 않습니다.

상세 결정은 [`docs/M6_DECISION_LOG.md`](docs/M6_DECISION_LOG.md), 최종 계약은 [`docs/DB_LOGICAL_SCHEMA.md`](docs/DB_LOGICAL_SCHEMA.md)를 참조합니다.

---

## 7. M7 SQLite 구현

현재 구현:

```text
src/jira_collector/knowledge_db/
├─ ids.py
├─ schema.py
├─ loader.py
├─ evidence.py
└─ models.py
```

실행 도구:

```text
tools/jira_knowledge/materialize_knowledge_db.py
```

SQLite 주요 table:

```text
pipeline_run
issue
issue_version
issue_version_observation
comment
attachment
relationship
custom_field_catalog
custom_field_value
knowledge_generation
knowledge_attempt
knowledge_item
knowledge_evidence
knowledge_review
review_finding
```

자동 테스트에서 확인한 것:

- 동일 Run 2회 materialize 시 row 증가 없음
- deterministic logical ID 유지
- historical failed Attempt 보존
- accepted Attempt Knowledge/Evidence 저장
- 6종 Evidence round-trip
- broken Evidence 시 transaction rollback
- Jira Issue당 active Generation 최대 1개 DB-level 강제
- GitHub Actions 전체 `pytest` PASS

남은 M7 Gate는 실제 `20260804T043628Z` 30건 materialization입니다.

예상 regression count:

```text
Issue               30
Generation          30
Attempt             37
Knowledge Item     285
Evidence            503
Review               37
```

실행법은 [`docs/M7_SQLITE_MATERIALIZATION.md`](docs/M7_SQLITE_MATERIALIZATION.md)를 기준으로 합니다.

---

## 8. Active / Historical 정책

```text
[DB]
Current + Historical Version/Generation/Attempt 보존

[기본 RAG / FAISS]
state=active Generation의 accepted Attempt만 사용

[History Retrieval]
감사 · 재현 · 변화 분석 · temporal query에서만 historical 사용
```

새 candidate가 생겼다는 이유만으로 기존 active를 내리지 않습니다.

```text
G1 active
G2 candidate

G2 PASS 전 → G1 active 유지
G2 PASS    → G1 historical / G2 active
```

---

## 9. Knowledge Quality Loop

```text
Orchestrator
    ↓
Fresh Worker
    ↓
Knowledge JSON
    ↓
Python Validator
    ↓
Fresh Defect Reviewer
    ↓
PASS / REGENERATE
    ↓
최대 3 Attempt
```

PASS:

```text
score >= 8.5
AND critical_error == false
AND major_issue_count == 0
```

M7에서는 Review Attempt를 `knowledge_attempt`에 연결해 감사 이력을 잃지 않습니다.

현재 M4 legacy artifact는 과거 failed Attempt의 Knowledge 본문을 저장하지 않았기 때문에:

```text
failed historical Attempt
→ Attempt / Review / Finding 보존
→ content_available=false

accepted final Attempt
→ Knowledge Item / Evidence 보존
→ content_available=true
```

없는 과거 Knowledge를 추정 생성하지 않습니다.

---

## 10. 주요 문서

### Current Source of Truth

- [현재 상태와 향후 계획](docs/status/jira_knowledge_db_current_status.html)
- [Pipeline 전체 아키텍처](docs/PIPELINE_OVERVIEW.md)
- [Jira Knowledge 관계 맵](docs/architecture/jira_data_relationship_map.html)
- [HTML 문서 Index](docs/index.html)
- [문서 동기화 정책](docs/DOCUMENTATION_POLICY.md)

### M6 / M7

- [M6 DB Logical Schema](docs/DB_LOGICAL_SCHEMA.md)
- [M6 Decision Log](docs/M6_DECISION_LOG.md)
- [M6 Completion](docs/status/M6_DB_LOGICAL_SCHEMA_COMPLETION.md)
- [M7 SQLite Materialization](docs/M7_SQLITE_MATERIALIZATION.md)

### 완료 기록

- [M0 Completion](docs/status/M0_JIRA_COLLECTION_ANALYSIS_COMPLETION.md)
- [M1 Completion](docs/status/M1_KNOWLEDGE_INPUT_COMPLETION.md)
- [M2 Completion](docs/status/M2_KNOWLEDGE_SCHEMA_SKILL_COMPLETION.md)
- [M3 Completion](docs/status/M3_KNOWLEDGE_QUALITY_LOOP_COMPLETION.md)
- [M4 Completion](docs/status/M4_KNOWLEDGE_EXTRACTION_COMPLETION.md)
- [M5 Completion](docs/status/M5_KNOWLEDGE_PROFILING_COMPLETION.md)
- [M6 Completion](docs/status/M6_DB_LOGICAL_SCHEMA_COMPLETION.md)

---

## 11. 설치 / 실행 환경

- Python 3.11 이상
- Jira Server/Data Center 또는 호환 REST API
- Windows PowerShell, Linux shell 또는 macOS shell

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Jira 설정은 `.env`와 `config/settings.yaml`을 사용합니다.

```yaml
jira:
  rate_limit:
    requests_per_minute: 20
    max_concurrency: 1
```

---

## 12. 주요 명령

Collector / Parser:

```text
python -m jira_collector.cli check-connection
python -m jira_collector.cli collect
python -m jira_collector.cli resume --run-id <RUN_ID>
python -m jira_collector.cli verify --run-id <RUN_ID>
python -m jira_collector.cli export-issues --run-id <RUN_ID>
python -m jira_collector.cli export-comments --run-id <RUN_ID>
python -m jira_collector.cli export-structure --run-id <RUN_ID>
python -m jira_collector.cli build-knowledge-input --run-id <RUN_ID>
```

M5 Profiling:

```text
python tools/jira_knowledge/profile_knowledge_run.py ...
```

M7 SQLite:

```bash
python tools/jira_knowledge/materialize_knowledge_db.py \
  --run-id 20260804T043628Z \
  --data-root data \
  --database data/knowledge_db/jira_knowledge.sqlite3 \
  --skill-version 0.9 \
  --runtime-version 0.9 \
  --model-profile <M4_MODEL_PROFILE>
```

---

## 13. 다음 단계

현재는 **M7 real-run validation**에서 멈춥니다.

```text
M7 실제 30건 materialize
→ M5 count 일치 확인
→ 동일 Run 2회 실행 idempotency 확인
→ active=30 / review_required=0
→ Evidence failure=0
→ M7 Gate PASS
```

그 뒤에만:

```text
M8 Knowledge Item / Chunk 전략 검증
→ BGE-M3 Embedding
→ M9 FAISS Active Retrieval
→ M10 Evidence Builder + MCP
```

M10이 Functional MVP 완료선입니다.
