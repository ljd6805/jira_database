# M2 Knowledge Schema / Skill Completion Record

복원 기준일: 2026-08-24  
완료 근거: 2026-08-21 Source-of-Truth에서 M2 DONE으로 고정  
최종 artifact materialization: 2026-08-21 · PR #5  
단계: **M2 · 검색용 Knowledge 계약**

이 문서는 M2의 결정과 검증 결과를 저장소 history에서 복원한다.

M2는 M0/M1처럼 모든 실험 과정이 개별 commit으로 남아 있지는 않다. 따라서 이 문서는 **저장소에서 직접 확인 가능한 사실**과 **당시 Source-of-Truth에 완료 사실로 기록된 결정**을 구분해 기록하며, 없는 실험 이력을 추정해서 채우지 않는다.

---

## 1. M2 목적

M1까지의 결과는 완전한 Issue 사실 패키지였다.

```text
[KNOWLEDGE INPUT]
Issue
├─ Description
├─ Comments
├─ Attachment metadata
├─ Relationships
└─ Custom Fields
```

하지만 검색 시스템에서 매번 이 긴 사실 패키지 전체를 직접 비교하는 것은 비효율적이다.

M2의 목적은 이 사실 패키지를 대체하는 것이 아니라, 그 위에 다음과 같은 **검색용 의미 압축 계층**을 정의하는 것이었다.

```text
[KNOWLEDGE INPUT]  # 사실 계약
        ↓
OpenCode Worker + Extraction Skill
        ↓
[KNOWLEDGE]        # 검색용 의미 압축
```

핵심 질문은 다음이었다.

> Jira 한 건에서 무엇을 “업무지식”으로 남겨야 검색과 후속 분석에 유용하면서도, 원문보다 더 강한 사실을 만들어내지 않을 수 있는가?

---

## 2. M2의 Source-of-Truth 완료 기록

2026-08-21 `docs: add milestone source of truth` commit은 M2를 다음과 같이 고정했다.

```text
M2 DONE
목표   : 검색용 Knowledge 계약
Action : Light Structured Schema
         → 합성 30건
         → Pro/MAX 비교
         → Skill 반복 개선
산출물 : Schema v0.1 · Skill v0.9
Gate   : Pro 채택, Schema 안정 → M3
```

같은 문서에는 다음 검증 결론도 남아 있다.

```text
Schema v0.1
Skill v0.9
Pro Worker + Pro Reviewer
MAX는 10배 이상 느려 제외
Reviewer는 보조 필터
```

이 중 Reviewer 운영 구조는 M3의 주제이고, M2에서 중요한 것은 **Schema v0.1을 유지하고 Knowledge Extraction 모델로 Pro를 채택했다**는 점이다.

---

## 3. 저장소 history에 없는 부분

M2에서 “합성 30건 → Pro/MAX 비교 → Skill 반복 개선”이 수행됐다는 사실은 Source-of-Truth에 남아 있다.

그러나 현재 `jira_database` repository에는 다음이 별도 commit artifact로 보존되어 있지 않다.

```text
합성 30건 원본 dataset
v0.1 ~ v0.8 Skill 각 버전
버전별 모델 출력 전체
Pro/MAX 비교 raw result
버전별 score table
```

따라서 이 Completion Record는 다음을 사실처럼 재구성하지 않는다.

- 각 Skill 버전에서 정확히 어떤 문장을 언제 바꿨는지
- 합성 case별 점수
- Pro/MAX의 정확한 처리 시간 수치
- 모델별 전체 승패 건수

저장소가 직접 지지하는 결론은 다음까지다.

```text
합성 30건으로 반복 검증함
MAX가 일부 복잡 case에서 조금 더 섬세했음
MAX 처리 시간이 10배 이상 느렸음
검색용 의미 압축 목적에서는 Pro가 충분하다고 판단함
Pro를 채택함
Knowledge Schema v0.1은 안정화되어 유지함
Skill 최종본은 v0.9로 고정함
```

이 공백을 명시적으로 남기는 이유는 “문서가 그럴듯해 보이는 것”보다 **프로젝트 history가 실제로 무엇을 증명하는지**가 더 중요하기 때문이다.

---

## 4. 결정 1 — Knowledge는 사실 원장이 아니다

