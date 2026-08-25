# Knowledge Extraction Runtime v0.9

기준 Runtime: **M4 Historical Runtime Contract**  
현재 프로젝트 위치: **M7 · SQLite Materialization — IMPLEMENTED / REAL-RUN VALIDATION PENDING**

이 문서는 M4 실제 Jira Knowledge Extraction에서 사용한 OpenCode 실행 계약과 당시 문제/해결/실행 기록을 보존한다.

> 이 문서의 Worker/Reviewer/Prompt/Attempt 내용은 M4를 재현하기 위한 historical runtime 기록이다. 현재 전체 구조와 Milestone 상태는 `README.md`, `docs/PIPELINE_OVERVIEW.md`, `docs/status/jira_knowledge_db_current_status.html`을 따른다.

---

## 1. M4 완료 상태

기준 Run:

```text
20260804T043628Z
```

실제 결과:

```text
Knowledge Input package       30
Knowledge                     30
Final PASS                    30
First-pass PASS               24
Second-pass PASS               5
Third-pass PASS                1
Regenerated Issue              6
Review JSON                   37
INPUT_ERROR                    0
REVIEW_REQUIRED                0
INCOMPLETE                     0
Human Validation             5/5
```

초기 LLM 최종 보고에서 Attempt/PASS/Critical/Major 집계 불일치가 발견되어, 최종 통계 책임을 deterministic `summarize_knowledge_run.py`로 옮겼다.

M4 Gate:

## **PASS / DONE**

완료 기록:

```text
docs/status/M4_KNOWLEDGE_EXTRACTION_COMPLETION.md
```

이후 M5 Profiling과 M6 Logical Schema가 완료됐으며 현재는 M7 실데이터 Gate를 검증한다.

---

## 2. M4 데이터 경계

```text
[KNOWLEDGE INPUT]
data/knowledge_input/runs/<run_id>/issues/<ISSUE_KEY>.json

[KNOWLEDGE]
data/knowledge/runs/<run_id>/issues/<ISSUE_KEY>.json

[KNOWLEDGE REVIEW]
data/knowledge/runs/<run_id>/reviews/<ISSUE_KEY>.review.attempt<N>.json
```

Knowledge는 사실 원장이 아니다.

```text
KNOWLEDGE
  ↓ evidence_refs
KNOWLEDGE INPUT
  ↓
ANALYSIS
  ↓ source_path
RAW
```

M4의 유일한 사실 입력은 지정된 로컬 Knowledge Input이다.

```text
Jira REST / Jira Web / Jira MCP
        ✕ M4에서 접근하지 않음

RAW
 ↓
ANALYSIS
 ↓
KNOWLEDGE INPUT
 ────────────── M4 fact boundary
 ↓
Worker
 ↓
KNOWLEDGE
```

금지:

- Jira Web / REST / MCP 재조회
- webfetch / websearch
- curl / wget / requests 네트워크 호출
- Input URL 재접근
- Input에 없는 사실 보충

Input 파일이 없으면 Jira에서 다시 가져오지 않고 `INPUT_ERROR`로 종료한다.

---

## 3. 설치 구조

```text
.opencode/
├─ agents/
│  ├─ jira-knowledge-orchestrator.md
│  ├─ jira-knowledge-worker.md
│  └─ jira-knowledge-reviewer.md
└─ skills/
   └─ jira-knowledge-extraction/
      ├─ SKILL.md
      ├─ CHANGELOG.md
      └─ references/
         ├─ knowledge.schema.json
         ├─ output-example.json
         ├─ review.schema.json
         └─ review-example.json

tools/jira_knowledge/
├─ validate_knowledge.py
├─ summarize_knowledge_run.py
└─ profile_knowledge_run.py
```

---

## 4. Runtime 실행 구조

```text
Jira Knowledge Orchestrator
        │ 경로와 상태만 관리
        ▼
Fresh Worker · Issue 1건
        │
        ├─ Skill v0.9
        ├─ Knowledge JSON 생성
        └─ Python Validator
                │
                ├─ FAIL → 같은 Worker에서 구조 수정/재검증
                └─ PASS
                     ▼
               Fresh Defect Reviewer
                     │
                     ├─ PASS
                     └─ REGENERATE
                           ▼
                       Fresh Worker

최대 3 Attempt
→ 이후에도 실패하면 REVIEW_REQUIRED
```

