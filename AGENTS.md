# Jira Knowledge Pipeline Agent Rules

이 파일은 이 repository에서 작업하는 Agent가 반드시 지켜야 하는 프로젝트 규칙이다.
상세 문서 정책은 `docs/DOCUMENTATION_POLICY.md`를 함께 따른다.

## 1. Milestone HTML은 필수 산출물이다

- 각 Milestone `M<N>`이 `CURRENT`가 되는 시점부터 `docs/status/M<N>_*.html` 정적 HTML 시각 문서를 유지한다.
- Milestone이 `DONE`이 된 뒤에도 해당 HTML을 영구 보존한다.
- Markdown Completion Record / 설계 문서는 상세 기준본으로 함께 유지할 수 있지만 **Markdown이 HTML을 대체할 수 없다.**
- 기존 HTML을 Markdown으로 치환하거나, Markdown이 있으니 HTML이 불필요하다고 판단해서는 안 된다.
- `docs/index.html`에서 M0부터 현재 Milestone까지 HTML과 기준 Markdown을 모두 찾을 수 있어야 한다.

## 2. 구현 변경과 HTML 문서 변경은 같은 작업이다

다음 중 하나가 바뀌면 같은 작업 단위에서 관련 HTML을 반드시 갱신한다.

- 기능 동작
- 데이터 계약 / Schema / Entity / Cardinality
- ID / Evidence / Active-History 정책
- 실행 방법 / CLI / 검증 방법
- Milestone 상태 / Gate / 다음 단계
- 실제 검증 결과와 수치

필요 시 함께 갱신할 Current Source of Truth:

```text
README.md
docs/PIPELINE_OVERVIEW.md
docs/index.html
docs/status/jira_knowledge_db_current_status.html
docs/architecture/jira_data_relationship_map.*
```

작업 종료 전에 코드와 문서가 같은 상태인지 확인한다. 코드만 변경하고 HTML 갱신을 다음 작업으로 미루지 않는다.

## 3. Milestone HTML 삭제는 사용자 승인 없이는 금지한다

- `docs/status/M*.html` Milestone 문서를 삭제, 이름 변경, 다른 형식으로 대체, archive로 이동하는 행위를 기본적으로 금지한다.
- HTML 삭제가 기술적으로 반드시 필요하다고 판단되면 **삭제하기 전에 사용자에게 이유와 영향 범위를 설명하고 명시적 승인을 받아야 한다.**
- 현재 작업에서 사용자의 명시적 삭제 승인을 확인할 수 없다면 삭제하지 않는다.
- 정리가 필요하면 삭제 대신 기존 HTML을 보존하고 superseded / historical 표시를 추가하는 방식을 우선한다.
- 사용자의 승인 없이 이 규칙 자체나 관련 regression test를 약화하거나 제거해서는 안 된다.

## 4. HTML은 독립적으로 읽을 수 있어야 한다

- Milestone 핵심 본문은 HTML 파일 자체에 정적으로 포함한다.
- 외부 CDN, 원격 문서, 압축 fragment가 없어도 핵심 내용을 읽을 수 있어야 한다.
- Milestone 문서에서 `fetch()` + `DecompressionStream`으로 외부/분할 payload를 복원하는 loader 방식을 사용하지 않는다.
- HTML이 기준 Markdown/Contract보다 더 강한 사실을 새로 만들지 않는다.

## 5. 문서 Gate도 테스트 대상이다

최소 다음 검증을 유지한다.

```text
pytest tests/test_documentation_current_state.py
```

이 테스트는 다음 회귀를 막아야 한다.

- DONE/CURRENT Milestone의 HTML 누락
- M0~현재 HTML 삭제
- docs/index.html 링크 누락
- 압축 fragment loader 회귀
- 오래된 Milestone 상태로의 퇴행
- HTML 보존/사용자 승인 규칙 삭제

문서 테스트가 실패하면 구현 작업도 완료된 것으로 보지 않는다.
