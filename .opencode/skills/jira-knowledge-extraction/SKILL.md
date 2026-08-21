---
name: jira-knowledge-extraction
description: Jira Knowledge Input 한 건에서 검색과 후속 분석에 유용한 업무지식을 Light Structured Knowledge Schema v0.1로 추출한다.
compatibility: opencode
metadata:
  language: ko
  skill-version: "0.9"
  schema-version: "0.1"
---

# Jira 업무지식 추출 Skill v0.9

## 목적

Jira Knowledge Input 한 건에서
검색과 후속 분석에 유용한 Knowledge JSON 한 건을 생성한다.

Knowledge는 원문을 대체하는 사실 원장이 아니다.
검색용 의미 압축 계층이다.

---

## 핵심 원칙

1. 입력에 없는 사실을 만들지 않는다.
2. 근거 없는 Knowledge를 만들지 않는다.
3. 빈 배열은 정상이다.
4. 원문의 확실성을 높이지 않는다.
5. 댓글은 sequence 순서대로 읽는다.
6. 후속 결과가 초기 가설을 뒤집으면 반영한다.
7. 같은 핵심 지식을 중복하지 않는다.
8. content_available=false 첨부 내용을 상상하지 않는다.
9. 자연스러운 한국어를 사용한다.

---

## 인과 표현 특별 규칙

다음 단어를 사용할 때는 한 단계 더 점검한다.

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

이 표현은:

```text
원문이 직접 확정했거나
충분히 통제된 비교/개입 결과가 직접 뒷받침할 때만
```

사용한다.

그 외에는:

```text
가능성이 있다
영향이 관찰됐다
설명하기 어렵다
근거가 약하다
개선됐다
```

처럼 원문 확실성을 보존한다.

특히:

```text
"못 찾았다" != "배제했다"
"다른 조건에서도 발생" != "원인이 아니다"
"영향일 수도 있다" != "주원인"
```

---

## 상태 표현 특별 규칙

```text
"확인되지 않았다"
```

와

```text
"검증을 아직 하지 않았다 / 검증 미완료"
```

를 구분한다.

측정 결과가 정상인 것도
미측정으로 바꾸면 안 된다.

---

## 지식 선택 우선순위

높은 가치:

1. 핵심 발견
2. 중요한 비교/반증
3. 최종 결과
4. 실제 Decision
5. 재발방지/표준 변경
6. 의사결정의 근거가 되는 trade-off

중간 가치:

7. 중요한 중간 시험
8. 핵심 정량 결과

낮은 가치:

9. 단순 일정
10. 파일 전달
11. 잡담
12. 중요하지 않은 단순 절차

---

## Summary

문제 + 핵심 방향 + 현재 상태만 짧게 쓴다.

세부 사실을 과도하게 넣지 않는다.

---

## Evidence Audit

모든 statement를 사실 A/B/C로 나눠
각 사실의 직접 Evidence를 확인한다.

핵심 인과 주장에는
특히 직접 근거가 있어야 한다.

---

## 중간 결과와 Outcome

승인 기준/후속 검증/원인 분리가 남은 결과는
기본적으로 `key_findings`를 우선한다.

중간 결과를 삭제하지 않는다.

후속 Decision에서 실제 채택된 충분한 결과는
`outcomes`에 둘 수 있다.

---

## Decision과 Open Item

```text
적용하기로 했다
→ actions_and_decisions

추가 확인이 필요하다
→ open_items
```

한 문장에 둘이 섞여 있으면 분리한다.

---

## Trade-off 보존

최종 선택 이유를 이해하는 데 중요한
대안 비교/부작용은 삭제하지 않는다.

예:

```text
30분 처리 → 문제는 없어졌지만 품질 부작용
15분 처리 → 문제 없음 + 부작용 작음
→ 15분 채택
```

이 경우 30분 결과도 검색 가치가 있다.

---

## 출력

Knowledge Schema v0.1 유지:

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

Evidence:

```text
summary
description
comment:<id>
attachment:<id>
relationship:<id>
custom_field:<id>
```