한 Issue가 끝나기 전에는 다음 Issue로 넘어가지 않는다. Worker/Reviewer 병렬 실행은 하지 않는다.

### 현재 M6/M7에서 이 Attempt의 의미

M6-02에서 M4의 1/2/3차 회차를 DB의 별도 Entity로 명시했다.

```text
Knowledge Generation · kg_
└── Knowledge Attempt · ka_
    ├── attempt_no = 1
    ├── attempt_no = 2
    └── attempt_no = 3
```

따라서 이 문서의 `Attempt N`은 M7 `knowledge_attempt`에 직접 대응한다.

---

## 5. Agent 역할

### Orchestrator

- 본문을 직접 읽지 않는다.
- Input/Output/Review 경로와 짧은 상태만 관리한다.
- Issue를 순차 처리한다.
- 외부 Jira에 접근하지 않는다.
- 최종 통계를 직접 계산하지 않는다.
- `summarize_knowledge_run.py` 결과만 최종 집계로 사용한다.

### Worker

- Knowledge Input 한 건만 처리한다.
- `jira-knowledge-extraction` Skill v0.9 사용.
- 생성 직후 Python Validator 실행.
- Validator 구조 FAIL은 같은 Worker에서 수정.
- Reviewer REGENERATE 시 Fresh Worker가 원본 Input + 이전 Review를 읽고 Knowledge 전체를 다시 만든다.

### Defect Reviewer

- 현재 Input 한 건과 현재 Knowledge 한 건만 비교한다.
- 점수를 먼저 정하지 않는다.
- 다음 Audit 순서를 사용한다.

```text
Fact
→ Causal Claim
→ Evidence
→ Classification
→ Missing Knowledge
→ Duplication / Low-value
```

Reviewer score는 품질 인증서가 아니라 defect reduction을 위한 보조 지표다.

---

## 6. Validator / Review Gate

Validator:

```bash
python tools/jira_knowledge/validate_knowledge.py \
  <KNOWLEDGE_OUTPUT> \
  <KNOWLEDGE_INPUT>
```

검증:

- Knowledge 최상위 필드
- `knowledge_schema_version == 0.1`
- Input/Output `issue_key` 일치
- `statement` / `evidence_refs` 구조
- Evidence ref format과 Input 내 존재

Review PASS:

```text
score >= 8.5
AND critical_error == false
AND major_issue_count == 0
```

Hard cap:

```text
Critical >= 1 → score <= 7.9
Major >= 1    → score <= 8.4
```

빈 Knowledge category는 정상일 수 있다. 모든 배열을 강제로 채우면 중복/hallucination을 유발할 수 있으므로 채움률 자체를 목표로 사용하지 않는다.

---

## 7. Deterministic Run Summary

명령:

```bash
python tools/jira_knowledge/summarize_knowledge_run.py \
  <KNOWLEDGE_INPUT_DIR> \
  <KNOWLEDGE_OUTPUT_DIR> \
  <KNOWLEDGE_REVIEW_DIR>
```

실제 Run:

```bash
python tools/jira_knowledge/summarize_knowledge_run.py \
  data/knowledge_input/runs/20260804T043628Z/issues \
  data/knowledge/runs/20260804T043628Z/issues \
  data/knowledge/runs/20260804T043628Z/reviews
```

정의:

```text
1차/2차/3차 PASS
= 최종 PASS가 된 attempt 번호

재생성 Issue
= final attempt >= 2

Critical 발생 Issue
= 어느 attempt에서든 critical_error 또는 critical issue 존재

Major 발생 Issue
= 어느 attempt에서든 major_issue_count > 0 또는 major issue 존재
```

실제 결과:

```text
target_issue_count      = 30
first_pass_count        = 24
second_pass_count       = 5
third_pass_count        = 1
regenerated_issue_count = 6
review_required_count   = 0
incomplete_count        = 0
```

```text
24 + 5 + 1 = 30
5 + 1 = regenerated 6
```

---

## 8. `.gitignore` / OpenCode 탐색 문제

실제 Jira 데이터는 Git에서 제외한다.

