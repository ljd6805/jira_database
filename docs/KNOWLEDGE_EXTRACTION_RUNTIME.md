# Knowledge Extraction Runtime v0.9

이 문서는 M4 실제 Jira Knowledge Pilot에서 사용하는 OpenCode 실행 환경의 현재 계약을 기록한다.

## 1. 설치 위치

프로젝트 루트 기준:

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
   └─ validate_knowledge.py
```

## 2. 데이터 계층

```text
[KNOWLEDGE INPUT]
data/knowledge_input/runs/<run_id>/issues/<ISSUE_KEY>.json
```

용도: Worker와 Reviewer가 읽는 Issue 단위 사실 패키지.

```text
[KNOWLEDGE]
data/knowledge/runs/<run_id>/issues/<ISSUE_KEY>.json
```

용도: Skill v0.9가 생성하는 검색용 의미 압축 결과.

```text
[KNOWLEDGE REVIEW]
data/knowledge/runs/<run_id>/reviews/<ISSUE_KEY>.review.attempt<N>.json
```

용도: Defect Reviewer의 Audit, Critical/Major, 개선 지점을 보존한다.

Knowledge는 사실 원장이 아니다. 최종 사실 확인은 Evidence reference를 통해 [KNOWLEDGE INPUT] → [ANALYSIS] → [RAW]로 돌아간다.

## 3. M4 Local Input Boundary

M4 Knowledge Extraction은 Jira 수집 단계가 아니다.
Jira 데이터는 이미 수집·정규화·패키징되어 있고, 지정된 로컬 `[KNOWLEDGE INPUT]` JSON이 유일한 사실 입력이다.

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

Agent는 `permission`의 최상위 `"*": deny`를 기본값으로 사용하고 필요한 도구만 개별 허용한다.
따라서 새 MCP/Custom Tool이 추가되어도 명시적으로 허용하지 않는 한 M4 Agent가 사용할 수 없다.

```text
Orchestrator
  default deny
  → glob/list
  → jira-knowledge-worker task
  → jira-knowledge-reviewer task

Worker
  default deny
  → local read/edit
  → jira-knowledge-extraction Skill
  → validate_knowledge.py 실행만 bash 허용

Reviewer
  default deny
  → local read/edit
```

외부 디렉터리 접근은 허용하지 않는다.

## 4. 실행 구조

```text
Jira Knowledge Orchestrator
        │
        │ 파일 경로만 관리
        ▼
새 Worker · Issue 1건
        │
        ├─ jira-knowledge-extraction Skill v0.9
        ├─ Knowledge JSON 생성
        └─ Python Validator
                │
                ├─ FAIL → 같은 Worker에서 수정/재검증
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
```

한 Issue가 PASS 또는 REVIEW_REQUIRED가 되기 전에는 다음 Issue로 이동하지 않는다. Worker/Reviewer 병렬 호출은 하지 않는다.

## 5. Agent 역할

### Orchestrator

- Jira 본문과 Knowledge 본문을 직접 읽지 않는다.
- Input/Output/Review 파일 경로와 짧은 상태만 관리한다.
- Worker와 Reviewer만 호출한다.
- Issue를 반드시 순차 처리한다.
- Gold/expected/test metadata를 사용하지 않는다.
- Jira 웹/API/MCP/Connector에 접근하지 않는다.
- Input 파일이 없으면 외부 재수집 없이 `INPUT_ERROR`로 종료한다.

### Worker

- 전달받은 Knowledge Input JSON 한 건만 처리한다.
- `jira-knowledge-extraction` Skill v0.9를 반드시 사용한다.
- 생성 직후 Python Validator를 실행한다.
- Validator FAIL이면 같은 Worker에서 최대 3회 구조 오류를 수정한다.
- REGENERATE 시 원본 Input과 이전 Review JSON을 읽고 처음부터 전체 Knowledge를 다시 만든다.
- Jira 웹/API/MCP/Connector에 접근하지 않는다.
- Validator 명령 외 Bash 실행을 허용하지 않는다.

### Defect Reviewer

- 현재 Input 한 건과 그 Knowledge 한 건만 비교한다.
- 점수를 먼저 정하지 않는다.
- Fact → Causal Claim → Evidence → Classification → Missing Knowledge → Duplication/Low-value 순서로 Audit한다.
- Reviewer score는 절대 품질 인증값이 아니라 결함 감소용 보조 지표다.
- 외부 Jira/웹/API/MCP 정보로 Knowledge를 보정하지 않는다.

## 6. Validator

실행:

```bash
python tools/jira_knowledge/validate_knowledge.py \
  <KNOWLEDGE_OUTPUT> \
  <KNOWLEDGE_INPUT>
```

검증 범위:

- 최상위 필드 계약
- `knowledge_schema_version == 0.1`
- Input/Output `issue_key` 일치
- 모든 Knowledge item의 `statement`/`evidence_refs` 구조
- Evidence reference 형식
- Evidence가 실제 Input에 존재하는지

Validator는 의미적 사실성, 인과관계 강도, 분류 적절성은 판단하지 않는다. 이 영역은 Defect Reviewer가 담당한다.

## 7. Review PASS 조건

아래 세 조건을 모두 만족해야 PASS다.

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

## 8. M4 실행 전 확인

- [ ] 실제 Jira Knowledge Input run을 확인한다.
- [ ] `manifest.status == completed`인지 확인한다.
- [ ] package warning이 없는지 확인한다.
- [ ] Issue JSON 수와 중복 issue_key를 확인한다.
- [ ] v0.9 Skill/Agent/Validator가 프로젝트에 존재한다.
- [ ] Agent가 `"*": deny` 기본 정책과 local-only 경계를 적용하고 있다.
- [ ] 실제 출력 경로를 합성 테스트 결과와 분리한다.
- [ ] 실제 Jira 1건으로 Worker → Validator → Reviewer E2E를 먼저 확인한다.
- [ ] 1건 통과 후 5건, 그 다음 30건으로 확장한다.

## 9. 금지사항

- Orchestrator가 Jira/Knowledge 본문을 직접 읽지 않는다.
- 한 Context에 30개 Issue 본문을 모두 적재하지 않는다.
- Worker/Reviewer를 배치 병렬 실행하지 않는다.
- Reviewer 점수만으로 Knowledge를 사실 원장처럼 신뢰하지 않는다.
- 합성 데이터의 Gold/expected를 실제 M4 실행에 사용하지 않는다.
- 실제 Jira와 합성 테스트 출력 경로를 섞지 않는다.
- Jira 웹/API/MCP/Connector를 Knowledge Extraction 단계에서 다시 사용하지 않는다.
- 입력이 없다고 외부 Jira에서 재수집하지 않는다.
