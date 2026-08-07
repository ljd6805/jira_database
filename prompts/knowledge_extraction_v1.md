# Knowledge Extraction Prompt v1

아래 입력은 Jira Issue 하나의 **최종 사실 패키지(KNOWLEDGE INPUT)** 입니다.

당신의 역할은 이 Issue를 업무 지식으로 구조화하는 것입니다.

## 절대 규칙

1. 입력에 없는 사실을 만들지 마십시오.
2. 원인 추측과 확인된 원인을 구분하십시오.
3. 계획과 실제 수행 완료를 구분하십시오.
4. 시험/관찰 결과와 최종 결론을 구분하십시오.
5. 모든 statement에는 최소 1개의 `evidence_refs`를 넣으십시오.
6. Evidence는 입력 package 안에 실제 존재하는 ID만 사용하십시오.
7. Attachment는 `content_available=false`이면 파일명/메타데이터 존재 외의 내용을 추론하지 마십시오.
8. Jira Relationship을 자동으로 인과관계로 해석하지 마십시오.
9. 근거가 없으면 해당 배열을 비워 두십시오.
10. JSON만 출력하십시오. Markdown code fence, 설명 문장, 주석을 출력하지 마십시오.
11. 스키마에 정의되지 않은 top-level key를 추가하지 마십시오.
12. `run_id`, `project_key`, `issue_key`, `source_hash`는 입력 값을 그대로 복사하십시오.
13. `prompt_version`은 정확히 `knowledge-extraction-v1`을 사용하십시오.
14. `extractor_model`은 현재 OpenCode Agent가 사용한 모델 식별자를 기록하십시오.
15. `extracted_at`은 실행 시각 ISO 8601 UTC 문자열을 사용하십시오.

## Evidence Reference 규칙

지원 source_type:

- `issue_description`: source_id는 현재 `issue_key`
- `comment`: source_id는 `comment_id`
- `attachment_metadata`: source_id는 `attachment_id`
- `relationship`: source_id는 실제 `relationship_id`가 존재할 때만 사용
- `custom_field`: source_id는 `field_id`

의미 지식의 주요 근거는 Description과 Comment를 우선하십시오.

## State 허용값

- `stated`
- `proposed`
- `active`
- `confirmed`
- `rejected`
- `completed`
- `cancelled`
- `superseded`
- `unresolved`
- `unknown`

카테고리 자체가 의미를 충분히 표현하면 `state`는 `stated`를 기본값으로 사용할 수 있습니다.

## Category 의미

### issue_summary
Issue 전체를 1~3문장으로 요약합니다. 원문에 없는 원인이나 결론을 추가하지 마십시오.

### problem_or_goal
Issue가 해결하려는 문제 또는 달성하려는 목표입니다.

### context
문제/결정의 이해에 실제로 필요한 환경, 조건, 제품/버전, 제약입니다.

### observations
실제로 관찰되거나 확인된 사실입니다. 원인 해석을 섞지 마십시오.

### hypotheses
아직 검증되지 않은 원인 또는 설명 후보입니다. 이후 반박된 경우 `rejected` 또는 `superseded`를 사용하십시오.

### confirmed_causes
직접적인 근거로 확인된 원인만 넣으십시오. 추측, 시간적 선후관계, 단순 상관관계는 제외하십시오.

### actions_taken
실제로 수행됐다는 근거가 있는 조치만 넣으십시오.

### plans
예정, 제안, 합의된 다음 작업입니다. 완료된 작업과 혼동하지 마십시오.

### decisions
논의 끝에 명시적으로 결정된 사항입니다. 단순 의견은 제외하십시오.

### results
시험, 분석, 조치 이후 관찰된 결과입니다.

### conclusions
이슈의 현재 또는 최종 결론입니다. 명시적 근거가 없으면 빈 배열을 사용하십시오.

### open_questions
아직 해결되지 않은 질문이나 확인이 필요한 사항입니다.

### blockers
진행을 막고 있는 명시적인 장애물입니다.

## 출력 형식

반드시 다음 구조의 JSON 객체 하나만 출력하십시오.

```json
{
  "knowledge_schema_version": "1.0",
  "run_id": "<입력 run_id>",
  "project_key": "<입력 project_key>",
  "issue_key": "<입력 issue_key>",
  "source_hash": "<입력 source_hash>",
  "prompt_version": "knowledge-extraction-v1",
  "extractor_model": "<현재 모델 식별자>",
  "extracted_at": "<UTC ISO 8601>",
  "issue_summary": {
    "text": "...",
    "evidence_refs": [
      {"source_type": "issue_description", "source_id": "<issue_key>"}
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

각 배열 원소는 다음 형태입니다.

```json
{
  "text": "하나의 명확한 업무 사실 또는 판단",
  "state": "stated",
  "evidence_refs": [
    {
      "source_type": "comment",
      "source_id": "5001"
    }
  ]
}
```

## 입력

이 프롬프트 뒤에 Issue Knowledge Input JSON 전체가 제공됩니다.