```text
.gitignore
→ data/
```

OpenCode Glob/Grep도 ignore rule을 따라 실제 파일이 있어도 0건처럼 보이는 문제가 있었다.

해결:

```text
.ignore

!data/
data/*

!data/knowledge_input/
!data/knowledge_input/**

!data/knowledge/
!data/knowledge/**
```

효과:

- Git에는 실제 data를 올리지 않음.
- OpenCode는 Knowledge Input/Knowledge를 탐색 가능.
- 정확한 path read는 되는데 Glob 결과가 0이면 CWD와 ignore rule을 먼저 확인한다.

---

## 9. M4 실행 프롬프트 이력

### 1건 Smoke Test 패턴

```text
jira-knowledge-orchestrator v0.9로 M4 실제 Jira Knowledge Extraction 1건을 수행해줘.

[KNOWLEDGE INPUT]
data/knowledge_input/runs/20260804T043628Z/issues/<ISSUE_KEY>.json

[KNOWLEDGE OUTPUT]
data/knowledge/runs/20260804T043628Z/issues/<ISSUE_KEY>.json

[KNOWLEDGE REVIEW]
data/knowledge/runs/20260804T043628Z/reviews

지정한 로컬 INPUT FILE만 사용해 기존 Agent 규칙대로 처리하고 최종 상태만 요약해줘.
```

### 실제 30건 실행 프롬프트

```text
jira-knowledge-orchestrator v0.9로 M4 실제 Jira Knowledge Extraction 전체 30건을 수행해줘.

[KNOWLEDGE INPUT]
data/knowledge_input/runs/20260804T043628Z/issues

[KNOWLEDGE OUTPUT]
data/knowledge/runs/20260804T043628Z/issues

[KNOWLEDGE REVIEW]
data/knowledge/runs/20260804T043628Z/reviews

INPUT 폴더의 Issue JSON 30건 전체를 순차 처리해줘.
처리 시작 전에 입력 JSON이 정확히 30건인지 확인하고,
30건이 아니면 실행하지 말고 INPUT_ERROR로 알려줘.
```

이 프롬프트 실행 자체는 성공했으나 최종 통계를 LLM이 직접 계산한 보고에서 불일치가 발생했다. 이후 최종 집계를 deterministic summarizer로 고정했다.

현재 권장 방식:

```text
RUN_ID와 local INPUT/OUTPUT 경로만 Prompt로 전달하고,
stable rule은 Agent/Skill에 둔다.
최종 보고는 deterministic summarizer 결과만 사용한다.
```

---

## 10. Human Validation

자동 PASS 뒤 5건을 사람이 Knowledge Input과 최종 Knowledge로 대조했다.

확인 항목:

- 사실 왜곡
- 과도한 인과 확정
- 중요한 정보 누락
- 분류 오류
- Evidence 추적 가능성
- 검색 Knowledge 사용 가능성

실제 결과:

```text
5 / 5 완료
검색 의미를 해치는 문제 발견 없음
```

---

## 11. M4 Gate

- [x] 실제 30건 Knowledge 생성
- [x] Review Loop
- [x] deterministic summary 정합성
- [x] Human Validation 5/5
- [x] Evidence 원문 추적
- [x] 반복적 사실 반전/심각한 인과 왜곡 없음

## **M4 Gate: PASS / DONE**

---

## 12. 현재 프로젝트와의 연결

M4 Runtime의 산출물은 이후 다음처럼 이어졌다.

```text
M4
30 Knowledge + 37 Review Attempts
  ↓
M5
285 Knowledge Items + 503 Evidence profile
  ↓
M6
Issue Version / Generation / Attempt / deterministic ID contract
  ↓
M7
SQLite Schema v1 / loader / Evidence resolver
```

현재 authoritative ID 계층:

```text
jira_id → iv_ → kc_ → kg_ → ka_(attempt_no) → ki_ → ke_
```

M7 실제 30건 materialization이 통과하면 M8 Chunk/BGE-M3로 이동한다.

현재 문서:

```text
docs/DB_LOGICAL_SCHEMA.md
docs/M6_DECISION_LOG.md
docs/M7_SQLITE_MATERIALIZATION.md
docs/status/jira_knowledge_db_current_status.html
```
