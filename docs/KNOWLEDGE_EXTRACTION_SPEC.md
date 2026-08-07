# Jira Knowledge Extraction v1 상세 설계

## 1. 목적

Knowledge Extraction은 `[KNOWLEDGE INPUT]`의 이슈별 사실 패키지를 사내 OpenCode Agent가 읽고, 긴 Jira 논의에서 업무 의미를 구조화하는 단계입니다.

```text
[KNOWLEDGE INPUT]
Issue + Comments + Attachments + Relationships + Custom Fields
        ↓
OpenCode Agent
        ↓
[KNOWLEDGE]
문제/목표 · 관찰 · 가설 · 확인 원인 · 조치 · 계획 · 결정 · 결과 · 결론
```

이 단계부터 생성형 LLM의 해석이 개입합니다.

따라서 RAW/ANALYSIS/KNOWLEDGE INPUT과 달리 결과를 사실 원본으로 취급하지 않습니다.

---

## 2. 핵심 원칙

### 2.1 원문을 대체하지 않는다

Knowledge는 검색과 분석 편의를 위한 파생 지식입니다.

사실의 기준은 계속 다음 순서로 유지합니다.

```text
RAW
→ ANALYSIS
→ KNOWLEDGE INPUT
```

Knowledge가 원문과 충돌하면 원문이 우선입니다.

### 2.2 근거 없는 지식을 만들지 않는다

모든 Knowledge Statement는 최소 1개의 `evidence_refs`를 가져야 합니다.

### 2.3 추측과 확정 원인을 분리한다

```text
hypotheses
confirmed_causes
```

를 별도 배열로 둡니다.

`~인 것 같다`, `가능성이 있다`, `의심된다`는 confirmed cause가 아닙니다.

### 2.4 계획과 수행 완료를 분리한다

```text
plans
```

은 예정/제안/진행 계획입니다.

```text
actions_taken
```

은 실제 수행되었다는 근거가 있는 조치만 들어갑니다.

### 2.5 결과와 결론을 분리한다

```text
results
```

은 관찰된 시험/조치 결과입니다.

```text
conclusions
```

은 이슈의 최종 또는 현재 판단입니다.

결과가 존재한다고 해서 Agent가 임의로 결론을 만들어서는 안 됩니다.

---

## 3. 입력

```text
[KNOWLEDGE INPUT]
data/knowledge_input/runs/<run_id>/issues/<ISSUE_KEY>.json
```

Agent는 한 번의 분석에서 기본적으로 한 이슈 package만 읽습니다.

연결 이슈가 필요할 경우 `other_package_available=true`인 별도 package를 추가로 읽는 확장 전략은 향후 도입할 수 있습니다.

v1에서는 현재 package 내부의 사실만으로 결과를 생성합니다.

---

## 4. 출력 위치

향후 실행기는 다음 구조를 목표로 합니다.

```text
[KNOWLEDGE]
data/knowledge/runs/<run_id>/
├─ issues/
│  ├─ ABC-123.json
│  └─ ...
├─ extraction_warnings.jsonl
└─ manifest.json
```

실제 OpenCode 실행 방법은 사내 환경에 맞춰 별도 orchestration으로 구현합니다.

---

## 5. 출력 기본 구조

```json
{
  "knowledge_schema_version": "1.0",
  "run_id": "...",
  "project_key": "ABC",
  "issue_key": "ABC-123",
  "source_hash": "sha256:...",
  "prompt_version": "knowledge-extraction-v1",
  "extractor_model": "...",
  "extracted_at": "...",

  "issue_summary": {
    "text": "...",
    "evidence_refs": [
      {"source_type": "issue_description", "source_id": "ABC-123"}
    ]
  },

  "problem_or_goal": [],
  "context": [],
  "observations": [],
  "hypotheses": [],
  "confirmed_causes": [],
  "actions_taken": [],
  "plans": [],
  "decisions": [],
  "results": [],
  "conclusions": [],
  "open_questions": [],
  "blockers": []
}
```

