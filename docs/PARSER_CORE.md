# Jira Parser Core

## 1. 목적

Parser Core는 Collector가 저장한 Jira Raw JSON을 수정하지 않고 읽어, 이후 JSONL·Excel·DB로 전달할 표준 중간 레코드를 생성합니다.

Parser는 Jira API를 호출하지 않습니다.

```text
data/raw/runs/<run_id>/...
        ↓
RunReader
        ↓
IssueParser / CommentParser
        ↓
IssueRecord / CommentRecord
```

## 2. 설계 원칙

- Raw JSON은 읽기 전용으로 취급
- 아는 필드는 표준 구조로 변환
- HTML 원문과 정제 텍스트를 구분
- 모르는 구조는 가능한 원문을 보존하고 경고 기록
- 한 이슈 또는 페이지 오류가 전체 run을 중단시키지 않음
- 모든 레코드에 run_id, project_key, issue_key, source_path 보존
- 실제 Jira 데이터를 테스트 fixture로 사용하지 않음

## 3. RunReader

입력:

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/
```

출력 `IssueSource`:

```text
run_id
project_key
issue_key
issue_path
comments_dir
```

정렬 순서:

```text
project 디렉터리 이름
→ issue 디렉터리 이름
→ comment page 파일 이름
```

## 4. IssueParser

읽는 파일:

```text
issues/<issue_key>/issue.json
```

생성 레코드:

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

### Description 처리

- HTML 문자열이면 `description_format=html`
- HTML 태그, style, color 속성은 `description_text`에서 제거
- HTML 원문은 `description_raw`에 유지
- 일반 문자열이면 `plain_text`
- null이면 `null`
- 예상하지 못한 객체·배열이면 타입을 기록하고 경고 생성
- `renderedFields.description`이 있으면 fallback으로 사용 가능

### 주요 경고

```text
issue_key_mismatch
project_key_mismatch
unexpected_type
unsupported_description_type
```

## 5. CommentParser

읽는 파일:

```text
issues/<issue_key>/comments/page_0001.json
issues/<issue_key>/comments/page_0002.json
...
```

댓글 전용 API 파일만 댓글의 기준 원본으로 사용합니다. `issue.json` 안의 `fields.comment`는 사용하지 않습니다.

생성 레코드:

```text
run_id
project_key
issue_key
comment_id
sequence
author_name
author_key
created_at
updated_at
body_raw
body_text
body_format
source_path
source_page
```

### 페이지 처리

1. `page_*.json`을 파일명 순서로 정렬
2. 각 페이지의 `comments` 배열을 원래 순서로 읽음
3. `comment.id` 기준 중복 제거
4. 첫 번째로 발견한 댓글을 유지
5. 저장되는 레코드 순서로 `sequence=1..N` 부여
6. 깨진 페이지는 오류 경고 후 다음 페이지 처리
7. 댓글이 0개인 빈 페이지는 정상 처리

### Body 처리

실제 파일럿에서 확인된 형식:

```text
BodyType           : System.String
BodyStartsWithHtml : True
```

처리 규칙:

- HTML 문자열 → `body_format=html`, `body_text` 생성
- 일반 문자열 → `plain_text`
- null → `null`
- 객체·배열 → 타입 기록, body_text는 null, 경고 생성

### 작성자 처리

실제 작성자 객체에서 확인된 키:

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

표준화 규칙:

```text
author_name = displayName → name → key
author_key  = name → key
```

Parser 레코드에는 원본 author 객체를 보존하지 않습니다. Exporter는 이메일, avatar URL, self URL을 출력하지 않습니다.

### 주요 경고과 오류

```text
comment_pages_missing
comment_page_parse_error
invalid_comments_array
invalid_comment_object
missing_comment_id
duplicate_comment_id
unsupported_comment_body_type
```

`severity=error`인 경우:

- 댓글 페이지 JSON 파싱 실패
- comments 배열 형식 오류
- 댓글 항목이 객체가 아님
- comment.id 누락

## 6. ParseWarning

```text
code
message
json_path
severity
```

기본 severity는 `warning`입니다.

Parser는 경고를 직접 파일에 저장하지 않습니다. Exporter가 `parse_warnings.jsonl` 형식으로 변환합니다.

## 7. HTML 텍스트 변환

표준 라이브러리 `html.parser.HTMLParser`를 사용합니다.

처리 내용:

- script와 style 내용 무시
- p, div, heading, table, tr 뒤 줄바꿈
- br 줄바꿈
- li 앞에 `- ` 추가
- td/th 사이 구분자 추가
- HTML entity 디코딩
- 중복 공백과 빈 줄 정리

예:

```html
<p dir="auto">부팅 <span style="color:red">오류</span></p>
<ul><li>첫 항목</li></ul>
```

결과:

```text
부팅 오류
- 첫 항목
```

## 8. 로컬 구조 확인

```powershell
$runId = "<RUN_ID>"
python -c "from collections import Counter; from jira_collector.parser import RunReader, IssueParser; s=RunReader('./data').list_issue_sources('$runId'); r=[IssueParser().parse_file(x) for x in s]; print(len(r)); print(Counter(x.record.description_format for x in r))"
```

댓글 Parser의 실제 저장 결과는 직접 Python 표현식을 작성하기보다 CLI를 사용하는 것을 권장합니다.

```powershell
jira-collector export-comments --run-id $runId
```

## 9. 테스트

```powershell
pytest tests/parser
```

검증 항목:

- HTML description 변환
- 객체 description fallback
- 경로와 payload 키 불일치
- HTML 댓글 변환
- 작성자 표시 이름과 key 추출
- 다중 페이지 순서
- 중복 comment.id 제거
- 빈 댓글 페이지
- 깨진 페이지 격리
- 댓글 ID 누락
- 댓글 원본 디렉터리 누락

## 10. 현재 제한

- Jira Wiki markup 전용 변환기 없음
- Atlassian Document Format 객체의 직접 텍스트 변환 없음
- 댓글 수정 이력 없음
- 삭제 댓글 복원 없음
- 첨부·링크·Custom field Parser 미구현

지원하지 않는 구조는 임의 추측하지 않고 경고와 원본 경로로 남깁니다.
