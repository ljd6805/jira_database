# Jira Knowledge Pipeline Agent Rules

이 파일은 이 repository에서 작업하는 Agent가 반드시 지켜야 하는 프로젝트 규칙이다.
사람용 상세 문서 정책은 `docs/DOCUMENTATION_POLICY.html`을 따른다.

## 0. 현재 Operational Source of Truth

새 구현/설계 작업 전에 반드시 다음 순서로 현재 맥락을 확인한다.

```text
docs/index.html
docs/VERSION_TERMINOLOGY_GUIDE.html
docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html
docs/architecture/jira_operational_two_loop_architecture.html
docs/architecture/jira_sync_contract.html
docs/architecture/jira_sync_state_schema_contract.html
```

현재 운영 아키텍처 기준:

```text
M0~M11 Functional MVP = DONE / PASS
Two-Loop Operational Architecture = FROZEN
D10 Latest-Only Processing = FIXED
현재 운영 규칙 = Sync Contract · 개정 3
현재 Operational State 설계 = 개정 3

Loop A = Source Sync
Loop B = Knowledge Processing / Publish
sync_issue_change = durable latest-only backlog boundary
```

`docs/architecture/jira_sync_contract_v2_baseline.html`,
`docs/architecture/jira_sync_state_schema_contract_v1_baseline.html`,
`docs/architecture/jira_sync_state_schema_contract_v2_baseline.html`과 단일 `sync_run`을 전제로 한 과거 표현은 **historical/superseded**이며 구현 기준으로 사용하지 않는다.

사람용 문서에서 bare `v1/v2/v3` 표현을 남발하지 않는다. 같은 대상 안에서만 개정 번호를 비교하며 `docs/VERSION_TERMINOLOGY_GUIDE.html`을 따른다. 단, 코드 상수·DB `PRAGMA user_version`·내부 식별자 `data-doc-shell="v1"`·`semantic_v2`처럼 기술적으로 고정된 이름은 그대로 사용한다.

## 1. Documentation Hub는 HTML 전용이다

- `docs/index.html`에서 연결하는 **로컬 문서 anchor는 전부 `.html`** 이어야 한다.
- Hub에서 `.md` 문서로 직접 링크하지 않는다.
- Overview / Design / Policy / Status / Completion / Troubleshooting / Decision Log 등 사람이 읽는 Hub 노출 문서는 HTML로 작성한다.
- 원본 실행 로그, Decision Log source, CHANGELOG 등은 Markdown으로 남길 수 있다.
- Markdown 로그를 Hub에서 읽게 해야 한다면 HTML companion을 만들고 Hub는 HTML에 링크한다.
- README.md, AGENTS.md, Skill 문서는 도구/저장소 동작을 위한 운영 Markdown으로 유지할 수 있다.
- legacy non-log Markdown은 기존 테스트/참조 호환 때문에 일시 보존할 수 있지만 새 Hub 링크 대상으로 사용하지 않는다.

## 1.1 Document Shell · 개정 1 고정 규칙

- `docs/index.html`은 내부 식별자 `data-hub-frame="v1"` 구조와 `docs/assets/hub-frame.css`를 사용한다.
- 모든 일반 HTML은 내부 식별자 `data-doc-shell="v1"`과 공통 shell CSS/JS를 포함한다.
- `이전 문서 / 문서 Hub / 다음 문서` 버튼은 항상 유지한다. 첫/마지막 문서는 숨기지 않고 disabled로 표시한다.
- 새 HTML 작성 후 `python tools/docs/sync_document_shell.py --write`를 실행하고 `--check`를 통과시킨다.
- Hub 기본 5개 영역 또는 shell 계약을 바꿀 때는 임의 수정하지 말고 Documentation Policy와 Framework 문서를 함께 갱신한다.

## 2. Milestone HTML은 필수 산출물이다

