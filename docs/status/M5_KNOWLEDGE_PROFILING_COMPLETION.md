# M5 Knowledge / Review Profiling Completion Record

기준일: 2026-08-24  
대상 Run: `20260804T043628Z`

이 문서는 M5 Knowledge / Review Profiling 단계의 **완료 시점 측정 결과와 M6 설계 입력을 고정 기록**한다.

> 문서 보존 원칙: 이전 Milestone의 입력·프롬프트·문제·해결·판단·결과는 틀린 내용이 아닌 한 삭제하지 않는다. M5 결과 역시 M6 이후에도 설계 근거로 보존한다.

---

## 1. M5 목적

M5는 Knowledge를 다시 생성하거나 Skill을 튜닝하는 단계가 아니다.
실제 M4 산출물의 분포를 deterministic Python으로 측정해 M6 DB Logical Schema와 이후 M8 Chunk 정책의 근거를 만든다.

```text
M4 Knowledge / Review 30건
        ↓
profile_knowledge_run.py
        ↓
크기 · Category · Empty · Statement · Evidence · Review · Outlier
        ↓
M6 DB Logical Schema
```

---

## 2. 입력과 실행 도구

입력:

```text
[KNOWLEDGE]
data/knowledge/runs/20260804T043628Z/issues

[KNOWLEDGE REVIEW]
data/knowledge/runs/20260804T043628Z/reviews
```

도구:

```text
tools/jira_knowledge/profile_knowledge_run.py
```

실행 예:

```powershell
python tools/jira_knowledge/profile_knowledge_run.py `
  data/knowledge/runs/20260804T043628Z/issues `
  data/knowledge/runs/20260804T043628Z/reviews `
  --expected-issue-count 30 `
  --output data/knowledge/runs/20260804T043628Z/profile.json
```

Profiler는 statement 원문을 profile 결과에 복사하지 않고 길이와 위치 정보만 기록한다.

---

## 3. Knowledge 분포

```text
Issue 수                    30
Knowledge item 전체         285
배열 item                   255

Issue당 item
  min                        3
  mean                       9.5
  p50                        9
  p95                        16.1
  max                        19
```

Category별 전체 item:

```text
issue_summary               30
problem_or_goal             32
key_findings               138
actions_and_decisions       51
outcomes                     21
open_items                   13
```

285개 전체 item 기준 대략적인 비중:

```text
issue_summary               10.5%
problem_or_goal             11.2%
key_findings                48.4%
actions_and_decisions       17.9%
outcomes                     7.4%
open_items                   4.6%
```

### 관찰

- 실제 업무지식의 가장 큰 비중은 `key_findings`다.
- Issue당 Knowledge item 수는 현재 30건 corpus에서 비교적 안정적이다.
- 최대 19 item 수준으로, item 단위 관계형 저장이 충분히 현실적이다.
- 이 30건 분포를 향후 모든 Jira의 절대 상한으로 사용하지 않는다.

---

## 4. Empty Array 분포

```text
problem_or_goal
  empty 6 / 30 = 20.0%

actions_and_decisions
  empty 4 / 30 = 13.33%

outcomes
  empty 10 / 30 = 33.33%

open_items
  empty 20 / 30 = 66.67%

key_findings
  empty 0 / 30 = 0%
```

### 관찰

M4 Human Validation과 일치하게 Empty Array 자체는 품질 오류가 아니다.
모든 category를 강제로 채우는 정책은 유지하지 않는다.

---

## 5. Statement 길이

전체 285개 statement의 문자 길이:

```text
min       20
mean      114.01
p50       104
p95       206.4
max       447
```

Category별 특징:

```text
issue_summary
  mean 153.3 / p95 238.25 / max 299

key_findings
  mean 118.81 / p95 231.6 / max 447

actions_and_decisions
  mean 88.57 / p95 172 / max 217

outcomes
  mean 103.9 / p95 157 / max 170

open_items
  mean 79.08 / p95 132.4 / max 139
```

### 관찰

- Knowledge item은 실제 데이터에서도 비교적 짧고 독립적인 의미 단위로 유지됐다.
- M8에서 `Knowledge Item`은 기본 Chunk 후보로 검토할 가치가 높다.
- 다만 M5에서 Chunk 정책을 확정하지 않는다.
- BGE-M3 token 기준은 M8에서 실제 tokenizer로 측정한다.

---

## 6. Evidence 분포

전체 Evidence reference:

```text
503
```

Item당 Evidence:

```text
min       1
mean      1.76
p50       1
p95       4.8
max       13
```

Evidence type:

```text
comment        402  / 79.92%
description     80  / 15.90%
attachment      18  /  3.58%
summary          2  /  0.40%
custom_field     1  /  0.20%
```

### 관찰

- Evidence의 약 80%가 Comment에 연결된다.
- M6에서 Knowledge → Evidence → Comment round-trip은 핵심 계약이다.
- Evidence 최대 13개 item이 있으므로 Evidence를 단일 문자열/고정 컬럼으로 제한하면 안 된다.
- `knowledge_item`과 Evidence 사이에는 1:N 관계가 자연스럽다.

