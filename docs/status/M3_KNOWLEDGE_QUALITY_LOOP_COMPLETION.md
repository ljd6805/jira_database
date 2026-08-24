# M3 Knowledge Quality Loop Completion Record

복원 기준일: 2026-08-24  
완료 근거: 2026-08-21 Source-of-Truth에서 M3 DONE으로 고정  
최종 runtime artifact materialization: 2026-08-21 · PR #6  
단계: **M3 · Knowledge Quality Loop / Context Isolation**

이 문서는 M2에서 확정한 Knowledge Schema / Skill을 실제 다건 처리 가능한 품질 Loop로 운영하기 위해 어떤 책임을 Agent와 deterministic code에 나눴는지, 저장소의 Source-of-Truth와 PR #6, 현재 Runtime 문서를 대조해 복원한 Completion Record다.

> 범위 주의: 실제 Jira 30건 실행, Human Validation, `.ignore` 문제 해결, deterministic run summarizer는 M4에서 수행한 후속 검증/보강이다. M3 완료 기록에 소급해 섞지 않는다.

---

## 1. M3 목적

M2에서 다음 계약은 이미 결정됐다.

```text
[KNOWLEDGE INPUT]
        ↓
Knowledge Extraction Skill
        ↓
[KNOWLEDGE]
Schema v0.1
```

하지만 이것만으로는 실제 다건 처리 시스템이 아니다.

다음 문제가 남아 있었다.

1. 여러 Issue를 한 Primary Context에서 계속 읽으면 Context가 누적된다.
2. Worker가 자기 출력을 스스로 평가하면 오류를 놓칠 가능성이 높다.
3. JSON 구조 오류와 의미 오류를 같은 LLM 판단에 맡기면 불필요하게 비결정적이다.
4. Reviewer 점수 하나만 보고 통과시키면 사실 반전이나 인과 과장이 숨을 수 있다.
5. 재생성 시 기존 잘못된 Knowledge를 정답처럼 고쳐 쓰면 오류가 고착될 수 있다.
6. 한 Issue의 반복 작업이 다른 Issue Context와 섞이면 품질과 재현성이 떨어진다.

M3의 목적은 이를 해결하는 실행 구조를 만드는 것이었다.

```text
Orchestrator
    ↓
Fresh Worker · Issue 1건
    ↓
Python Validator
    ↓
Fresh Defect Reviewer
    ↓
PASS / REGENERATE
```

---

## 2. Source-of-Truth에 고정된 M3 정의

2026-08-21 `docs: add milestone source of truth` commit은 M3를 다음과 같이 기록했다.

```text
M3 DONE
목표   : 256K Context 품질 Loop
Action : Orchestrator 경로 관리
         → Worker 1건
         → Python Validator
         → Defect Reviewer
         → 필요 시 새 Worker
산출물 : 3 Agent · Validator · Review JSON
Gate   : Issue별 순차 처리
         Reviewer = 보조 필터
         → M4
```

같은 문서는 256K Context 대응 원칙을 다음처럼 고정했다.

```text
Orchestrator는 Jira 본문을 읽지 않는다.
Worker / Reviewer는 Issue 한 건만 child context에서 읽는다.
운영 규모가 커지면 Primary Session도 30~50건 단위로 새로 시작한다.
```

즉 M3의 핵심은 “Reviewer를 하나 더 붙였다”가 아니라 **Context 격리 + 역할 분리 + deterministic gate + 결함 중심 review loop**를 함께 설계한 것이다.

---

## 3. 최종 Runtime Artifact

PR #6에서 다음 파일이 저장소에 추가됐다.

```text
.opencode/
└─ agents/
   ├─ jira-knowledge-orchestrator.md
   ├─ jira-knowledge-worker.md
   └─ jira-knowledge-reviewer.md

tools/
└─ jira_knowledge/
   └─ validate_knowledge.py

docs/
└─ KNOWLEDGE_EXTRACTION_RUNTIME.md
```

PR #6 제목:

```text
feat: add Jira knowledge runtime v0.9
```

PR 본문은 실행 구조를 다음처럼 명시한다.

