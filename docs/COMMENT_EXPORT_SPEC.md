# Jira Comment JSONL Exporter 상세 명세

## 1. 목적

`CommentJsonlExporter`는 댓글 전용 API 응답 파일인 `comments/page_*.json`을 읽어 이슈별 댓글을 병합하고, 검색·Excel·DB 적재의 입력으로 사용할 `comments.jsonl`을 생성합니다.

댓글의 기준 원본은 `issue.json` 내부의 `fields.comment`가 아니라 댓글 전용 API 파일입니다.

## 2. 실행 명령

```powershell
jira-collector export-comments --run-id <RUN_ID>
```

## 3. 실제 파일럿에서 확인한 원본 구조

댓글 본문:

```text
BodyType           : System.String
BodyStartsWithHtml : True
```

작성자 객체 키:

```text
self
name
key
emailAddress
avatarUrls
displayName
active
timeZone
```

페이지 구조:

```text
startAt
maxResults
total
comments
```

## 4. 입력 계약

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/comments/
├─ page_0001.json
├─ page_0002.json
└─ ...
```

파일은 이름 순서로 읽습니다.

댓글이 없는 이슈도 Collector가 다음 형태의 빈 첫 페이지를 저장할 수 있습니다.

```json
{
  "startAt": 0,
  "maxResults": 100,
  "total": 0,
  "comments": []
}
```

이는 정상 완료 결과입니다.

## 5. 출력 계약

```text
data/analysis/<run_id>/
├─ comments.jsonl
├─ parse_warnings.jsonl
└─ summary.json
```

## 6. `comments.jsonl`

한 줄에 댓글 하나의 JSON 객체를 기록합니다.

```json
{
  "run_id": "20260804T043628Z",
  "project_key": "ABC",
  "issue_key": "ABC-123",
  "comment_id": "5001",
  "sequence": 1,
  "author_name": "Example User",
  "author_key": "example.user",
  "created_at": "2026-08-01T10:00:00.000+0900",
  "updated_at": "2026-08-01T11:00:00.000+0900",
  "body_text": "HTML 태그가 제거된 댓글 본문",
  "body_format": "html",
  "source_path": ".../comments/page_0001.json",
  "source_page": "page_0001.json"
}
```

## 7. 저장하지 않는 값

```text
body_raw HTML
전체 author 객체
emailAddress
avatarUrls
self URL
active
timeZone
```

HTML 원문과 전체 작성자 객체는 `source_path`가 가리키는 Raw 댓글 페이지에 그대로 남아 있습니다.

## 8. 페이지 병합과 sequence

```text
page_0001.json의 comments 순서
→ page_0002.json의 comments 순서
→ ...
```

내보내는 순서대로 `sequence=1..N`을 부여합니다.

Jira created 시각으로 재정렬하지 않습니다. 원본 API 페이지와 배열 순서를 그대로 보존하는 것이 첫 버전의 계약입니다.

## 9. 중복 제거

`comment.id`가 이미 발견된 경우:

- 첫 번째 댓글을 유지
- 이후 중복은 저장하지 않음
- `duplicate_comment_id` 경고 기록
- `duplicate_count` 증가

`issue.json` 내부 내장 댓글은 읽지 않으므로, 이슈 상세와 댓글 전용 파일 사이의 중복은 애초에 입력 대상에서 제외됩니다.

## 10. 작성자 정규화

```text
author_name = displayName → name → value → key → id
author_key  = name → key
```

현재 실제 구조에는 `displayName`, `name`, `key`가 있으므로 다음 결과를 기대합니다.

```text
author_name = displayName
author_key  = name
```

값이 없으면 null을 허용합니다.

## 11. Body 정규화

| 원본 | body_format | body_text |
|---|---|---|
| HTML 문자열 | `html` | 태그·style 제거 텍스트 |
| 일반 문자열 | `plain_text` | 공백 정리 문자열 |
| null | `null` | null |
| 객체 | `object` | null + 경고 |
| 배열 | `array` | null + 경고 |

지원하지 않는 타입도 comment_id가 있다면 레코드는 저장하고 body 원문은 Raw JSON에서 추적합니다.

## 12. 페이지와 댓글 오류 격리

### 깨진 페이지

- `comment_page_parse_error`
- 해당 페이지를 건너뜀
- 다른 페이지와 다른 이슈 계속 처리
- `failed_page_count` 증가
- comments 상태 `partial`

### comments가 배열이 아님

- `invalid_comments_array`
- 해당 페이지를 건너뜀
- `failed_page_count` 증가

### 댓글 항목이 객체가 아님

- `invalid_comment_object`
- 해당 항목만 건너뜀
- `failed_comment_count` 증가

### comment.id 누락

- `missing_comment_id`
- 안정적인 식별과 중복 제거가 불가능하므로 저장하지 않음
- `failed_comment_count` 증가

### 댓글 페이지 원본 누락

- `comment_pages_missing`
- `missing_comment_source_count` 증가
- comments 상태 `partial`

## 13. 공통 경고 파일

댓글 경고에는 `component=comments`가 추가됩니다.

```json
{
  "component": "comments",
  "severity": "error",
  "code": "comment_page_parse_error",
  "run_id": "run1",
  "project_key": "ABC",
  "issue_key": "ABC-123",
  "source_path": ".../comments"
}
```

Comment Exporter 재실행 시 댓글 component 경고만 교체하고 Issue 경고는 보존합니다.

## 14. Summary 2.0 comments 영역

```json
{
  "comments": {
    "status": "completed",
    "parser_version": "0.1",
    "issue_count": 30,
    "page_count": 30,
    "discovered_count": 142,
    "exported_count": 142,
    "duplicate_count": 0,
    "failed_page_count": 0,
    "failed_comment_count": 0,
    "missing_comment_source_count": 0,
    "warning_count": 0,
    "body_formats": {
      "html": 142
    }
  }
}
```

기존 Issue 1.0 요약만 있는 경우 자동으로 2.0으로 변환한 뒤 `comments` 영역을 추가합니다.

## 15. 상태 결정

`comments.status=completed` 조건:

```text
failed_page_count == 0
failed_comment_count == 0
missing_comment_source_count == 0
```

중복 댓글과 지원하지 않는 body 타입은 경고이지만, 안정적으로 처리됐으므로 그 자체만으로 partial 상태를 만들지 않습니다.

## 16. 저장 원자성

`comments.jsonl`, `parse_warnings.jsonl`, `summary.json`은 같은 디렉터리의 임시 파일에 기록한 후 `os.replace`로 교체합니다.

중간 종료 시 기존 정상 결과를 유지합니다.

## 17. 재실행 의미

```text
comments.jsonl
→ 현재 Raw 댓글 전체를 기준으로 전체 교체