최종 Skill v0.9의 첫 번째 설계 문장은 다음 의미를 고정한다.

```text
Knowledge는 원문을 대체하는 사실 원장이 아니다.
검색용 의미 압축 계층이다.
```

따라서 데이터 계층 역할은 다음처럼 분리됐다.

```text
[RAW]
  최종 사실 원본

[ANALYSIS]
  결정적으로 정규화된 사실

[KNOWLEDGE INPUT]
  Issue 단위 최종 사실 계약

[KNOWLEDGE]
  검색과 후속 분석을 위한 의미 압축
```

이 결정은 이후 M4 Human Validation과 M10 Evidence Retrieval까지 유지되는 핵심 원칙이다.

---

## 5. 결정 2 — Light Structured Knowledge Schema v0.1

M2는 복잡한 Ontology를 먼저 만들지 않았다.

최종 Schema v0.1의 top-level 필드:

```text
knowledge_schema_version
issue_key
issue_summary
problem_or_goal[]
key_findings[]
actions_and_decisions[]
outcomes[]
open_items[]
```

의도는 Jira 업무 흐름에서 검색 가치가 높은 의미를 최소한의 안정적인 범주로 나누는 것이다.

### 각 필드 의미

#### `issue_summary`

Issue 전체의 문제 + 핵심 방향 + 현재 상태를 짧게 나타낸다.

세부 사실을 전부 압축해 넣는 필드가 아니다.

#### `problem_or_goal[]`

해결하려는 문제, 조사 목적, 달성하려는 목표처럼 Issue가 왜 존재하는지를 표현한다.

#### `key_findings[]`

중요 관찰, 비교, 반증, 중간 시험 결과, 핵심 정량 사실 등 검색 가치가 높은 발견을 저장한다.

특히 아직 최종 승인이나 후속 검증이 남아 있는 결과는 `outcomes`보다 이 필드에 두는 것을 우선한다.

#### `actions_and_decisions[]`

실제로 수행한 조치 또는 명시적으로 채택한 의사결정을 저장한다.

단순 계획을 실행 완료처럼 적지 않는다.

#### `outcomes[]`

실제 후속 의사결정이나 종결 판단에 채택된 충분한 결과를 저장한다.

중간 시험이 좋게 나왔다는 이유만으로 자동으로 Outcome이 되는 것은 아니다.

#### `open_items[]`

추가 확인, 남은 검증, 미해결 항목처럼 현재도 열린 상태를 저장한다.

---

## 6. 결정 3 — 모든 Knowledge Item은 Evidence를 가진다

Schema v0.1의 핵심 구조:

```json
{
  "statement": "...",
  "evidence_refs": ["..."]
}
```

`statement`만 존재하는 자유 텍스트 목록을 허용하지 않았다.

모든 item은 최소 하나 이상의 `evidence_refs`를 가져야 한다.

허용 Evidence 형식:

```text
summary
description
comment:<id>
attachment:<id>
relationship:<id>
custom_field:<id>
```

JSON Schema는 다음을 강제한다.

- `additionalProperties: false`
- `statement.minLength = 1`
- `evidence_refs.minItems = 1`
- `evidence_refs.uniqueItems = true`
- 허용된 reference pattern만 사용

이 결정의 목적은 Knowledge를 나중에 Embedding한 뒤에도 검색 결과에서 **왜 이런 지식이 나왔는지 원래 사실로 돌아갈 수 있게 하는 것**이다.

---

## 7. 결정 4 — 빈 배열은 정상이다

Skill v0.9는 명시적으로:

```text
빈 배열은 정상이다.
```

라고 규정한다.

즉 모든 Issue가 반드시:

```text
problem
finding
decision
outcome
open item
```

을 각각 하나 이상 가져야 하는 것은 아니다.

이 결정은 “Schema를 채우기 위해 사실을 만들어내는” 압력을 줄이기 위한 것이다.

예를 들어 실제 최종 Decision이 없는 Issue에서 `actions_and_decisions`를 억지로 채우는 것보다 빈 배열이 정확하다.

---

## 8. 결정 5 — 원문의 확실성을 높이지 않는다

M2 반복 개선에서 가장 중요한 품질 규칙 중 하나는 **certainty preservation**이었다.