```text
Orchestrator
→ fresh Worker
→ Python Validator
→ fresh Defect Reviewer
```

그리고 한 Issue가 `PASS` 또는 `REVIEW_REQUIRED`가 된 뒤에만 다음 Issue로 이동한다.

PR 추가 시 원본 v0.9 package와 Agent/Validator Git blob SHA 일치를 확인했고 Python Validator는 `py_compile`을 통과했다.

---

## 4. 결정 1 — Orchestrator는 본문 분석자가 아니다

Orchestrator의 역할은 **파일 경로와 짧은 상태를 관리하는 것**으로 제한했다.

하지 않는 일:

```text
Jira Issue 본문 분석
Knowledge 본문 분석
원인 / 결과 판단
Reviewer 대신 품질 판정
```

하는 일:

```text
입력 파일 경로 결정
출력 파일 경로 결정
Worker 호출
Validator 통과 여부 확인
Reviewer 호출
PASS / REGENERATE / REVIEW_REQUIRED 상태 관리
다음 Issue로 이동할지 판단
```

이 결정의 목적은 Primary Context가 Issue 본문으로 계속 비대해지는 것을 막는 것이다.

```text
Primary Context
= workflow state

Child Context
= one Issue semantics
```

으로 분리했다.

---

## 5. 결정 2 — Issue 단위 순차 처리

M3는 여러 Issue를 병렬로 처리하지 않는다.

핵심 규칙:

```text
한 번에 Issue 하나
Worker / Reviewer 병렬 호출 금지
현재 Issue가 terminal state가 되기 전 다음 Issue 금지
```

Terminal state:

```text
PASS
REVIEW_REQUIRED
INPUT_ERROR  # 이후 M4 local-boundary hardening에서 명시적으로 강화
```

M3 핵심 Loop 관점에서는 `PASS` 또는 최대 시도 후 `REVIEW_REQUIRED`가 되어야 다음 Issue로 넘어간다.

이 선택은 처리량보다 다음을 우선한 것이다.

- Issue별 결과와 Review 이력의 명확한 대응
- 재생성 횟수 추적
- Context 격리
- 실패 원인 분석
- 실제 파일럿에서 품질 Loop 자체를 먼저 검증

---

## 6. 결정 3 — Worker는 매 Attempt마다 Fresh Context

Attempt 1:

```text
새 Worker
→ Knowledge Input 한 건 읽기
→ Skill v0.9 적용
→ Knowledge JSON 생성
```

Reviewer가 `REGENERATE`를 내리면 기존 Worker를 계속 쓰지 않는다.

```text
새 Worker Context
→ 원본 Knowledge Input 다시 읽기
→ 이전 Review JSON 읽기
→ Knowledge 전체를 처음부터 재생성
```

Fresh Worker를 쓰는 이유:

1. 이전 생성 과정의 잘못된 추론이 Context에 남는 것을 줄임
2. Reviewer feedback을 새 관점에서 반영
3. “내가 전에 이렇게 판단했으니 맞을 것”이라는 self-anchoring 완화
4. Issue별 Attempt가 독립적인 품질 개선 단위가 됨

---

## 7. 결정 4 — 재생성은 Patch가 아니라 Full Regeneration

REGENERATE 시 Worker에 전달하는 핵심 입력:

```text
MODE=REGENERATE

[KNOWLEDGE INPUT]
<original input path>

[KNOWLEDGE OUTPUT]
<output path>

[REVIEW FEEDBACK]
<previous review json path>
```

Worker는 Review JSON의 다음 내용을 읽는다.

```text
critical_issues
major_issues
audit_findings
improvement_points
```

그러나 **기존 Knowledge 문장을 정답처럼 복사해 부분 수정하지 않는다.**

항상 원본 Input을 다시 읽고 Knowledge 전체를 재생성한다.

이 결정은 잘못된 구조나 과장된 인과관계를 작은 문장 수정으로 덮어두는 것을 막기 위한 것이다.

---

## 8. 결정 5 — 구조 검증은 Python Validator가 담당