parse_warnings.jsonl
→ comments component만 교체

summary.json
→ comments 영역만 교체
```

Issue Exporter 실행 전후 어느 시점에 재실행해도 Issue 결과를 삭제하지 않습니다.

## 18. 종료 코드

| 코드 | 의미 |
|---:|---|
| 0 | 모든 댓글 페이지와 댓글을 정상 처리 |
| 1 | 설정, Summary, 경고 파일 또는 저장 오류 |
| 2 | 페이지 실패, 댓글 실패 또는 댓글 원본 누락 존재 |

## 19. 보안

- 이메일 주소를 JSONL에 저장하지 않음
- avatar URL과 self URL을 저장하지 않음
- 댓글 HTML 원문을 JSONL에 중복 저장하지 않음
- 실제 댓글 본문을 로그에 출력하지 않음
- 테스트에는 가짜 댓글 데이터만 사용

## 20. 테스트

```powershell
pytest tests/parser/test_comment_parser.py
pytest tests/exporter/test_comment_jsonl_exporter.py
```

검증 항목:

- HTML 댓글 변환
- 작성자 표시 이름과 key
- 이메일·avatar 제외
- 다중 페이지 순서
- comment.id 중복 제거
- 빈 댓글 페이지
- 깨진 페이지 격리
- comment.id 누락
- 1.0 Summary 마이그레이션
- Issue와 Comment Exporter 실행 순서 독립성
