# M5 Knowledge / Review Profiling Spec

기준일: 2026-08-24  
대상 Run: `20260804T043628Z`

이 문서는 M5에서 실제 Jira Knowledge / Review 산출물을 어떻게 측정할지 정의한다.

> 문서 보존 원칙: M4의 프롬프트, 문제 해결 기록, 완료 산출물은 삭제하지 않는다. M5는 그 위에 실제 분포 측정 결과를 추가한다.

## 1. 목적

M5의 목적은 Knowledge를 다시 생성하거나 품질 규칙을 튜닝하는 것이 아니다.

```text
M4 실제 Knowledge / Review 30건
        ↓
Deterministic Profiler
        ↓
크기 · 분포 · Empty · Evidence · Review 이력 · Outlier
        ↓
M6 DB Logical Schema
M8 Chunk 정책의 근거
```

M5에서는 **측정 → 분포 확인 → 이상치 확인**까지만 한다.
DB Schema, Chunk 크기, FAISS 구조는 아직 확정하지 않는다.

## 2. 입력

```text
[KNOWLEDGE]
data/knowledge/runs/20260804T043628Z/issues

[KNOWLEDGE REVIEW]
data/knowledge/runs/20260804T043628Z/reviews
```

Jira Web/API/MCP 또는 Knowledge Input 원문을 다시 읽을 필요가 없다.
M5 Profiler는 로컬 Knowledge와 Review JSON만 읽는다.

## 3. 실행 도구

```text
tools/jira_knowledge/profile_knowledge_run.py
```

실행:

```powershell
python tools/jira_knowledge/profile_knowledge_run.py `
  data/knowledge/runs/20260804T043628Z/issues `
  data/knowledge/runs/20260804T043628Z/reviews `
  --expected-issue-count 30 `
  --output data/knowledge/runs/20260804T043628Z/profile.json
```

성공 조건:

```text
integrity.ok == true
```

Profiler는 JSON을 stdout에도 출력하고 `--output`이 지정되면 동일 내용을 파일에 저장한다.

## 4. Knowledge Metric Contract

### 4.1 Issue / Item 크기

`total_statement_item_count`는 다음을 모두 포함한다.

```text
issue_summary 1개
+ problem_or_goal[]
+ key_findings[]
+ actions_and_decisions[]
+ outcomes[]
+ open_items[]
```

`array_item_count`는 `issue_summary`를 제외한 5개 배열 item 수다.

측정:

- Issue 수
- 전체 statement item 수
- Issue당 item 수: min / mean / p50 / p95 / max
- Issue당 array item 수: min / mean / p50 / p95 / max
- category별 전체 item 수
- category별 Issue당 item 분포

### 4.2 Empty Array

다음 5개 배열에 대해 측정한다.

- `problem_or_goal`
- `key_findings`
- `actions_and_decisions`
- `outcomes`
- `open_items`

각 category:

```text
empty_issue_count
empty_ratio
```

Empty ratio는 품질 점수가 아니다.
M4 Human Validation에서 확인했듯 선택 배열이 비어 있어도 전체 Knowledge에 검색 의미가 보존되면 정상이다.

### 4.3 Statement 길이

각 statement의 Unicode 문자 수를 Python `len()`으로 측정한다.

```text
statement_length_chars
  overall
  by_category
    count / min / mean / p50 / p95 / max
```

M5에서는 토큰 수를 추정하지 않는다.
정확한 BGE-M3 tokenizer 기반 token 분석은 M8에서 수행한다. 문자 수를 임의 token 수로 환산하지 않는다.

### 4.4 Evidence

각 item의 `evidence_refs` 수:

```text
evidence_refs_per_item
  overall
  by_category
```

Evidence type 분포:

```text
summary
description
comment
attachment
relationship
custom_field
```

출력:

```text
total_evidence_ref_count
type_counts
type_ratios
```

## 5. Review Metric Contract

최종 Review와 전체 Attempt 이력을 함께 본다.

측정:

- Review JSON 파일 수
- Review된 Issue 수
- 최종 Attempt 분포: 1 / 2 / 3
- 재생성 Issue 수
- 어느 Attempt에서든 Critical이 있었던 Issue 수
- 어느 Attempt에서든 Major가 있었던 Issue 수
- 최종 Verdict 분포
- 최종 Score 분포
- 최종 category score 분포

Defect Audit 분포:

- `fact_audit`
- `causal_claim_audit`
- `evidence_audit`
- `classification_audit`
- `missing_knowledge_audit`
- `duplication_audit`

각 Audit category는:

```text
audit_finding_counts  # 전체 Attempt의 finding 개수
audit_issue_counts    # 한 번이라도 finding이 있었던 Issue 수
```

를 함께 측정한다.

## 6. Outlier Contract

평균만 보고 M6/M8을 설계하지 않는다.
기본 `top_n=5`로 다음 이상치를 출력한다.

- item 수가 가장 많은 Issue
- 전체 statement 문자 수가 가장 큰 Issue
- 가장 긴 statement
- Evidence reference가 가장 많은 item
- 최종 Attempt가 가장 높은 Issue

보안 및 공유 편의를 위해 `profile.json`의 Outlier에는 statement 원문을 복사하지 않는다.

```text
issue_key
category
index
statement_length_chars
evidence_count
```

처럼 위치와 수치만 저장한다.

## 7. Integrity Contract

Profiler는 통계 전에 입력 정합성을 확인한다.

```text
expected_issue_count_match
knowledge_parse_errors
duplicate_issue_keys
review_parse_errors
missing_review_issue_keys
orphan_review_issue_keys
```

다음 중 하나라도 발생하면:

```text
integrity.ok == false
exit code = 1
```

으로 종료한다.

M5 결과를 M6 설계 근거로 사용하려면 `integrity.ok == true`가 선행 조건이다.

## 8. 산출물

로컬 Run 산출물:

```text
data/knowledge/runs/20260804T043628Z/
├─ issues/
├─ reviews/
├─ run_summary.json      # M4 집계, 저장한 경우
└─ profile.json          # M5 Profiling
```

프로젝트 문서:

```text
docs/KNOWLEDGE_PROFILING_SPEC.md
```

M5 Gate 완료 시 별도 Completion Record를 추가한다.

```text
docs/status/M5_KNOWLEDGE_PROFILING_COMPLETION.md
```

## 9. 사용자와 공유할 최소 통계

Jira 원문이나 statement 내용은 공유하지 않는다.
다음 aggregate 값만으로 M5 결과를 함께 판단할 수 있다.

```text
integrity.ok
issue_count
total_statement_item_count
items_per_issue
array_items_per_issue
category_item_counts
empty_arrays
statement_length_chars.overall
evidence_refs_per_item.overall
evidence.type_counts
final_attempt_distribution
regenerated_issue_count
historical_critical_issue_count
historical_major_issue_count
audit_finding_counts
outlier 수치 요약
```

## 10. M5에서 하지 않는 것

- Knowledge 재생성
- Skill v0.9 추가 튜닝
- Empty array 강제 채움
- DB Logical Schema 확정
- Chunk 크기 확정
- 임의 token 수 추정
- Embedding / FAISS 실행
- 평균값만 보고 이상치를 무시

M5는 실제 분포를 관찰하는 단계다. 설계 결정은 Profiling 결과를 확인한 뒤 M6부터 진행한다.