Knowledge JSON은 먼저 deterministic Validator를 통과해야 한다.

실행 계약:

```bash
python tools/jira_knowledge/validate_knowledge.py \
  <KNOWLEDGE_OUTPUT> \
  <KNOWLEDGE_INPUT>
```

Validator 검증 범위:

```text
최상위 필드 계약
knowledge_schema_version == 0.1
Input / Output issue_key 일치
statement 구조
Evidence refs 구조
Evidence reference 형식
해당 Evidence가 Input에 실제 존재하는지
```

이 구분의 핵심은 다음과 같다.

```text
JSON / Schema / Reference existence
→ Python이 결정적으로 검증

사실 의미 / 인과 / 누락 / 분류
→ Reviewer LLM이 검토
```

구조 오류를 LLM Reviewer에게 맡기지 않으므로 Reviewer Context와 토큰을 의미 품질에 집중시킬 수 있다.

Validator가 실패하면 같은 Worker가 구조 오류를 수정하고 다시 Validator를 통과시킨 뒤 Reviewer로 이동한다.

---

## 9. 결정 6 — Reviewer는 Fresh Context

Worker가 만든 Knowledge를 Worker 자신이 최종 평가하지 않는다.

Reviewer는 **현재 Knowledge Input 한 건과 Knowledge Output 한 건만** 비교하는 새 Subagent Context다.

사용하지 않는 것:

```text
Gold answer
expected output
다른 Issue의 Knowledge
이전 Issue review 결과
```

목표는 정답 문장을 맞히는 것이 아니라:

```text
이 Knowledge가 검색을 왜곡할 결함을 만들었는가?
```

를 찾는 것이다.

이 때문에 Reviewer는 “예쁜 문장 평가자”가 아니라 **Defect Reviewer**로 정의됐다.

---

## 10. 결정 7 — 점수보다 Defect Audit가 먼저다

Reviewer의 가장 중요한 규칙:

> **점수를 먼저 정하지 않는다.**

반드시 Audit를 수행한 뒤:

```text
Critical 판단
→ Major 판단
→ Minor 판단
→ 마지막에 score 계산
```

한다.

최종 Audit 순서:

```text
1. Fact Audit
2. Causal Claim Audit
3. Evidence Audit
4. Classification Audit
5. Missing Knowledge Audit
6. Duplication / Low-value Audit
```

---

## 11. Fact Audit

모든 Knowledge statement를 원자 사실로 분해한다.

확인:

```text
Input에 실제로 있는가?
의미가 반대로 바뀌지 않았는가?
시점 / 수치 / 대상 / 상태가 바뀌지 않았는가?
```

대표 Critical 후보:

```text
입력에 없는 핵심 사실 생성
입력 사실 반전
수행하지 않은 작업을 완료로 기록
```

M2의 “입력에 없는 사실을 만들지 않는다”를 Reviewer 쪽 독립 Audit로 만든 것이다.

---

## 12. Causal Claim Audit

Knowledge에서 강한 인과/확정 표현을 별도로 찾는다.

예:

```text
원인
주원인
원인이 아니다
무관
배제
기인
때문
확인됐다
해결됐다
최적
```

검사 질문:

```text
A. Input이 직접 그 인과를 확정했는가?
OR
B. 충분히 통제된 비교/개입이 그 강도를 직접 지지하는가?
```

대표 오류:

```text
다른 조건에서도 발생
→ 원인이 아니다        X

못 찾았다
→ 배제했다             X

영향일 수도 있다
→ 주원인이다           X

개선됐다
→ 해결됐다             X
```

검색 판단을 바꿀 수준의 certainty 강화는 Major, 심각한 최종 원인 왜곡은 Critical 후보로 둔다.

---

## 13. Evidence Audit

모든 statement를 원자 사실 A/B/C로 나누고 각각 어떤 `evidence_refs`가 직접 뒷받침하는지 대조한다.

```text
statement fact A → direct evidence?
statement fact B → direct evidence?
statement fact C → direct evidence?
```

대표 Major:

- Summary 핵심 주장에 직접 근거 없음
- 핵심 Finding 주요 사실에 직접 근거 없음
- 복합 statement의 핵심 인과 주장 근거 누락

M2 Schema가 Evidence 필드의 존재를 강제했다면, M3 Reviewer는 **그 Evidence가 statement 의미를 실제로 지지하는지**를 검토한다.

---

## 14. Classification Audit

각 Knowledge 영역의 의미 경계를 독립적으로 확인한다.

```text
key_findings
→ 중요한 관찰 / 비교 / 중간 시험인가?

actions_and_decisions
→ 실제 수행 / 명시적 Decision인가?

outcomes
→ 후속 검증이 남은 중간 결과를 최종 Outcome으로 올리지 않았는가?

open_items
→ 실제 미해결인가?
```

대표 Major:

```text
미완료 중간 결과를 Outcome 처리
최종 Decision 누락
확인되지 않음을 검증 미완료로 상태 왜곡
동일 핵심 상태가 여러 영역에 중복되어 해석 혼란
```

---

## 15. Missing Knowledge Audit

정확한 문장만 남기는 것으로는 충분하지 않다.

Input의 시간 흐름을 다시 훑어 검색 가치가 높은 핵심 이벤트가 빠졌는지 검사한다.

특히:

```text
초기 가설을 뒤집은 반증
중요한 비교 시험
trade-off
실제 최종 Decision
재발방지 / 표준 변경
채택된 결과
중요한 미해결 항목
```

이 Audit를 추가한 이유는 **틀린 사실뿐 아니라 중요한 사실의 누락도 검색 결과를 왜곡하기 때문**이다.

---

## 16. Duplication / Low-value Audit

확인:

```text
같은 핵심 사실을 여러 category에 반복했는가?
단순 일정이 Knowledge를 차지하는가?
파일 전달 / 잡담 / 저가치 절차가 의미 압축을 흐리는가?
```

Knowledge는 원문 복사본이 아니라 검색용 semantic compression이므로 정확성뿐 아니라 signal density도 관리한다.

---

## 17. 결정 8 — PASS는 점수 하나가 아니다

최종 PASS 조건:

```text
score >= 8.5
AND critical_error == false
AND major_issue_count == 0
```

Hard cap:

```text
Critical >= 1
→ score <= 7.9

Major >= 1
→ score <= 8.4
```

이 결정은 높은 평균 점수가 심각한 단일 결함을 가리는 것을 막기 위한 것이다.

예를 들어 문체, 압축, 일반 품질이 좋아도 핵심 인과를 잘못 확정했다면 PASS할 수 없다.

---

## 18. Review JSON 계약

Reviewer는 상세 결함을 대화에 길게 반환하는 대신 JSON으로 보존한다.

대표 구조:

```text
issue_key
score
verdict
critical_error
major_issue_count
category_scores

audit_findings
  fact_audit
  causal_claim_audit
  evidence_audit
  classification_audit
  missing_knowledge_audit
  duplication_audit

critical_issues
major_issues
improvement_points
```

이 Review JSON이 다음 Attempt Worker의 입력이 된다.

Orchestrator에는 짧은 상태만 돌려 Primary Context 비대를 줄인다.

---

## 19. 결정 9 — 최대 3 Attempt

Issue Loop:

```text
Attempt 1
  Worker → Validator → Reviewer

REGENERATE
  Attempt 2
  Fresh Worker → Validator → Fresh Reviewer

REGENERATE
  Attempt 3
  Fresh Worker → Validator → Fresh Reviewer

그래도 PASS 실패
  → REVIEW_REQUIRED
```

무한 반복하지 않는다.

이유:

- 동일 LLM 구조에서 무한 regeneration의 한계
- 시간/비용 상한 필요
- 반복 실패는 사람이 봐야 할 신호
- 운영 시 terminal state가 필요

---

## 20. 결정 10 — Reviewer Score는 품질 인증서가 아니다

M3 Source-of-Truth는 Reviewer를 **보조 필터**로 정의했다.

즉:

```text
Reviewer PASS
!= 사실 100% 보증
```

Reviewer도 LLM이기 때문에:

