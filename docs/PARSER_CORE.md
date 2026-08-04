# Jira Issue Parser Core

## 목적

이 단계는 수집된 Jira 원본 JSON을 DB에 바로 적재하지 않고, 먼저 이슈 핵심 필드를 안전하게 읽는 parser 기반을 제공합니다.

Parser는 Jira API를 호출하지 않으며 다음 경로만 읽습니다.

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

원본 JSON은 수정하지 않습니다.

## 포함된 기능

- `RunReader`: 하나의 `run_id` 아래에 저장된 `issue.json` 탐색
- `IssueParser`: 이슈 핵심 필드를 `IssueRecord`로 변환
- HTML description 원문 보존 및 텍스트 변환
- 경로와 JSON 내부의 프로젝트/이슈 키 불일치 경고
- 예상하지 못한 description 타입 경고
- 모든 결과에 원본 `source_path` 보존

## 첫 IssueRecord 필드

```text
run_id
project_key
issue_key
jira_id
summary
description_raw
description_rendered
description_text
description_format
issue_type
status
priority
created_at
updated_at
source_path
```

`description_raw`에는 `fields.description` 원본을 저장합니다. 값이 HTML 문자열이면 `description_text`에는 태그와 스타일을 제거한 텍스트를 저장합니다.

## 로컬 확인 예시

프로젝트 루트에서 가상환경을 활성화하고 다음처럼 실행할 수 있습니다.

```powershell
python -c "from jira_collector.parser import RunReader, IssueParser; r=RunReader('./data'); s=r.list_issue_sources('<RUN_ID>'); print('issues=', len(s)); x=IssueParser().parse_file(s[0]); print(x.record); print(x.warnings)"
```

`<RUN_ID>`는 실제 수집 실행 ID로 변경해야 합니다.

처음에는 제목이나 description 전체를 공유하지 말고 다음 항목만 확인하는 것이 안전합니다.

- 탐색한 이슈 수
- `description_format`
- warning 코드
- 오류 메시지의 JSON 경로

## 테스트

```powershell
pytest tests/parser
```

테스트는 실제 Jira 데이터가 아닌 가짜 fixture를 사용합니다.

## 아직 포함하지 않은 기능

- 댓글 parser
- 첨부파일 메타데이터 parser
- 이슈 링크 parser
- custom field parser
- Excel exporter
- DB 적재
- LLM 요약 또는 임베딩

다음 단계는 실제 run에서 Issue Parser의 구조를 검증한 뒤 Comment Parser를 추가하는 것입니다.