---

## 7. Issue Summary의 역할

`issue_summary`는 모든 Issue에 1개 존재한다.

```text
statement 평균 길이        153.3 chars
Evidence 평균              3.83 refs
Evidence 최대              8 refs
```

일반 item보다 여러 Evidence를 압축하는 경향이 뚜렷하다.

### 관찰

논리적으로 다음 두 검색 레벨을 구분할 수 있다.

```text
Issue-level representation
  └─ issue_summary

Fine-grained Knowledge
  ├─ problem_or_goal
  ├─ key_findings
  ├─ actions_and_decisions
  ├─ outcomes
  └─ open_items
```

M6에서는 이 차이를 잃지 않도록 모델링하고, 실제 Retrieval 사용 방식은 M8/M9에서 검증한다.

---

## 8. Review 분포

```text
Review JSON 파일           37
Review된 Issue             30

최종 Attempt
  1                         24
  2                          5
  3                          1

재생성 Issue                6
Historical Critical Issue   2
Historical Major Issue      4
최종 Verdict PASS          30
```

최종 Score:

```text
min       8.5
mean      9.15
p50       9.05
p95       9.75
max       9.9
```

### 관찰

- 80%는 최초 Attempt에서 PASS했다.
- 나머지 20%도 최대 3 Attempt 안에 수렴했다.
- Critical/Major는 최종 결함 수가 아니라 중간 Attempt의 historical defect 이력이다.
- 현재 30건 corpus에서는 최대 3 Attempt 정책이 충분히 작동했다.

---

## 9. Defect Audit 분포

전체 Attempt에서 Audit finding이 발생한 Issue 수:

```text
missing_knowledge_audit   18 / 30
classification_audit     13 / 30
evidence_audit           13 / 30
duplication_audit        11 / 30
causal_claim_audit        7 / 30
fact_audit                6 / 30
```

전체 finding 수:

```text
missing_knowledge_audit   23
classification_audit     21
evidence_audit           21
duplication_audit        15
causal_claim_audit       11
fact_audit                9
```

### 관찰

실제 Jira에서 자주 발생한 Reviewer 지적은 단순 사실 오류보다:

- 무엇을 지식으로 남길지
- 어느 category로 둘지
- 어떤 Evidence를 붙일지
- 중복을 어떻게 줄일지

에 더 집중됐다.

이는 Worker/Reviewer 역할 분리가 실제 데이터에서도 의미가 있었음을 보여준다.

---

## 10. Outlier 요약

보안상 완료 문서에는 내부 Issue Key를 기록하지 않고 수치만 남긴다.

```text
Issue 최대 item 수                 19
Issue 최대 전체 statement chars    2408
단일 statement 최대 chars           447
단일 item 최대 Evidence refs         13
최대 final attempt                    3
```

### 관찰

현재 30건에서 구조를 깨뜨릴 정도의 극단적인 Outlier는 관찰되지 않았다.
다만 Schema는 이 값을 고정 상한으로 두지 않고 향후 더 큰 Jira를 허용해야 한다.

---

## 11. M6로 넘기는 설계 제약

M5가 직접 DB Schema를 확정하지는 않지만 다음은 M6 설계 입력으로 고정한다.

1. `Issue`와 `Knowledge Item`은 1:N 관계가 자연스럽다.
2. `issue_summary`와 fine-grained item의 역할 차이를 보존한다.
3. Category는 현재 6개지만 category별 독립 테이블을 남발하지 않는다.
4. 빈 category를 정상 상태로 허용한다.
5. `Knowledge Item`과 `Evidence`는 1:N 관계로 모델링할 수 있어야 한다.
6. Evidence는 원본 Comment/Description/Attachment 등으로 round-trip 가능해야 한다.
7. Comment Evidence가 약 80%이므로 Comment 식별자와 sequence/source locator를 안정적으로 보존한다.
8. Review Attempt와 historical Critical/Major 이력을 감사 가능한 형태로 보존한다.
9. p95/max를 DB 컬럼 길이의 하드 제한으로 사용하지 않는다.
10. Knowledge/Review 산출물의 Run/Schema version을 추적할 수 있어야 한다.

---

## 12. M5 Gate 판정

M5 목적은 실제 산출물의 분포를 측정하고 M6 설계 근거를 확보하는 것이다.

확인된 결과:

- [x] Knowledge 30건 Profiling
- [x] Category / Empty 분포 측정
- [x] Statement 길이 분포 측정
- [x] Evidence 분포 측정
- [x] Review Attempt / Score / Historical Defect 분포 측정
- [x] Audit finding 분포 측정
- [x] Outlier 확인
- [x] M6 설계 제약 도출
- [x] Profiler 실행 과정에서 사용자로부터 integrity 오류 보고 없음

## **M5 Gate: PASS / DONE**

다음 단계는 **M6 · DB Logical Schema**다.