`issue_summary`는 Description이 비어 있거나 의미 있는 요약 근거를 만들 수 없는 극단적인 경우 `null`을 허용할 수 있습니다.

---

## 6. Knowledge Statement

각 배열의 원소는 동일한 기본 형태를 사용합니다.

```json
{
  "text": "...",
  "state": "observed",
  "evidence_refs": [
    {
      "source_type": "comment",
      "source_id": "5001"
    }
  ]
}
```

### text

원문의 의미를 짧고 명확하게 재진술합니다.

가능하면 한 statement에는 하나의 사실/판단만 넣습니다.

### state

v1 공통 상태값:

```text
stated
proposed
active
observed
confirmed
rejected
attempted
completed
failed
cancelled
superseded
unresolved
unknown
```

카테고리가 이미 의미를 표현하므로 state는 필요한 경우에만 추가 의미를 제공합니다.

권장 예:

```text
observations + observed
hypotheses + active
hypotheses + rejected
hypotheses + superseded
confirmed_causes + confirmed
actions_taken + attempted
actions_taken + completed
actions_taken + failed
plans + proposed
plans + active
plans + cancelled
plans + completed
open_questions + unresolved
```

### evidence_refs

모든 statement는 최소 1개의 evidence를 가져야 합니다.

---

## 7. Evidence Reference

지원 source_type:

```text
issue_description
comment
attachment_metadata
relationship
custom_field
```

### Issue Description

```json
{
  "source_type": "issue_description",
  "source_id": "ABC-123"
}
```

### Comment

```json
{
  "source_type": "comment",
  "source_id": "5001"
}
```

### Attachment Metadata

```json
{
  "source_type": "attachment_metadata",
  "source_id": "8001"
}
```

Attachment는 현재 metadata만 제공됩니다.

따라서 파일 본문을 읽은 것처럼 지식을 추출하면 안 됩니다.

### Relationship

`relationship_id`가 존재하는 관계만 직접 evidence id로 사용하는 것을 v1 기본 정책으로 합니다.

Hierarchy 등 `relationship_id`가 없는 관계는 다른 Description/Comment 근거를 우선 사용합니다.

### Custom Field

```json
{
  "source_type": "custom_field",
  "source_id": "customfield_16603"
}
```

---

## 8. issue_summary

Issue 전체를 1~3문장으로 요약합니다.

금지:

- 원문에 없는 원인 추가
- 계획을 완료된 사실로 변경
- 미해결 이슈를 해결 완료로 표현

요약도 반드시 evidence를 포함합니다.

---

## 9. problem_or_goal

이 이슈가 해결하거나 달성하려는 핵심 문제/목표입니다.

예:

```text
장애 Issue   → 재현되는 문제
개발 Task    → 달성 목표
요청 Issue   → 요청 사항
조사 Issue   → 확인하려는 질문
```

문제와 목표가 여러 개라면 statement를 나눕니다.

---

## 10. context

문제/결정을 이해하는 데 필요한 환경과 조건입니다.

예:

```text
특정 제품/버전
특정 시험 조건
특정 프로젝트 제약
발생 조건
관련 시스템 구성
```

단순히 Custom Field 값을 모두 복사하지 않습니다.
업무 의미에 실제로 필요한 Context만 추출합니다.

---

## 11. observations

실제로 관찰되거나 확인된 사실입니다.

권장 상태는 `observed`입니다.

예:

```text
로그에서 timeout 관찰
특정 조건에서만 재현
20회 반복 시험 결과
특정 버전에서 발생하지 않음
```

관찰과 원인 해석을 섞지 않습니다.

---

## 12. hypotheses

아직 확정되지 않은 원인 또는 설명 후보입니다.

표현 예:

```text
~일 가능성이 있음
~가 원인으로 의심됨
~를 확인할 필요가 있음
```

후속 댓글에서 반박되면:

```text
state = rejected
```

또는 다른 가설로 대체됐으면:

```text
state = superseded
```

로 남길 수 있습니다.

초기 가설을 삭제해 버리기보다 논의 흐름을 보존하는 것이 유용할 수 있습니다.

---

