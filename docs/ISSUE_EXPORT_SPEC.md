# Jira Issue JSONL Exporter 상세 명세

## 1. 목적

`IssueJsonlExporter`는 Collector가 저장한 `issue.json`을 읽어, 검색·Excel·DB 적재의 입력으로 사용할 `issues.jsonl`을 생성합니다.

Jira API는 호출하지 않으며 Raw JSON은 수정하지 않습니다.

## 2. 실행 명령

```powershell
jira-collector export-issues --run-id <RUN_ID>
```

## 3. 입력 계약

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

`RunReader`가 project와 issue 디렉터리를 안정적인 이름 순서로 탐색합니다.

## 4. 출력 계약

```text
data/analysis/<run_id>/
├─ issues.jsonl
├─ parse_warnings.jsonl
└─ summary.json
```

Issue와 Comment Exporter가 같은 `parse_warnings.jsonl`, `summary.json`을 공유합니다.

## 5. `issues.jsonl`

한 줄에 이슈 하나의 JSON 객체를 기록합니다.

```json
{
  "run_id": "20260804T043628Z",
  "project_key": "ABC",
  "issue_key": "ABC-123",
  "jira_id": "10001",
  "summary": "Example summary",
  "description_text": "HTML 태그가 제거된 본문",
  "description_format": "html",
  "issue_type": "Bug",
  "status": "Open",
  "priority": "Major",
  "created_at": "2026-08-01T10:00:00.000+0900",
  "updated_at": "2026-08-02T11:00:00.000+0900",
  "source_path": ".../issue.json"
}
```

저장하지 않는 값:

```text
description_raw
description_rendered
전체 fields 객체
내장 fields.comment
첨부파일 바이너리
전체 custom field 값
```

HTML 원문은 `source_path`가 가리키는 `issue.json`에 유지됩니다.

## 6. Description 정규화

| 원본 | description_format | description_text |
|---|---|---|
| HTML 문자열 | `html` | 태그·style 제거 텍스트 |
| 일반 문자열 | `plain_text` | 공백 정리 문자열 |
| null | `null` | null |
| 객체 + rendered HTML | `object_with_rendered_html` | rendered HTML 변환 결과 |
| 지원하지 않는 객체 | 실제 타입 이름 | null 또는 fallback |

## 7. 오류 격리

한 이슈 JSON이 깨지면:

- 해당 이슈를 `issues.jsonl`에 저장하지 않음
- `parse_warnings.jsonl`에 `issue_parse_error` 기록
- 다음 이슈 계속 처리
- Issue summary 상태를 `partial`로 기록
- CLI 종료 코드 2 반환

## 8. 공통 경고 파일

Issue 경고에는 저장 시 다음 값이 추가됩니다.

```json
{
  "component": "issues",
  "severity": "error",
  "code": "issue_parse_error",
  "run_id": "run1",
  "project_key": "ABC",
  "issue_key": "ABC-2",
  "json_path": null,
  "source_path": ".../issue.json"
}
```

Issue Exporter 재실행 시:

- 기존 `component=issues` 경고는 현재 실행 결과로 교체
- `component=comments` 경고는 보존
- 과거 경고에 component가 없으면 Issue 경고로 간주

## 9. 공통 Summary 2.0

Issue Exporter는 `summary.json` 전체를 독점하지 않습니다. `issues` 영역만 갱신합니다.

```json
{
  "schema_version": "2.0",
  "run_id": "run1",
  "status": "incomplete",
  "issues": {
    "status": "completed",
    "parser_version": "0.1",
    "discovered_count": 30,
    "exported_count": 30,
    "failed_count": 0,
    "warning_count": 0,
    "parse_error_count": 0,
    "description_formats": {"html": 30}
  },
  "comments": {"status": "not_run"}
}
```

Comment Exporter가 이미 실행됐다면 `comments` 영역은 그대로 보존됩니다.

기존 1.0 요약은 `RunSummaryStore`가 2.0 구조로 자동 변환합니다.

## 10. 저장 원자성

```text
임시 파일 생성
→ UTF-8 내용 기록
→ flush
→ fsync
→ os.replace
```

Windows의 `WinError 5`, `32`, `33`은 제한된 횟수만 재시도합니다.

## 11. 메모리 정책

`issues.jsonl`은 이슈 한 건씩 기록합니다. 모든 description을 리스트로 모아 한 번에 직렬화하지 않습니다.

경고는 파일 병합을 위해 현재 실행 단위에서 메모리에 보관합니다. 경고량이 매우 커지는 운영 단계에서는 SQLite 임시 저장 또는 별도 스트리밍 전략을 검토합니다.

## 12. 재실행 의미

Issue Exporter는 증분 append가 아니라 현재 Raw snapshot을 기준으로 결과를 재생성합니다.

```text
issues.jsonl
→ 전체 교체

parse_warnings.jsonl
→ issues component만 교체

summary.json
→ issues 영역만 교체
```

따라서 Comment Exporter 전후 어느 시점에 다시 실행해도 댓글 결과를 지우지 않습니다.

## 13. 종료 코드

| 코드 | 의미 |
|---:|---|
| 0 | 모든 이슈 저장 성공 |
| 1 | 설정, 경로, Summary 또는 파일 저장 오류 |
| 2 | 일부 이슈 파싱 실패 |

## 14. 보안

- Raw JSON과 JSONL을 Git에 올리지 않음
- 실제 본문을 기본 로그에 출력하지 않음
- HTML 원문을 JSONL에 중복 저장하지 않음
- `source_path`는 로컬 분석용이며 향후 MCP 외부 응답에서는 제거 예정
- 테스트에는 가짜 이슈 데이터만 사용

## 15. 테스트

```powershell
pytest tests/exporter/test_issue_jsonl_exporter.py
```

검증 항목:

- 정상 이슈 JSONL 저장
- HTML description 변환
- Raw HTML 제외
- 손상 JSON 오류 격리
- 공통 경고 component
- Summary 2.0 issues 영역
- comments not_run일 때 전체 incomplete
- 댓글 Summary 보존
