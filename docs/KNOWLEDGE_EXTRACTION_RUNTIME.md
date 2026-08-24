# Knowledge Extraction Runtime v0.9

이 문서는 M4 실제 Jira Knowledge Extraction에서 사용하는 OpenCode 실행 계약과 실제 실행 기록을 함께 보존한다.

M4의 목적은 이미 로컬에 고정된 `[KNOWLEDGE INPUT]`에서 검색용 `[KNOWLEDGE]`를 생성하고, Validator / Defect Reviewer / Human Validation으로 품질을 확인하는 것이다. **M4는 Jira 수집 단계가 아니다.**

## 1. 현재 상태

기준 Run:

```text
20260804T043628Z
```

현재까지 확인된 상태:

- `[KNOWLEDGE INPUT]` 실제 Jira Issue package 30건 준비 완료
- `manifest.status == completed`
- package warning 0
- 실제 30건 Knowledge 생성 완료
- Issue별 Worker → Validator → Defect Reviewer 순차 Loop 실행 완료
- 최종 Issue 상태 30/30 PASS
- REVIEW_REQUIRED / INPUT_ERROR 없음
- 초기 LLM 최종 보고에서 재생성/Critical/Major 집계 불일치 발견
- 집계를 `summarize_knowledge_run.py`의 deterministic 계산으로 교체
- Human Validation 진행 중
- 대표 1건 수동 확인에서 검색 의미를 해치는 품질 문제는 발견되지 않음
- M4 Gate는 Human Validation 총 5건 확인 후 판정

초기 LLM 보고의 세부 집계 수치는 내부 정합성 문제가 있었으므로 **정식 통계로 사용하지 않는다.** 기존 Knowledge/Review 산출물은 다시 생성할 필요가 없으며 deterministic summarizer로 다시 계산한다.

## 2. 설치 위치

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

tools/
└─ jira_knowledge/
   ├─ validate_knowledge.py
   └─ summarize_knowledge_run.py

.ignore
.gitignore
```

## 3. 데이터 계층

```text
[KNOWLEDGE INPUT]
data/knowledge_input/runs/<run_id>/issues/<ISSUE_KEY>.json

[KNOWLEDGE]
data/knowledge/runs/<run_id>/issues/<ISSUE_KEY>.json

[KNOWLEDGE REVIEW]
data/knowledge/runs/<run_id>/reviews/<ISSUE_KEY>.review.attempt<N>.json
```

Knowledge는 사실 원장이 아니다. 최종 사실 확인은 Evidence reference를 통해 다음 방향으로 돌아간다.

```text
[KNOWLEDGE]
    ↓ evidence_refs
[KNOWLEDGE INPUT]
    ↓
[ANALYSIS]
    ↓
[RAW]
```

## 4. M4 Local Input Boundary

M4 Knowledge Extraction에서는 지정된 로컬 `[KNOWLEDGE INPUT]` JSON이 유일한 사실 입력이다.

```text
Jira REST API / Jira Web / Jira MCP
        ↑
        │ M0 수집 단계에서만 사용
────────┼────────────────────────────
        │
      [RAW]
        ↓
   [ANALYSIS]
        ↓
[KNOWLEDGE INPUT]  ← M4의 유일한 사실 입력
        ↓
     Worker
        ↓
   [KNOWLEDGE]
```

M4 Agent는 다음 행위를 하지 않는다.

- Jira 웹사이트 접근
- Jira REST API 호출
- Jira MCP/Connector/Custom Tool 호출
- Issue Key로 외부 Jira 재조회
- webfetch/websearch 사용
- curl/wget/requests 등 네트워크 호출
- Input에 포함된 URL 재접근
- Knowledge Input에 없는 사실을 외부에서 보충

입력 파일이 없거나 읽을 수 없으면 Jira에서 다시 가져오지 않고 `INPUT_ERROR`로 종료한다.

### Permission 원칙

```text
Orchestrator
  default deny
  → glob/list
  → jira-knowledge-worker task
  → jira-knowledge-reviewer task
  → summarize_knowledge_run.py 실행만 bash 허용

Worker
  default deny
  → local read/edit
  → jira-knowledge-extraction Skill
  → validate_knowledge.py 실행만 bash 허용

Reviewer
  default deny
  → local read/edit