## 13. confirmed_causes

명시적으로 확인된 원인만 저장합니다.

권장 상태는 `confirmed`입니다.

다음만으로는 confirmed cause가 아닙니다.

```text
시간적으로 먼저 발생함
누군가 추측함
패치 후 문제가 사라짐
비슷한 사례가 있음
```

원인 확인에 대한 직접적인 Jira 근거가 있어야 합니다.

근거가 부족하면 `hypotheses`에 두거나 비워 둡니다.

---

## 14. actions_taken

실제로 수행된 조치입니다.

```text
코드 수정
설정 변경
로그 수집
시험 수행
롤백
패치 적용
```

상태 예:

```text
attempted  시도했음
completed  실제 완료됨
failed     수행했으나 목적 달성 실패
active     현재 수행 중
```

`~할 예정`은 여기에 넣지 않고 `plans`에 넣습니다.

---

## 15. plans

향후 예정, 제안, 합의된 다음 작업입니다.

가능한 state:

```text
proposed
active
cancelled
completed
superseded
unknown
```

완료 사실이 확인되면 동일 내용을 `actions_taken`에도 별도 기술할 수 있지만, 의미 없는 중복은 피합니다.

---

## 16. decisions

논의 결과 명시적으로 결정된 사항입니다.

예:

```text
특정 방법 채택
특정 방향 폐기
릴리즈 보류
추가 시험 진행 결정
```

단순 의견과 결정은 구분합니다.

---

## 17. results

시험, 분석, 조치 후 확인된 결과입니다.

예:

```text
20회 재시험에서 재현되지 않음
성능이 개선됨
패치 후 다른 오류 발생
가설이 실험으로 반박됨
```

결과 자체가 성공/실패를 나타내면 `observed`, `confirmed`, `failed` 등을 문맥에 맞게 사용할 수 있습니다.

---

## 18. conclusions

이슈의 현재/최종 결론입니다.

Jira가 해결 상태라고 해서 Agent가 내용 없는 결론을 자동 생성하면 안 됩니다.

결론을 명시할 근거가 없으면 빈 배열을 허용합니다.

---

## 19. open_questions

아직 해결되지 않은 질문입니다.

권장 상태는 `unresolved`입니다.

예:

```text
정확한 재현 조건 미확정
장기 영향 미확인
추가 로그 필요
```

---

## 20. blockers

진행을 막고 있는 명시적 장애물입니다.

예:

```text
재현 장비 없음
외부 팀 답변 대기
필수 로그 미확보
패치 승인 대기
```

---

## 21. 빈 값 처리

없는 지식을 억지로 생성하지 않습니다.

```json
{
  "confirmed_causes": [],
  "conclusions": []
}
```

은 정상 결과입니다.

빈 배열은 `정보가 없음을 확인한 결과`로 해석합니다.

---

## 22. 시간 순서 해석

댓글은 Knowledge Input에서 sequence 순으로 제공됩니다.

Agent는 후반 댓글을 무조건 정답으로 선택하면 안 되지만, 다음을 고려해야 합니다.

```text
초기 가설
→ 검증
→ 반박
→ 새 가설
→ 조치
→ 결과
→ 최종 결론
```

이전 주장이 이후 명시적으로 폐기됐으면 상태를 `rejected` 또는 `superseded`로 표시합니다.

---

## 23. 관계 정보 해석

Relationship은 직접 인과관계라고 가정하지 않습니다.

예:

```text
relates to
blocks
parent_of
```

는 Jira가 명시한 관계일 뿐입니다.

`blocks`를 `root cause`로 바꾸면 안 됩니다.

Agent 추론 인과관계는 Comment/Description 등의 근거가 있어야 합니다.

---

## 24. Attachment 해석

v1 KNOWLEDGE INPUT에서는:

```text
content_available=false
```

입니다.

따라서:

```text
첨부파일 이름으로 존재 사실 확인     가능
첨부파일 실제 본문 내용 주장          금지
스크린샷의 내용 분석                  금지
로그 내부 오류 메시지 주장            금지
```