최종 Skill은 강한 인과/확정 표현에 별도 제한을 둔다.

주의 표현:

```text
원인
주원인
원인이 아니다
배제
무관
기인
때문
해결
확정
```

이 표현은 다음 중 하나가 직접 뒷받침할 때만 사용한다.

```text
원문이 직접 확정
OR
충분히 통제된 비교/개입 결과가 직접 뒷받침
```

그 외에는 더 약한 표현을 사용한다.

```text
가능성이 있다
영향이 관찰됐다
설명하기 어렵다
근거가 약하다
개선됐다
```

대표적인 금지 변환:

```text
"못 찾았다"
!= "배제했다"

"다른 조건에서도 발생했다"
!= "원인이 아니다"

"영향일 수도 있다"
!= "주원인이다"
```

이 규칙은 이후 M3 Reviewer의 Causal Claim Audit로 강화됐다.

---

## 9. 결정 6 — 상태의 의미를 보존한다

Skill은 다음 두 상태를 구분하도록 했다.

```text
"확인되지 않았다"

vs

"아직 검증하지 않았다 / 검증 미완료"
```

또한 실제 측정 결과가 정상인 것을 “미측정”처럼 바꾸지 않는다.

이 규칙의 핵심은 원문의 **사실 내용뿐 아니라 epistemic state**, 즉 무엇이 확인됐고 무엇이 아직 열린 상태인지까지 보존하는 것이다.

---

## 10. 결정 7 — 시간 흐름과 반증을 보존한다

Issue의 댓글은 `sequence` 순으로 읽는다.

중요한 이유:

```text
초기 가설
→ 시험
→ 반증
→ 대안 비교
→ 최종 선택
```

형태의 Jira 업무 흐름에서는 마지막 댓글만 읽으면 잘못된 결론을 만들 수 있다.

Skill v0.9는:

- 댓글 sequence 순서 유지
- 후속 결과가 초기 가설을 뒤집으면 반영
- 중요한 중간 결과를 삭제하지 않음

을 명시한다.

Knowledge는 단순한 “마지막 상태 요약”이 아니라 **최종 결론을 이해하는 데 필요한 핵심 경로**를 보존해야 한다.

---

## 11. 결정 8 — 검색 가치 우선순위

M2에서 모든 Jira 문장을 같은 가치로 취급하지 않도록 Knowledge 선택 우선순위를 명시했다.

### 높은 가치

```text
1. 핵심 발견
2. 중요한 비교 / 반증
3. 최종 결과
4. 실제 Decision
5. 재발방지 / 표준 변경
6. Decision의 근거가 되는 trade-off
```

### 중간 가치

```text
7. 중요한 중간 시험
8. 핵심 정량 결과
```

### 낮은 가치

```text
9. 단순 일정
10. 파일 전달
11. 잡담
12. 중요하지 않은 단순 절차
```

이 분류는 Knowledge가 Issue 원문을 또 한 번 길게 복사하는 것이 아니라, 검색 시 도움이 되는 의미를 압축하기 위한 규칙이다.

---

## 12. 결정 9 — 중간 결과와 Outcome 분리

최종 Skill은:

```text
승인 기준 / 후속 검증 / 원인 분리가 남은 결과
→ 기본적으로 key_findings
```

를 우선한다.

반대로:

```text
후속 Decision에서 실제 채택되고 충분히 확정된 결과
→ outcomes 가능
```

이다.

이 구분이 필요한 이유는 “좋은 시험 결과”와 “업무적으로 최종 채택된 결과”가 다르기 때문이다.

검색에서 중간 결과를 최종 해결처럼 노출하면 과거 Jira 이력의 의미가 왜곡된다.

---

## 13. 결정 10 — Decision과 Open Item 분리

대표 규칙:

```text
"적용하기로 했다"
→ actions_and_decisions

"추가 확인이 필요하다"
→ open_items
```

한 문장에 둘이 섞여 있으면 분리한다.

이 결정은 이후 DB에서 Knowledge Item type을 안정적으로 다루기 위한 토대가 됐다.

---

## 14. 결정 11 — Trade-off를 버리지 않는다

검색용 요약에서 흔히 생기는 오류는 최종 선택만 남기고 “왜 그 선택을 했는지”를 지우는 것이다.

