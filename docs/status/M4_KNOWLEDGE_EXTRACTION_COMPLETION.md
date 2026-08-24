# M4 Knowledge Extraction Completion Record

기준일: 2026-08-24  
기준 Run: `20260804T043628Z`

이 문서는 M4 실제 Jira Knowledge Extraction 단계의 **완료 시점 산출물과 검증 결과를 고정 기록**한다.

프로젝트의 문서는 단계가 진행될 때 이전 내용을 지우는 방식이 아니라, **당시의 입력·판단·문제·해결·결과를 단계별 산출물로 누적 보존**한다. 이후 구현 변경으로 기존 설명이 명백히 틀린 경우에만 정정하고, 유효한 실행 이력과 의사결정은 남긴다.

---

## 1. M4 목적

이미 로컬에 고정된 `[KNOWLEDGE INPUT]`을 대상으로 검색용 `[KNOWLEDGE]`를 생성하고, 다음 품질 루프가 실제 Jira 데이터에서도 안정적으로 동작하는지 확인한다.

```text
[KNOWLEDGE INPUT]
    ↓
Fresh Worker + Skill v0.9
    ↓
[KNOWLEDGE]
    ↓
Python Validator
    ↓
Fresh Defect Reviewer
    ↓
PASS / REGENERATE
    ↓
최대 3 Attempt
    ↓
Deterministic Run Summary
    ↓
Human Validation
```

M4는 Jira 수집 단계가 아니다. 외부 Jira Web/API/MCP/Connector를 다시 사용하지 않고 로컬 Knowledge Input만 사실 입력으로 사용한다.

---

## 2. 입력

```text
[KNOWLEDGE INPUT]
data/knowledge_input/runs/20260804T043628Z/issues
```

확인된 Preflight:

- Issue package: 30건
- `manifest.status == completed`
- package warning: 0
- JSON parse 정상
- 중복 issue_key 없음

---

## 3. 실제 30건 실행 프롬프트

아래 프롬프트로 실제 30건 Knowledge Extraction을 수행했다.

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

이 프롬프트로 Knowledge/Review 생성 자체는 정상 완료됐다. 다만 마지막 Run 통계를 LLM이 직접 계산하면서 집계 불일치가 발견됐고, 이후 deterministic summarizer로 집계 책임을 이동했다.

현재 재실행 시 권장 프롬프트와 전체 Prompt Runbook은 `docs/KNOWLEDGE_EXTRACTION_RUNTIME.md`를 기준으로 한다.

---

## 4. M4 실행 중 발견한 문제와 해결

### 4.1 다건 입력 파일 Glob 실패

1건 Smoke Test는 정확한 파일 경로를 직접 `read`해 성공했지만, 다건 실행에서 Orchestrator의 Glob이 Knowledge Input을 찾지 못했다.

원인은 Windows 경로 형식이 아니라 `.gitignore`의 `data/` 제외 규칙을 OpenCode/ripgrep 탐색도 따르는 것이었다.

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

결과:

- Git에서는 실제 Jira `data/`가 계속 제외된다.
- OpenCode에서는 M4에 필요한 `knowledge_input` / `knowledge`만 탐색 가능하다.
- 기존 보안 경계는 유지된다.

### 4.2 LLM 최종 집계 오류

30건 생성 후 LLM 보고에서 PASS attempt 합계와 재생성 Issue 수, Critical/Major 분류 사이에 불일치가 발견됐다.

이는 Knowledge 생성 품질 문제가 아니라 **단순 집계를 LLM에게 맡긴 구조 문제**로 판단했다.

해결:

```text
tools/jira_knowledge/summarize_knowledge_run.py
```

Orchestrator는 이후 Run 통계를 직접 세지 않고 이 도구의 JSON 결과만 사용한다.

---

## 5. Deterministic 최종 집계

사용자가 실제 산출물에 대해 summarizer를 실행해 확인한 결과:

```text
target_issue_count      = 30
input_error_count       = 0
first_pass_count        = 24
second_pass_count       = 5
third_pass_count        = 1
review_required_count   = 0
incomplete_count        = 0
regenerated_issue_count = 6
```

정합성:

```text
24 + 5 + 1 = 30
2차 PASS 5건 + 3차 PASS 1건 = 재생성 Issue 6건
```

즉 전체 30건은 최대 3 Attempt 안에서 최종 PASS했고, 처리 실패·입력 오류·미완료·REVIEW_REQUIRED는 없었다.

초기 LLM 보고에서 숫자가 달랐던 항목은 정식 통계로 사용하지 않는다. M4 Run의 정식 집계 기준은 deterministic summarizer 결과다.

---

## 6. Human Validation

자동 Reviewer PASS만으로 M4를 종료하지 않고 대표 5건을 사람이 직접 `[KNOWLEDGE INPUT]`과 최종 `[KNOWLEDGE]`로 대조했다.

검토 기준:

```text
- 사실 왜곡
- 과도한 인과 확정
- 중요한 정보 누락
- 분류 오류
- evidence 추적 가능 여부
- 검색용 Knowledge 사용 가능 여부
```

결과:

```text
Human Validation: 5 / 5 완료
품질 문제: 발견되지 않음
```

검토 중 `problem_or_goal=[]`처럼 선택 배열이 비어 있는 사례도 확인했다. 그러나 `issue_summary`에 문제, 원인 추정, 후속조치 등 핵심 검색 의미가 충분히 보존되어 있어 품질 문제로 판단하지 않았다.

따라서 M4에서의 품질 기준은 **모든 배열을 채우는 것**이 아니라 **전체 Knowledge가 원문의 검색 의미를 보존하고 Evidence로 추적 가능한가**이다.

---

## 7. M4 Gate 판정

M4 완료 조건과 결과:

- [x] 실제 Jira 30건 Knowledge 생성
- [x] Worker → Validator → Reviewer Loop 완료
- [x] 30/30 최종 PASS
- [x] `INPUT_ERROR = 0`
- [x] `REVIEW_REQUIRED = 0`
- [x] `INCOMPLETE = 0`
- [x] deterministic Run 집계 정합성 확인
- [x] 대표 5건 Human Validation 완료
- [x] Human Validation 5/5에서 검색 의미를 해치는 품질 문제 없음
- [x] Knowledge를 검색용 의미 압축 계층으로 사용 가능

## **M4 Gate: PASS / DONE**

다음 단계는 **M5 · Knowledge / Review Profiling**이다.

---

## 8. M4가 남긴 설계 결론

1. 사내 LLM의 성능 제약을 고려하면 Issue 단위 Fresh Context가 안정적이다.
2. 의미 추출은 LLM이 맡되 구조 검증과 통계 집계는 deterministic code로 분리한다.
3. Reviewer는 품질 인증서가 아니라 결함 감소용 2차 필터다.
4. Knowledge는 사실 원장이 아니라 검색용 의미 압축이다.
5. 최종 사실 확인은 `evidence_refs`를 통해 Knowledge Input / Analysis / Raw로 돌아간다.
6. 선택 배열의 empty 여부 자체를 품질 지표로 사용하지 않는다.
7. 실제 운영 규칙은 Agent/Skill에 두고 실행 Prompt는 짧게 유지한다.

---

## 9. M5 Handoff

M5에서는 실제 30건 Knowledge/Review 산출물을 대상으로 다음 분포를 측정한다.

- Issue당 Knowledge item 수
- category별 item 수
- statement 길이 p50 / p95 / max
- Evidence reference 수
- empty array 비율
- Review Attempt 분포
- Critical/Major 발생 이력 분포
- 이상치 Issue

DB Logical Schema와 Chunk 정책은 이 실제 Profiling 결과를 확인한 뒤 결정한다.