```

## 5. 실행 구조

```text
Jira Knowledge Orchestrator
        │ 파일 경로와 상태만 관리
        ▼
새 Worker · Issue 1건
        │
        ├─ Skill v0.9
        ├─ Knowledge JSON 생성
        └─ Python Validator
                │
                ├─ FAIL → 같은 Worker에서 구조 수정/재검증
                └─ PASS
                     ▼
               새 Defect Reviewer
                     │
                     ├─ PASS
                     └─ REGENERATE
                           ▼
                       새 Worker

최대 3 Attempt
→ 이후에도 실패하면 REVIEW_REQUIRED

모든 Issue 종료
→ summarize_knowledge_run.py
→ deterministic 최종 보고
```

한 Issue가 PASS 또는 REVIEW_REQUIRED가 되기 전에는 다음 Issue로 이동하지 않는다. Worker/Reviewer 병렬 호출은 하지 않는다.

## 6. Agent 역할

### Orchestrator

- Jira/Knowledge 본문을 직접 읽지 않는다.
- Input/Output/Review 경로와 짧은 상태만 관리한다.
- Issue를 반드시 순차 처리한다.
- Jira 웹/API/MCP/Connector에 접근하지 않는다.
- Input 파일이 없으면 외부 재수집 없이 `INPUT_ERROR`로 종료한다.
- **최종 통계를 직접 세지 않는다.**
- 최종 보고는 `summarize_knowledge_run.py` 결과만 사용한다.

### Worker

- Knowledge Input JSON 한 건만 처리한다.
- `jira-knowledge-extraction` Skill v0.9를 반드시 사용한다.
- 생성 직후 Python Validator를 실행한다.
- Validator FAIL이면 같은 Worker에서 구조 오류를 수정한다.
- REGENERATE 시 원본 Input과 이전 Review JSON을 읽고 전체 Knowledge를 다시 만든다.
- Jira 웹/API/MCP/Connector에 접근하지 않는다.

### Defect Reviewer

- 현재 Input 한 건과 Knowledge 한 건만 비교한다.
- 점수를 먼저 정하지 않는다.
- Fact → Causal Claim → Evidence → Classification → Missing Knowledge → Duplication/Low-value 순으로 Audit한다.
- Reviewer score는 품질 인증값이 아니라 결함 감소용 보조 지표다.

## 7. Validator와 PASS 조건

Validator:

```bash
python tools/jira_knowledge/validate_knowledge.py \
  <KNOWLEDGE_OUTPUT> \
  <KNOWLEDGE_INPUT>
```

검증 범위:

- 최상위 필드 계약
- `knowledge_schema_version == 0.1`
- Input/Output `issue_key` 일치
- `statement` / `evidence_refs` 구조
- Evidence reference 형식과 Input 내 존재 여부

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

빈 배열은 Schema상 정상이다. 예를 들어 `problem_or_goal=[]`이어도 `issue_summary`와 다른 Knowledge 항목에 문제/목표와 핵심 맥락이 충분히 보존되어 있다면 그 자체로 품질 오류가 아니다. Human Validation에서는 개별 필드 채움률보다 **검색 의미 보존 여부**를 우선한다.

## 8. 결정론적 Run 집계

여러 Issue를 처리한 뒤에는 LLM이 대화 이력을 보고 통계를 직접 계산하지 않는다.

```bash
python tools/jira_knowledge/summarize_knowledge_run.py \
  <KNOWLEDGE_INPUT_DIR> \
  <KNOWLEDGE_OUTPUT_DIR> \
  <KNOWLEDGE_REVIEW_DIR>
```

현재 Run:

```bash
python tools/jira_knowledge/summarize_knowledge_run.py \
  data/knowledge_input/runs/20260804T043628Z/issues \
  data/knowledge/runs/20260804T043628Z/issues \
  data/knowledge/runs/20260804T043628Z/reviews
```

집계 정의:

```text
1차/2차/3차 PASS
= 최종 PASS가 된 attempt 번호

재생성 발생 Issue
= 최종 attempt >= 2

Critical 발생 Issue
= 어느 attempt에서든 critical_error=true 또는 critical_issues 존재

