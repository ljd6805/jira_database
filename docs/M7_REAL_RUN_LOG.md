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

## 3. 실행 문제 2 — M4 legacy `critical_issues` 형식

두 번째 Gate 실행에서:

```text
오류: 필수 문자열이 없습니다: finding.message
```

실데이터 37개 Review를 진단한 결과 다음 legacy artifact를 확인했다.

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

현재 Review Schema v0.3은 `critical_issues`를 string array로 정의하지만 M4 실제 historical artifact에는 `{type, location, message}` object가 존재한다.

### 결정

실제 M4 artifact를 현재 schema에 맞춰 수정하지 않는다.

이유:

- M4 artifact는 당시 실행 결과이자 감사 가능한 history다.
- historical source를 사후 변환하면 provenance를 훼손한다.
- M7의 역할은 legacy history를 가능한 그대로 materialize하는 것이다.

따라서 M7 loader에 compatibility layer를 둔다.

```text
critical_issues[] string
→ finding_type="", location="", message=<string>

critical_issues[] object
→ finding_type=type, location=location, message=message
```

둘 다 `review_finding(finding_group='critical')`로 저장한다.

회귀 방지를 위해 `tests/knowledge_db/test_materializer.py`에 legacy object + current string을 함께 materialize하는 integration test를 추가했다.

## 4. 다음 검증 순서

```text
1. 최신 main pull
2. targeted knowledge_db test 실행
3. M7 real-run Gate --reset 재실행
4. PASS/FAIL 결과 분석
5. PASS 시 M7 Completion/HTML/Current Source of Truth 동기화
```

M7 Gate가 PASS되기 전에는 M8 Chunk/BGE-M3로 이동하지 않는다.
