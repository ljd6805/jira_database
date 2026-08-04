# Jira Issue Parser Core

## 1. 목적

이 단계는 수집된 Jira 원본 JSON을 DB에 바로 적재하지 않고, 이슈 핵심 필드를 안전하게 읽어 분석용 JSONL로 저장하는 기반을 제공합니다.

Parser와 Exporter는 Jira API를 호출하지 않으며 다음 경로만 읽습니다.

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

원본 JSON은 수정하지 않습니다.

상세 저장 계약은 [`ISSUE_EXPORT_SPEC.md`](ISSUE_EXPORT_SPEC.md)를 기준으로 합니다.

## 2. 포함된 기능

- `RunReader`: 하나의 `run_id` 아래에 저장된 `issue.json` 탐색
- `IssueParser`: 이슈 핵심 필드를 `IssueRecord`로 변환
- HTML description 원문 보존 및 텍스트 변환
- 경로와 JSON 내부의 프로젝트/이슈 키 불일치 경고
- 예상하지 못한 description 타입 경고
- `IssueJsonlExporter`: 파싱 결과를 `issues.jsonl`로 저장
- 파싱 경고와 오류를 `parse_warnings.jsonl`로 저장
- 실행 통계를 `summary.json`으로 저장
- 파일별 임시 파일 + `os.replace` 원자 저장
- Windows 파일 잠금 오류 재시도
- 모든 결과에 원본 `source_path` 보존

## 3. 내부 IssueRecord 필드

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

내부 레코드에는 HTML 원문이 있지만, `issues.jsonl`에는 정제된 `description_text`와 `description_format`만 저장합니다. 원문은 `source_path`가 가리키는 `issue.json`에서 확인합니다.

## 4. 실행

```powershell
jira-collector export-issues --run-id <RUN_ID>
```

예:

```powershell
jira-collector export-issues --run-id 20260804T074500Z
```

출력:

```text
data/analysis/<run_id>/
├─ issues.jsonl
├─ parse_warnings.jsonl
└─ summary.json
```

## 5. 로컬 파싱 확인

파일 저장 없이 parser 결과만 확인하려면 다음처럼 실행할 수 있습니다.

```powershell
python -c "from jira_collector.parser import RunReader, IssueParser; r=RunReader('./data'); s=r.list_issue_sources('<RUN_ID>'); print('issues=', len(s)); x=IssueParser().parse_file(s[0]); print('format=', x.record.description_format); print('warnings=', [w.code for w in x.warnings])"
```

`<RUN_ID>`는 실제 수집 실행 ID로 변경해야 합니다.

처음에는 제목이나 description 전체를 공유하지 말고 다음 항목만 확인하는 것이 안전합니다.

- 탐색한 이슈 수
- `description_format`
- warning 코드
- 오류 메시지의 JSON 경로

## 6. JSONL 확인

첫 두 레코드만 PowerShell에서 확인:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\issues.jsonl" -TotalCount 2
```

요약 확인:

```powershell
Get-Content ".\data\analysis\<RUN_ID>\summary.json" -Raw |
    ConvertFrom-Json |
    Format-List
```

경고 개수 확인:

```powershell
@(Get-Content ".\data\analysis\<RUN_ID>\parse_warnings.jsonl").Count
```

경고 파일이 0바이트라면 파싱 경고와 오류가 없었다는 의미입니다.

## 7. 테스트

Parser와 Exporter 테스트:

```powershell
pytest tests/parser tests/exporter tests/test_cli_export.py
```

전체 회귀 테스트:

```powershell
pytest
```

테스트는 실제 Jira 데이터가 아닌 가짜 fixture와 임시 디렉터리를 사용합니다.

## 8. 종료 코드

| 코드 | 의미 |
|---:|---|
| `0` | 모든 이슈 파싱 및 저장 성공 |
| `1` | run_id, 설정, 파일 시스템 등 전체 실행 오류 |
| `2` | 일부 이슈가 실패했지만 나머지 결과 저장 완료 |

## 9. 아직 포함하지 않은 기능

- 댓글 parser와 `comments.jsonl`
- 첨부파일 메타데이터 parser
- 이슈 링크 parser
- custom field parser
- 필드 profiler
- Excel exporter
- DB 적재
- LLM 요약 또는 임베딩

다음 단계는 댓글 전용 원본인 `comments/page_*.json`을 `comment.id` 기준으로 병합하는 `CommentParser`입니다.
