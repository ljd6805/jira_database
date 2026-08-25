# M7 Real-run Validation Log

기준일: 2026-08-25  
상태: **IN PROGRESS**

이 문서는 M7 SQLite Materialization의 실제 Jira Pilot Run `20260804T043628Z` 검증 과정에서 발견한 문제와 해결을 시간 순서대로 기록한다.

## 1. Preflight

실제 로컬 Pilot artifact 확인:

```text
Knowledge issue JSON = 30
Review JSON          = 37
```

M5 baseline과 일치하는 입력 집합이 존재함을 확인했다.

## 2. 실행 문제 1 — src layout import 실패

최초 실행:

```text
python tools/jira_knowledge/validate_m7_real_run.py ...
→ ModuleNotFoundError: No module named 'jira_collector'
```

원인:

- repository는 `src/jira_collector` layout을 사용한다.
- tool script를 직접 실행할 때 `src`가 자동으로 `sys.path`에 들어가지 않았다.
- 문서는 "프로젝트 루트에서 한 명령" 실행을 계약으로 두고 있었으므로 사용자 환경 문제가 아니라 Gate 실행성 결함으로 판단했다.

해결:

- `validate_m7_real_run.py`
- `materialize_knowledge_db.py`

두 tool이 repository `src` 경로를 스스로 bootstrap하도록 수정했다.

## 3. 실행 문제 2 — M4 Review Schema v0.3 위반 artifact

두 번째 Gate 실행에서:

```text
오류: 필수 문자열이 없습니다: finding.message
```

실데이터 37개 Review를 진단한 결과 다음 artifact를 확인했다.

```text
ISSUE-1137.review.attempt1.json
critical_issues[0] = {
  "type": "fact",
  "location": "actions_and_decisions[2]",
  "message": "..."
}

ISSUE-1306.review.attempt1.json
critical_issues[0] = {
  "type": "certainty",
  "location": "issue_summary",
  "message": "..."
}
critical_issues[1] = {
  "type": "fact",
  "location": "issue_summary",
  "message": "..."
}
```

Git history의 M4 Skill v0.9 최초 등록 commit까지 확인한 결과 당시 Review Schema는 이미 **v0.3**이었고 `critical_issues`는 `string[]` 계약이었다.

따라서 이 문제는 "옛 schema version"이 아니라 다음과 같이 해석한다.

```text
Review Schema v0.3 계약
→ critical_issues: string[]

M4 실제 Reviewer output 일부
→ critical_issues: {type, location, message}[]

즉 실제 Reviewer artifact 2개가 schema v0.3 계약을 위반했다.
```

M4 Runtime에는 Knowledge용 deterministic validator는 있었지만 Review artifact 전체를 JSON Schema로 강제하는 별도 deterministic Gate가 없었기 때문에 해당 출력이 historical artifact로 남았다.

### 결정

1. `review_schema_version`은 당시 계약대로 **0.3**으로 기록한다.
2. 실제 M4 Review JSON을 현재 schema에 맞춰 사후 수정하지 않는다.
3. schema 위반 형태도 당시 실행 결과이므로 history/provenance로 보존한다.
4. M7 loader에 명시적인 compatibility layer를 둔다.

```text
critical_issues[] string
→ finding_type="", location="", message=<string>

critical_issues[] object
→ finding_type=type, location=location, message=message
```

둘 다 `review_finding(finding_group='critical')`로 저장한다.

회귀 방지를 위해 `tests/knowledge_db/test_materializer.py`에 legacy/nonconformant object + schema-conformant string을 함께 materialize하는 integration test를 추가했다.

## 4. 실행 문제 3 — Knowledge Evidence 중복 1회

다음 Gate 실행에서:

```text
오류: Knowledge Item Evidence가 중복됐습니다: <knowledge_item_id>
```

실제 30개 Knowledge JSON 전체를 검사한 결과:

```text
Knowledge files          = 30
M5 profile evidence count= 503
Raw evidence refs        = 503
Unique per-item refs     = 502
Duplicate occurrences    = 1
Items with duplicates    = 1
```

유일한 중복:

```text
AI5-1270.json
key_findings[2]

[
  "comment:2717096",
  "comment:2720803",
  "comment:2720803"
]
```

Knowledge Schema v0.1은 `evidence_refs.uniqueItems = true`이므로 이 artifact는 당시 Schema 계약을 위반한다.
하지만 M3/M4 `validate_knowledge.py`는 Evidence 형식과 source 존재 여부만 검사했고 **중복 검사를 구현하지 않았기 때문에** Pilot을 통과했다.

### 결정

원본 `AI5-1270.json`은 수정하지 않는다.

```text
M5 raw profile
→ Evidence ref 503

M7 canonical SQLite
→ 동일 Knowledge Item 안의 동일 Evidence는 첫 occurrence만 materialize
→ Evidence row 502
```

DB의 다음 M6 제약은 그대로 유지한다.

```text
UNIQUE(knowledge_item_id, evidence_ref)
```

M7 loader는 historical duplicate의 **첫 occurrence raw ordinal**을 유지하고 이후 중복만 건너뛴다. 따라서 historical Knowledge 전체 내용은 `knowledge_content_hash`로 계속 추적 가능하며, SQLite에는 의미 없는 중복 row를 만들지 않는다.

M7 Gate는 이제 다음 값을 분리해 출력·검사한다.

```text
M5 raw Evidence ref count       = 503
M7 canonical Evidence row count = 502
Duplicate Evidence occurrences  = 1
Duplicate Item count             = 1
```

향후 새 Knowledge에는 같은 문제가 들어오지 않도록 `validate_knowledge.py`에 `evidence_refs` 중복 검사를 추가했다.

## 5. 다음 검증 순서

```text
1. 최신 main pull
2. targeted tests 실행
3. M7 real-run Gate --reset 재실행
4. PASS/FAIL 결과 분석
5. PASS 시 M7 Completion/HTML/Current Source of Truth 동기화
```

M7 Gate가 PASS되기 전에는 M8 Chunk/BGE-M3로 이동하지 않는다.