Skill은 최종 선택 이유를 이해하는 데 중요한 대안 비교나 부작용을 보존하도록 했다.

개념 예:

```text
30분 처리
→ 문제는 개선
→ 품질 부작용 큼

15분 처리
→ 문제 없음
→ 부작용 작음

결정
→ 15분 채택
```

이 경우 `30분 처리` 결과도 검색 가치가 있다.

최종 Decision만 남기면 나중에 “왜 30분이 아니라 15분인가?”라는 질문에 답할 수 없기 때문이다.

---

## 15. 모델 비교 — Pro vs MAX

M2 Source-of-Truth에 남은 모델 결정:

```text
MAX
- 일부 복잡한 case에서 약간 더 섬세함
- 처리 시간이 Pro 대비 10배 이상 느림

Pro
- 검색용 의미 압축 목적에 충분한 품질
- 실제 30건 운영을 고려하면 비용/처리시간 측면에서 유리
```

결론:

## **Knowledge Worker = Pro 채택**

이 선택은 “MAX가 성능이 나쁘다”는 판단이 아니다.

프로젝트 목적이:

```text
최종 법적/의학적 판단
```

같은 최대 정밀도 작업이 아니라:

```text
Jira 원문으로 되돌아갈 수 있는
검색용 의미 압축 계층 생성
```

이기 때문에 추가 지연의 가치가 충분하지 않다고 판단한 것이다.

---

## 16. Schema를 v0.1에서 더 복잡하게 확장하지 않은 이유

M2에서 초기 후보 개념은 더 많을 수 있었다.

예:

```text
context
observations
hypotheses
confirmed_causes
actions_taken
plans
decisions
results
conclusion
open_questions
blockers
```

그러나 최종 계약은 더 작은 5개 array + summary 구조를 채택했다.

이 선택의 효과:

1. 분류 경계가 지나치게 세분화되지 않음
2. 작은 사내 LLM도 일관되게 출력하기 쉬움
3. 검색 시 의미가 중복되는 필드 수 감소
4. 후속 DB schema가 LLM 출력 taxonomy에 과도하게 종속되지 않음
5. 실제 Jira 데이터를 본 뒤 필요할 때 확장 가능

즉 M2의 목표는 완벽한 Ontology가 아니라 **실제 검색에 충분한 최소 의미 계약**이었다.

---

## 17. 최종 Skill v0.9 artifact

최종 Skill은 다음 경로로 저장소에 materialize됐다.

```text
.opencode/skills/jira-knowledge-extraction/
├─ SKILL.md
├─ CHANGELOG.md
└─ references/
   ├─ knowledge.schema.json
   ├─ output-example.json
   ├─ review.schema.json
   └─ review-example.json
```

PR #5:

```text
feat: add Jira knowledge extraction skill v0.9
```

이 PR은 M4 실제 파일럿 환경을 준비하면서 **이미 합성 검증에서 확정된 M2/M3 계약의 최종 artifact를 repository 안으로 가져온 작업**이다.

따라서 artifact commit 시점과 설계 의사결정이 처음 완료된 시점을 같은 것으로 해석하면 안 된다.

---

## 18. v0.9 CHANGELOG가 보여주는 마지막 품질 보강

Repository에 보존된 CHANGELOG는 v0.9 항목만 남아 있다.

최종 보강점:

```text
Fact Audit 추가
Causal Claim Audit 추가
Evidence Audit 원자 사실 단위 강화
Classification Audit 강화
Missing Knowledge Audit 추가
Duplication/Low-value Audit 분리
못 찾음 != 배제
확인되지 않음 != 검증 미완료
trade-off 누락 Major 후보
Critical score cap 7.9
Major score cap 8.4
Audit 이후 score 계산
재생성 시 audit_findings 반영
```

여기서 Audit / score / regeneration 실행구조는 M3에서 다룬다.

M2 관점에서 중요한 사실은 **이 품질 보강에도 Knowledge Schema v0.1 자체는 변경하지 않았다는 것**이다.

즉 문제는 데이터 모델을 계속 늘려 해결하기보다 Extraction / Review 규칙을 정교화하는 방향으로 갔다.

---

## 19. M2 검증 결과