Attachment 본문 분석은 별도 확장 단계입니다.

---

## 25. Custom Field 해석

Custom Field는 context 또는 explicit metadata 근거로 사용할 수 있습니다.

하지만 plugin `any` 타입의 display 값에 과도한 의미를 부여하지 않습니다.

`value_shape`는 데이터 구조 정보이며 업무 의미 자체가 아닙니다.

---

## 26. source_hash 계약

Output의 `source_hash`는 입력 Knowledge Input package의 `source_hash`와 정확히 같아야 합니다.

이 값은 Agent가 새로 계산하거나 변경하지 않습니다.

향후:

```text
Knowledge.source_hash == KnowledgeInput.source_hash
→ 해당 Knowledge가 현재 package를 기반으로 생성됨
```

을 검증합니다.

---

## 27. Prompt Version

Prompt 변경도 결과 의미에 영향을 줍니다.

따라서:

```text
prompt_version = knowledge-extraction-v1
```

같은 명시적인 버전을 결과에 기록합니다.

Prompt 규칙을 의미 있게 수정하면 새 버전을 사용합니다.

---

## 28. Model 기록

```text
extractor_model
```

에는 실제 사내 OpenCode Agent가 사용한 모델 식별자를 기록합니다.

Knowledge 품질을 나중에 모델별로 비교하기 위해 필요합니다.

---

## 29. 생성 시간

```text
extracted_at
```

은 지식 추출 실행 시각입니다.

이는 source_hash에 포함되는 입력 사실과는 별개입니다.

---

## 30. Agent 출력 규칙

기본 Prompt에서는 다음을 강제합니다.

```text
JSON 객체만 출력
Markdown code fence 금지
설명 문장 추가 금지
스키마 밖 key 생성 금지
없는 정보 생성 금지
모든 statement evidence 필수
원문 표현을 장문 복사하지 말고 의미를 요약
```

---

## 31. 결정적 Validator의 역할

Agent 결과는 바로 신뢰하지 않습니다.

향후 `KnowledgeExtractionValidator`가 다음을 확인합니다.

```text
JSON 구조
schema_version
run_id
issue_key
source_hash
허용 category/state
필수 evidence_refs
evidence source_id가 실제 package에 존재하는지
Attachment metadata를 본문 evidence처럼 오용하지 않았는지
```

Validator 통과는 내용이 사실이라는 뜻이 아니라 **출력 계약과 evidence 연결이 구조적으로 유효하다**는 뜻입니다.

---

## 32. 사람 검증 파일럿

처음에는 대표 이슈 약 5건을 선택합니다.

권장 샘플:

```text
댓글이 적은 단순 Issue
댓글이 많은 Issue
해결된 Bug
미해결 Bug
계획/논의형 Task
관계/Custom Field가 있는 Issue
```

검증 관점:

```text
원문 누락 여부
가설/원인 혼동
계획/완료 혼동
시간 순서 오독
잘못된 결론 생성
evidence 정확성
```

5건 결과를 보고 schema와 Prompt를 수정한 뒤 전체 30건으로 확대합니다.

---

## 33. 완료 기준

Knowledge Extraction v1 파일럿 완료 조건:

```text
출력 JSON Schema 통과
source_hash 일치
모든 statement evidence 존재
잘못된 evidence id 0
대표 이슈 사람 검토 완료
추측 → confirmed cause 오분류 허용 기준 충족
계획 → actions_taken 오분류 허용 기준 충족
근거 없는 conclusion 생성 없음
```

정확한 품질 수치 기준은 파일럿 결과를 보고 별도로 결정합니다.

---

## 34. 다음 확장

Knowledge Extraction이 안정되면:

```text
Knowledge JSONL/DB 적재
→ Raw + Knowledge 이중 Chunk
→ BGE-M3 Embedding
→ FAISS
→ 구조화 지식 검색
→ 원문 evidence 복원
→ MCP
```

Knowledge는 검색 후보를 잘 찾는 용도로 사용하고, 최종 답변 시에는 원문 evidence를 다시 확인하는 방향을 유지합니다.