- 각 Milestone `M<N>`이 `CURRENT`가 되는 시점부터 `docs/status/M<N>_*.html` 정적 HTML 시각 문서를 유지한다.
- Milestone이 `DONE`이 된 뒤에도 해당 HTML을 영구 보존한다.
- 기존 HTML을 Markdown으로 대체하거나, Markdown이 있으니 HTML이 불필요하다고 판단해서는 안 된다.
- 사람이 읽는 공식 경로는 `docs/index.html` → HTML 문서로 유지한다.

## 3. 구현 변경과 HTML 문서 변경은 같은 작업이다

다음 중 하나가 바뀌면 같은 작업 단위에서 관련 HTML을 반드시 갱신한다.

- 기능 동작
- 데이터 계약 / Schema / Entity / Cardinality
- ID / Evidence / Active-History 정책
- 실행 방법 / CLI / 검증 방법
- Milestone 상태 / Gate / 다음 단계
- 실제 검증 결과와 수치
- Loop / Scheduler / Queue / Processing 정책

필요 시 함께 갱신할 Current Source of Truth:

```text
README.md
docs/index.html
docs/PIPELINE_OVERVIEW.html
docs/status/jira_knowledge_db_current_status.html
docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html
docs/architecture/jira_operational_two_loop_architecture.html
docs/architecture/jira_sync_contract.html
docs/architecture/jira_sync_state_schema_contract.html
docs/architecture/jira_data_relationship_map.html
```

작업 종료 전에 코드와 문서가 같은 상태인지 확인한다. 코드만 변경하고 HTML 갱신을 다음 작업으로 미루지 않는다.

## 4. Milestone HTML 삭제는 사용자 승인 없이는 금지한다

- `docs/status/M*.html` Milestone 문서를 삭제, 이름 변경, 다른 형식으로 대체, archive로 이동하는 행위를 기본적으로 금지한다.
- HTML 삭제가 기술적으로 반드시 필요하면 **삭제하기 전에 사용자에게 이유와 영향 범위를 설명하고 명시적 승인을 받아야 한다.**
- 현재 작업에서 사용자의 명시적 삭제 승인을 확인할 수 없다면 삭제하지 않는다.
- 정리가 필요하면 삭제 대신 기존 HTML을 보존하고 superseded / historical 표시를 추가하는 방식을 우선한다.
- 사용자의 승인 없이 이 규칙 자체나 관련 regression test를 약화하거나 제거해서는 안 된다.

## 5. HTML은 독립적으로 읽을 수 있어야 한다

- 핵심 본문은 HTML 파일 자체에 정적으로 포함한다.
- 외부 CDN, 원격 문서, 압축 fragment가 없어도 핵심 내용을 읽을 수 있어야 한다.
- Milestone 문서에서 `fetch()` + `DecompressionStream`으로 외부/분할 payload를 복원하는 loader 방식을 사용하지 않는다.
- HTML이 코드/검증 사실보다 더 강한 사실을 새로 만들지 않는다.

## 6. 문서 Gate도 테스트 대상이다

최소 다음 검증을 유지한다.

```text
pytest tests/test_documentation_hub_html_only.py
pytest tests/test_documentation_current_state.py
pytest tests/test_document_shell_consistency.py
```

문서 테스트는 다음 회귀를 막아야 한다.

- docs/index.html의 `.md` 로컬 링크 재등장
- Hub가 가리키는 HTML 파일 누락
- DONE/CURRENT Milestone의 HTML 누락
- M0~현재 HTML 삭제
- 압축 fragment loader 회귀
- 오래된 Milestone 상태로의 퇴행
- HTML 보존/사용자 승인 규칙 삭제
- 현재 Two-Loop + D10 Latest-Only + Sync Contract 개정 3 / State 설계 개정 3이 historical 문서로 퇴행
- 버전 숫자를 대상 없이 써서 State DB / Knowledge DB / 문서 UI를 같은 버전 계열처럼 오해시키는 회귀

문서 테스트가 실패하면 구현 작업도 완료된 것으로 보지 않는다.