Source-of-Truth에 고정된 검증 결과:

```text
합성 데이터 30건 사용
Light Structured Schema 반복 검증
Skill 반복 개선 → v0.9
Pro / MAX 비교
Pro 채택
Schema v0.1 유지
합성 데이터 추가 튜닝 종료
```

M2는 실제 사내 Jira 30건을 대상으로 한 최종 검증 단계가 아니다.

실제 Jira 30건 Knowledge Extraction과 사람 원문 검토는 M4의 역할로 남겼다.

따라서 M2 Gate의 의미는:

> “합성 검증에서 검색용 Knowledge 계약이 실제 Jira 파일럿을 시작할 정도로 안정화되었다.”

이지,

> “Knowledge 정확도가 실제 업무 데이터에서 완전히 검증되었다.”

가 아니다.

---

## 20. M2에서 하지 않은 것

```text
실제 Jira 30건 Knowledge 전체 생성
실제 Jira 원문 Human Validation
다건 운영 Orchestrator
Python schema validator 실행 loop
Defect Reviewer 재생성 loop
DB schema 확정
Chunk 단위 확정
Embedding / FAISS
```

이 중 Quality Loop는 M3, 실제 업무 데이터 검증은 M4로 분리했다.

---

## 21. M2 Gate 판정

- [x] Knowledge를 사실 원장과 분리
- [x] Light Structured Knowledge Schema 정의
- [x] Schema version `0.1` 고정
- [x] Issue summary + 5개 의미 array 계약 고정
- [x] 모든 item에 `statement + evidence_refs[]` 강제
- [x] Evidence reference namespace 정의
- [x] Empty array 정상 허용
- [x] certainty preservation 규칙
- [x] Comment 시간 흐름 반영
- [x] key finding / decision / outcome / open item 경계
- [x] trade-off 보존 규칙
- [x] 합성 30건 반복 검증 기록
- [x] Pro / MAX 비교
- [x] MAX 10배 이상 지연 확인
- [x] Pro 채택
- [x] Skill v0.9 최종화
- [x] Schema v0.1 유지 결정

## **M2 Gate: PASS / DONE**

다음 단계는 **M3 · 256K Context Quality Loop**다.

---

## 22. M2가 M3 이후에 남긴 설계 제약

1. Knowledge는 검색용 semantic compression이며 사실 원장이 아니다.
2. 최종 사실 판단은 Knowledge Input / ANALYSIS / RAW Evidence로 돌아간다.
3. 모든 Knowledge Item은 Evidence를 가진다.
4. Schema를 채우기 위해 없는 사실을 만들지 않는다.
5. 확실성을 원문보다 높이지 않는다.
6. 중요한 반증 / trade-off / 결정 경로를 보존한다.
7. Pro를 기본 Knowledge Worker 모델로 사용한다.
8. Schema v0.1을 실제 Jira 파일럿 전까지 불필요하게 확대하지 않는다.

---

## 23. 주요 근거 Commit / 문서

- [`f593a00` · milestone source of truth](https://github.com/ljd6805/jira_database/commit/f593a00b2bec2c85aec669c5d4620959386d2e57)
- [PR #5 · Jira knowledge extraction Skill v0.9](https://github.com/ljd6805/jira_database/pull/5)
- [`580de86` · final Skill v0.9 artifact](https://github.com/ljd6805/jira_database/commit/580de860ba3f8af020cfa71d2e89449aae9293a0)
- `.opencode/skills/jira-knowledge-extraction/SKILL.md`
- `.opencode/skills/jira-knowledge-extraction/CHANGELOG.md`
- `.opencode/skills/jira-knowledge-extraction/references/knowledge.schema.json`
- `.opencode/skills/jira-knowledge-extraction/references/output-example.json`

---

## 24. History Gap Note

이 문서를 이후에 갱신할 때 M2 초기 실험 자료가 다른 저장소/로컬 artifact에서 발견되면 다음 항목을 별도 Appendix로 추가한다.

```text
- 합성 30건 생성 규칙
- Skill v0.1~v0.8 change history
- Pro/MAX case별 비교
- 실제 처리 시간
- 최종 v0.9로 수렴한 오류 사례
```

현재 repository 증거 없이 위 내용을 추정해 채우지 않는다.