Major 발생 Issue
= 어느 attempt에서든 major_issue_count>0 또는 major_issues 존재
```

Critical/Major는 최종 상태가 아니라 Run의 결함 이력이다. 초기 Attempt에서 결함이 발생했지만 재생성으로 수정되어 PASS해도 발생 Issue에 포함한다.

집계 도구는 입력 수, Knowledge 존재, Review parse 오류, 중복 issue_key, 미완료 Issue, 전체 건수 정합성을 함께 확인한다. 정합성이 깨지면 Orchestrator는 숫자를 추정하지 않고 `REPORT_ERROR`로 취급한다.

### 왜 추가했는가

2026-08-24 실제 30건 실행에서 Knowledge 생성은 정상 완료됐지만 LLM 최종 보고의 Attempt/PASS/Critical/Major 집계가 서로 맞지 않았다. 이는 Knowledge Extraction 품질 문제가 아니라 **집계 책임을 LLM에게 둔 구조적 문제**였다.

따라서 의미 판단은 LLM에 남기고 단순 집계는 deterministic code로 이동했다.

## 9. `.gitignore`와 OpenCode 파일 탐색

실제 Jira 데이터는 Git에 올리지 않기 위해 `.gitignore`에서 `data/` 전체를 제외한다.

```text
# .gitignore
data/
```

OpenCode의 Glob/Grep 탐색도 ignore 규칙을 따르기 때문에 다건 실행에서 실제 파일이 존재해도 Glob 결과가 0건처럼 보일 수 있었다. 1건 Smoke Test는 정확한 경로를 직접 `read`해 성공했지만, 다건 실행 전 Orchestrator가 Glob으로 목록을 찾으면서 문제가 드러났다.

해결:

```text
# .ignore
!data/
data/*

!data/knowledge_input/
!data/knowledge_input/**

!data/knowledge/
!data/knowledge/**
```

효과:

- Git: `data/` 전체 계속 제외
- OpenCode/ripgrep: `knowledge_input`과 `knowledge`만 탐색 가능
- `reports`, `state` 등은 계속 탐색 제외

정확한 경로의 `read`는 성공하는데 `Glob "data/knowledge_input/.../*"`가 0건이면 파일 부재나 Windows 문제를 바로 단정하지 말고 프로젝트 CWD와 `.gitignore` / `.ignore`를 먼저 확인한다.

## 10. M4 Prompt Runbook

원칙은 **stable rule은 Agent/Skill에 두고 Prompt는 이번 실행 변수만 전달**하는 것이다.

### 10.1 1건 Smoke Test용 패턴

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

### 10.2 2026-08-24 실제 30건 실행에 입력한 프롬프트

아래 프롬프트로 실제 30건 Knowledge 생성이 수행됐다.

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

모든 처리가 끝나면 다음만 요약해줘.
- 전체 Issue 수
- PASS 수
- 재생성 발생 Issue 수
- REVIEW_REQUIRED 수
- 실패/INPUT_ERROR 수
- Issue별 최종 상태와 generation attempt 수
```

이 프롬프트로 30건 생성 자체는 완료했으나 마지막 통계를 LLM이 직접 계산하면서 집계 불일치가 발생했다. 따라서 위 프롬프트는 **실행 이력 보존용**이다.

### 10.3 현재 권장 30건 실행 프롬프트

```text
jira-knowledge-orchestrator v0.9로 M4 실제 Jira Knowledge Extraction 전체 30건을 수행해줘.

RUN_ID: 20260804T043628Z

[KNOWLEDGE INPUT]
data/knowledge_input/runs/20260804T043628Z/issues

[KNOWLEDGE OUTPUT]
data/knowledge/runs/20260804T043628Z/issues

[KNOWLEDGE REVIEW]
data/knowledge/runs/20260804T043628Z/reviews

INPUT의 30건 전체를 기존 Agent 규칙대로 순차 처리해줘.
최종 보고는 LLM이 직접 집계하지 말고 deterministic run summarizer 결과만 사용해줘.
```

Local-only, 순차 처리, Worker/Reviewer, 최대 3 Attempt, PASS 기준, 외부 Jira 금지는 Prompt에 길게 반복하지 않는다. 이 규칙들은 Agent/Skill의 책임이다.

### 10.4 기존 산출물의 집계만 다시 실행

Knowledge/Review 30건이 이미 존재하면 재생성하지 않는다.

```powershell
python tools/jira_knowledge/summarize_knowledge_run.py `
  data/knowledge_input/runs/20260804T043628Z/issues `
  data/knowledge/runs/20260804T043628Z/issues `
  data/knowledge/runs/20260804T043628Z/reviews
```

## 11. Human Validation

자동 Review PASS 후에도 최소 5건은 사람이 `[KNOWLEDGE INPUT]`과 최종 `[KNOWLEDGE]`를 직접 대조한다. Jira 원문을 외부에 공유할 필요는 없고, 내부에서 확인한 체크 결과만 기록한다.

```text
- 사실 왜곡: 없음 / 있음
- 과도한 인과 확정: 없음 / 있음
- 중요한 정보 누락: 없음 / 있음
- 분류 오류: 없음 / 있음
- evidence 추적 가능: 예 / 아니오
- 검색용 Knowledge로 사용 가능: 예 / 아니오
- 비고
```

선정은 단순 랜덤보다 다음 유형을 섞는다.

- 재생성 횟수가 많았던 어려운 Issue
- Critical/Major 이력이 있었던 Issue
- 1차 PASS지만 threshold에 가까운 Issue
- 일반적인 1차 PASS Issue
- 구조적으로 특이한 Issue

### 빈 배열 판단

`problem_or_goal`, `outcomes`, `open_items` 등은 비어 있을 수 있다. 선택 필드가 비어 있어도 `issue_summary`와 다른 항목에 핵심 의미가 충분히 보존되면 정상이다.

모든 배열을 강제로 채우면 중복이나 hallucination을 유발할 수 있으므로 **필드 채움률 자체를 품질 목표로 사용하지 않는다.**

## 12. M4 Gate

M4 완료 조건:

- 실제 Jira 30건 Knowledge 생성 완료
- Review Loop 완료
- deterministic Run 집계 정합성 확인
- 대표 5건 Human Validation 완료
- 반복적 사실 반전 또는 검색 의미를 바꾸는 심각한 인과 왜곡 없음
- 중요한 지식 누락이 반복적으로 나타나지 않음
- evidence_refs로 원문 위치 추적 가능
- Knowledge가 검색용 의미 압축으로 충분함

M4 Gate 통과 후 M5 Knowledge/Review Profiling으로 이동한다.

M5에서는 실제 결과를 대상으로 Issue당 item 수, category별 item 수, statement 길이 p50/p95/max, evidence 수, empty array 비율, Review attempt/Critical/Major 분포와 이상치를 측정한다. DB Schema와 Chunk 정책은 이 실제 분포를 본 뒤 결정한다.

## 13. M4 실행 전 체크리스트

- [ ] 프로젝트 루트에서 OpenCode를 시작한다.
- [ ] Knowledge Input Run ID를 확인한다.
- [ ] `manifest.status == completed`를 확인한다.
- [ ] package warning이 없는지 확인한다.
- [ ] Issue JSON 수와 중복 issue_key를 확인한다.
- [ ] `.ignore`로 Knowledge Input이 Glob에서 정상 노출되는지 확인한다.
- [ ] Skill/Agent/Validator/Summarizer가 존재한다.
- [ ] Agent가 `"*": deny`와 local-only 경계를 적용한다.
- [ ] 실제 출력 경로를 합성 테스트 결과와 분리한다.
- [ ] 최종 Run 보고는 deterministic summarizer 결과를 사용한다.

## 14. 금지사항

- Orchestrator가 Jira/Knowledge 본문을 직접 읽지 않는다.
- 한 Context에 30개 Issue 본문을 모두 적재하지 않는다.
- Worker/Reviewer를 배치 병렬 실행하지 않는다.
- Reviewer 점수만으로 Knowledge를 사실 원장처럼 신뢰하지 않는다.
- 합성 데이터의 Gold/expected를 실제 M4 실행에 사용하지 않는다.
- 실제 Jira와 합성 테스트 출력 경로를 섞지 않는다.
- Jira 웹/API/MCP/Connector를 M4에서 다시 사용하지 않는다.
- 입력이 없다고 외부 Jira에서 재수집하지 않는다.
- 최종 Run 통계를 LLM이 직접 다시 세거나 추정하지 않는다.
- 모든 Knowledge 배열을 강제로 채우지 않는다.