- 놓치는 인과 과장
- 미묘한 Evidence 부족
- 분류 오판

이 있을 수 있다.

따라서 M3에서 Review Loop의 목적은:

```text
오류 확률 감소
자동 결함 탐지
재생성 trigger 제공
```

이지 최종 사실 인증이 아니다.

실제 Jira 데이터에서 이 한계를 사람이 직접 확인하는 작업은 M4로 넘겼다.

---

## 21. 결정 11 — 256K Context를 “크게 쓰는 것”보다 “안 쌓이게 하는 것”

M3의 Context 전략은 큰 Context Window를 최대한 채우는 것이 아니다.

오히려:

```text
Orchestrator
→ 본문을 읽지 않음

Worker
→ Issue 한 건만 읽음

Reviewer
→ 같은 Issue의 Input + Knowledge만 읽음

다음 Issue
→ 새 child context
```

형태로 설계했다.

즉 256K는 안전망이지, 모든 Jira Issue를 한 대화에 밀어 넣기 위한 목표 용량이 아니다.

운영 규모가 커질 때 Primary Session도 30~50건 단위로 새로 시작하는 방식을 계획했다.

---

## 22. Permission / Local Input Boundary와 M3·M4 구분

PR #6 초기 Runtime에서 이미 Agent별 permission을 제한했지만, 실제 Jira 파일럿 직전/중에 다음 보강이 추가됐다.

```text
7c22556
fix: restrict M4 knowledge runtime to local inputs

→ Jira web / REST API / MCP / connector / websearch 차단 강화
→ local Knowledge Input을 유일한 사실 source로 명시
→ INPUT_ERROR 동작 강화
```

이 보강은 **M3의 역할 분리 원칙을 M4 실제 환경에서 더 강하게 enforce한 것**이다.

따라서 M3 완료 Gate 자체의 원래 산출물과 구분해서 보존한다.

---

## 23. `.ignore`와 deterministic run summary도 M4 후속 보강

다음 문제도 실제 30건 실행 단계에서 발견됐다.

```text
d89fb77
fix: expose M4 knowledge paths to OpenCode

→ Git은 data/를 계속 ignore
→ OpenCode/ripgrep은 knowledge_input / knowledge path 탐색 가능
```

또한:

```text
a97e609
fix: make M4 knowledge run reporting deterministic

→ LLM 최종 집계 제거
→ summarize_knowledge_run.py로 집계 책임 이동
```

이들은 M3 Quality Loop 설계 자체가 아니라 **M4 실제 운영에서 발견한 runtime/tooling hardening**이다.

M3 문서에서 이 사실을 남기는 이유는 현재 Runtime 문서를 읽을 때 “이 기능도 처음부터 M3에 있었나?”라는 혼동을 막기 위해서다.

---

## 24. M3 검증 범위

M3 완료 시점의 검증 근거는 다음이다.

### 합성 Knowledge Extraction 기반 검증

Source-of-Truth는 M2/M3를 다음 상태로 기록했다.

```text
Schema v0.1
Skill v0.9
Pro Worker + Pro Reviewer
3-Agent Review Loop
합성 튜닝 종료
Reviewer = 보조 필터
```

### Runtime artifact 검증

PR #6에서:

```text
Skill / Agent / Validator package Git blob SHA 일치 확인
validate_knowledge.py Python py_compile PASS
```

### 실제 Jira 검증은 아직 아님

M3 Gate 시점에는:

```text
실제 Jira 30건 전체 Run
Human Validation 5건
실제 Attempt 분포
실제 Critical/Major 발생 이력
```

을 M3 완료 조건에 포함하지 않았다.

그 검증은 다음 M4의 목적이었다.

---

## 25. M3에서 하지 않은 것

```text
실제 Jira 30건 전체 Knowledge 생성
Human Validation
실제 run deterministic 집계
Knowledge 분포 Profiling
DB Schema
SQLite materialization
Chunk / Embedding
FAISS / Retrieval
MCP
```

