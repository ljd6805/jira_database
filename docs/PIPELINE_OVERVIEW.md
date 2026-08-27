# Jira Knowledge Pipeline 전체 아키텍처

기준일: 2026-08-27  
현재 단계: **M0~M10 DONE / PASS**

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
```

## 2. 핵심 불변 원칙

```text
RAW → ANALYSIS → KNOWLEDGE → DB → EMBEDDING → RETRIEVAL → EVIDENCE PACKAGE
```

- RAW가 사실의 최종 기준이다.
- History Storage와 Active Retrieval을 분리한다.
- `knowledge_generation`과 retry `knowledge_attempt`를 구분한다.
- Identity는 `jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_`를 유지한다.
- `FAISS position ≠ embedding_id(emb_) ≠ knowledge_item_id(ki_)`다.
- MCP는 검색/근거 복원만 담당하고 생성형 LLM은 Agent에 둔다.

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

## 4. M9와 M10 역할 구분

```text
M9 Retrieval
질문 → BGE-M3 → FAISS → Top-3 Knowledge(ki_)

M10 Evidence/MCP
ki_ active/accepted 재검증
→ ke_ Evidence resolve
→ 실제 Jira source 복원
→ Evidence Package
→ MCP 2 tools

Agent / LLM
Knowledge + Evidence를 읽고 최종 답변
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

실제 M7 SQLite, M9 FAISS artifact, 사내 BGE-M3, MCP 2 tools를 연결했다.

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

쉬운 의미:

```text
tool_count 2          = MCP 기능 종류 2개, 호출 횟수가 아님
search_result_count 3 = FAISS Top-3 Knowledge
Evidence_count 6      = 3 Knowledge에 연결된 실제 Jira 근거 총 6개
warning_count 0       = 깨진 candidate 없음
path_leak_count 0     = 내부 경로 노출 없음
issue_lookup_ok true  = 실제 Issue 재조회 성공
failure_count 0       = Completion Gate 실패 없음
```

## 7. Real-run에서 실제로 해결한 환경 문제

1. `ModuleNotFoundError: No module named 'mcp'`
   - 현재 Python environment에 MCP SDK가 없어 발생.
   - `python -m pip install -e ".[dev]"`로 현재 interpreter에 dependency 설치.

2. `M10_REAL_RUN_QUERY 환경 변수가 비어 있습니다`
   - 실제 검색 질문이 설정되지 않아 발생.
   - Windows PowerShell에서는 `$env:M10_REAL_RUN_QUERY = Read-Host "M10 test query"` 사용.

3. `McpRuntimeSettingsError`
   - `JIRA_KNOWLEDGE_DB_PATH` 또는 `JIRA_RETRIEVAL_ARTIFACT_DIR`가 없거나 경로가 존재하지 않아 발생.
   - PowerShell `Test-Path` / `Resolve-Path`로 실제 artifact 경로를 확인해 설정.

상세한 트러블슈팅은 HTML 문서를 기준으로 한다.

## 8. 정식 서비스 Retrieval Update 방향

Pilot full rebuild와 운영 update를 분리한다.

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

이 후보들은 M10 완료 범위에 포함하지 않는다.

## 9. 보안 기록 원칙

실제 Query, Issue key, Jira 원문, 사내 endpoint/header/token, 로컬 절대경로는 공개 저장소에 기록하지 않는다. Real-run Completion에는 안전한 aggregate만 남긴다.

## 10. Current Source of Truth

```text
README.md
docs/index.html
docs/PIPELINE_OVERVIEW.html
docs/status/jira_knowledge_db_current_status.html
docs/status/M10_START_HERE.html
docs/status/M10_COMPLETION.html
docs/status/M10_REAL_RUN_GATE.html
docs/architecture/jira_data_relationship_map.*
```

다음 Milestone은 아직 정의하지 않는다. 운영화·Agent 연동·retrieval hardening 중 우선순위를 별도 의사결정한 뒤 경계를 정한다.