M3의 완료 의미는 **Quality Loop 실행 계약이 합성 검증 기준으로 안정화되어 실제 Jira 파일럿을 시작할 수 있게 됐다**는 것이다.

---

## 26. M3 Gate 판정

- [x] Orchestrator / Worker / Reviewer 역할 분리
- [x] Orchestrator 본문 비분석 원칙
- [x] Issue 1건 단위 child context
- [x] Issue별 순차 처리
- [x] Fresh Worker per Attempt
- [x] Fresh Reviewer per Review
- [x] Worker / Reviewer 병렬 처리 금지
- [x] Python Validator deterministic gate
- [x] Input / Output issue key consistency 검증
- [x] Evidence reference 존재 검증
- [x] Fact Audit
- [x] Causal Claim Audit
- [x] Evidence Audit
- [x] Classification Audit
- [x] Missing Knowledge Audit
- [x] Duplication / Low-value Audit
- [x] `score >= 8.5 AND Critical=0 AND Major=0` PASS 계약
- [x] Critical / Major score hard cap
- [x] Review JSON 보존
- [x] Regenerate 시 원본 Input + Review 사용
- [x] 기존 Knowledge patch가 아닌 full regeneration
- [x] 최대 3 Attempt
- [x] 실패 시 REVIEW_REQUIRED
- [x] Reviewer를 품질 인증이 아닌 보조 필터로 정의
- [x] 256K Context 누적 방지 전략
- [x] Runtime package / Validator 기본 검증

## **M3 Gate: PASS / DONE**

다음 단계는 **M4 · 실제 Jira 30건 Knowledge Extraction + Human Validation**이다.

---

## 27. M3 → M4 Handoff

M4에 전달된 고정 계약:

```text
Input
= M1 [KNOWLEDGE INPUT] Issue JSON

Semantic Contract
= M2 Schema v0.1 + Skill v0.9

Runtime
= M3 Orchestrator
  → Fresh Worker
  → Python Validator
  → Fresh Defect Reviewer
  → PASS / REGENERATE

Model
= Pro

PASS
= score >= 8.5
  AND Critical == 0
  AND Major == 0

Max Attempts
= 3
```

M4에서 확인해야 할 질문:

1. 실제 Jira 30건에서 이 Loop가 끝까지 실행되는가?
2. Reviewer PASS가 실제 원문과 사람 검토에서도 충분히 신뢰 가능한가?
3. 어떤 결함이 반복적으로 발생하는가?
4. 실제 Knowledge가 검색용 의미 압축으로 충분한가?
5. 다음 DB / Chunk 설계에 사용할 수 있을 만큼 출력 분포가 안정적인가?

---

## 28. 주요 근거 Commit / 문서

- [`f593a00` · milestone source of truth](https://github.com/ljd6805/jira_database/commit/f593a00b2bec2c85aec669c5d4620959386d2e57)
- [PR #6 · Jira knowledge runtime v0.9](https://github.com/ljd6805/jira_database/pull/6)
- [`6ba2b46` · add Jira knowledge runtime v0.9](https://github.com/ljd6805/jira_database/commit/6ba2b4665196eee60e5b9b0737d0ab9bfbeb8e83)
- `.opencode/agents/jira-knowledge-orchestrator.md`
- `.opencode/agents/jira-knowledge-worker.md`
- `.opencode/agents/jira-knowledge-reviewer.md`
- `tools/jira_knowledge/validate_knowledge.py`
- `docs/KNOWLEDGE_EXTRACTION_RUNTIME.md`
- `.opencode/skills/jira-knowledge-extraction/CHANGELOG.md`

### M4 후속 Hardening 참고

- [`7c22556` · local-only M4 input boundary](https://github.com/ljd6805/jira_database/commit/7c2255664f1b8fab2dbb8a86cff681d20d71260d)
- [`d89fb77` · OpenCode data path discovery fix](https://github.com/ljd6805/jira_database/commit/d89fb77af7b0c9b2c17a0c8d5afd3e008a229413)
- [`a97e609` · deterministic M4 run reporting](https://github.com/ljd6805/jira_database/commit/a97e609dab4bd916760675a0745898012fad1d3d)
