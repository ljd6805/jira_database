# Jira Issue JSONL Exporter 상세 명세

## 1. 문서 목적

이 문서는 Jira Raw Data Collector가 저장한 `issue.json`을 읽어 분석용 JSONL 파일로 변환하는 **Issue Parser + JSONL Exporter의 저장 계약**을 정의합니다.

이 기능의 목적은 다음과 같습니다.

1. Jira 원본 JSON을 수정하지 않고 분석 가능한 중간 데이터를 생성합니다.
2. HTML description에서 태그와 스타일을 제거한 텍스트를 만듭니다.
3. 파싱 결과를 한 이슈당 한 줄인 JSONL 형식으로 저장합니다.
4. 일부 이슈의 파싱 실패가 전체 run의 내보내기를 중단시키지 않게 합니다.
5. 모든 결과에서 원본 `issue.json`으로 되돌아갈 수 있도록 `source_path`를 보존합니다.
6. DB 스키마를 확정하기 전 데이터 구조와 품질을 검토할 기반을 만듭니다.

이 단계에서는 댓글, 첨부파일 바이너리, custom field 정규화, Excel, DB 적재, 임베딩을 처리하지 않습니다.

---

## 2. 실행 명령

```powershell
jira-collector export-issues --run-id <RUN_ID>
```

예:

```powershell
jira-collector export-issues --run-id 20260804T074500Z
```

이 명령은 Jira API를 호출하지 않습니다. 설정의 `storage.data_root` 아래에 이미 저장된 파일만 읽습니다.

현재 CLI 구조상 공통 설정을 읽기 때문에 `.env`와 `config/settings.yaml`이 존재해야 하지만, `export-issues` 실행 중 Jira 서버로 네트워크 요청을 보내지는 않습니다.

---

## 3. 입력 계약

### 3.1 입력 루트

```text
<data_root>/raw/runs/<run_id>/
```

기본 `data_root`는 `config/settings.yaml`의 다음 값입니다.

```yaml
storage:
  data_root: ./data
  raw_directory: raw
```

### 3.2 이슈 원본 경로

```text
data/raw/runs/<run_id>/projects/<project_key>/issues/<issue_key>/issue.json
```

예:

```text
data/raw/runs/20260804T074500Z/projects/ABC/issues/ABC-1137/issue.json
```

### 3.3 탐색 순서

`RunReader`는 다음 순서로 파일을 탐색합니다.

1. 프로젝트 디렉터리 이름 오름차순
2. 프로젝트 안의 이슈 디렉터리 이름 오름차순
3. `issue.json`이 실제 파일인 항목만 선택

따라서 같은 입력 run을 반복 실행하면 `issues.jsonl`의 레코드 순서도 동일합니다.

### 3.4 읽기 전용 원칙

Exporter는 다음을 수행하지 않습니다.

- `data/raw` 아래 파일 수정
- 원본 JSON 삭제
- 원본 JSON 파일명 변경
- Jira API 호출
- SQLite checkpoint 변경

---

## 4. 처리 흐름

```text
RunReader
  ↓ issue.json 경로 탐색
IssueParser
  ↓ IssueRecord + ParseWarning 생성
IssueJsonlExporter
  ├─ issues.jsonl
  ├─ parse_warnings.jsonl
  └─ summary.json
```

각 이슈는 독립적으로 처리합니다.

```text
이슈 A 파싱 성공 → issues.jsonl 기록
이슈 B JSON 손상 → parse_warnings.jsonl 오류 기록
이슈 C 파싱 성공 → issues.jsonl 기록
```

이슈 B가 실패해도 이슈 C 처리를 계속합니다.

---

## 5. Description 처리 계약

### 5.1 확인된 실제 형식

현재 사내 Jira의 `fields.description`은 다음처럼 HTML 문자열로 확인됐습니다.

```html
<p dir="auto">본문</p>
```

### 5.2 내부 파싱 레코드

`IssueRecord` 내부에서는 다음 세 값을 유지합니다.

| 필드 | 내용 |
|---|---|
| `description_raw` | `fields.description` 원본 |
| `description_rendered` | `renderedFields.description` 문자열 |
| `description_text` | HTML 태그와 스타일을 제거한 분석용 텍스트 |

### 5.3 JSONL 저장 정책

`issues.jsonl`에는 다음만 저장합니다.

- `description_text`
- `description_format`
- `source_path`

다음 값은 저장하지 않습니다.

- `description_raw`
- `description_rendered`

이유는 원본 HTML이 이미 `issue.json`에 존재하기 때문입니다. 동일 HTML을 분석 파일에 다시 저장하면 저장 공간이 증가하고 검색 시 `style`, `color`, `span`, `font` 같은 노이즈가 섞입니다.

### 5.4 HTML 텍스트 변환

변환 시 다음 원칙을 적용합니다.

- `<script>`와 `<style>` 내용 무시
- `<p>`, `<div>`, 제목, 표 행 등 블록 요소 뒤에 줄바꿈 추가
- `<br>`을 줄바꿈으로 변환
- `<li>`를 `- ` 목록 형태로 변환
- `<td>`, `<th>` 사이를 구분
- HTML entity 디코딩
- 연속 공백 정리
- 빈 줄 제거

예:

```html
<p dir="auto">첫 문단 <span style="color:red">강조</span></p>
<ul><li>항목 하나</li></ul>
```

결과:

```text
첫 문단 강조
- 항목 하나
```

### 5.5 Description format 값

| 값 | 의미 |
|---|---|
| `html` | `fields.description`이 HTML 문자열 |
| `plain_text` | 일반 문자열 |
| `rendered_html` | Raw 값은 없고 rendered HTML만 존재 |
| `null` | description이 없음 |
| `<type>` | 지원하지 않는 Raw 타입이고 대체 텍스트도 없음 |
| `<type>_with_rendered_html` | 지원하지 않는 Raw 타입이나 rendered HTML로 텍스트 생성 |
| `<type>_with_rendered_text` | 지원하지 않는 Raw 타입이나 rendered 일반 문자열 사용 |

---

## 6. 출력 구조

```text
data/
└─ analysis/
   └─ <run_id>/
      ├─ issues.jsonl
      ├─ parse_warnings.jsonl
      └─ summary.json
```

`data/` 전체는 `.gitignore`에 포함되므로 분석 결과도 Git에 올라가지 않습니다.

---

## 7. issues.jsonl 계약

### 7.1 형식

- UTF-8
- BOM 없음
- 한 줄에 JSON 객체 하나
- 각 줄 끝에 LF 줄바꿈
- JSON key 순서는 코드의 저장 순서를 따르지만 소비자는 순서에 의존하면 안 됨

### 7.2 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `run_id` | string | 원본 수집 실행 ID |
| `project_key` | string | Jira 프로젝트 키 |
| `issue_key` | string | Jira 이슈 키 |
| `jira_id` | string/null | Jira 내부 이슈 ID |
| `summary` | string/null | 이슈 제목 |
| `description_text` | string/null | HTML을 제거한 설명 본문 |
| `description_format` | string | description 원본 형식 분류 |
| `issue_type` | string/null | Bug, Task 등의 이슈 유형 |
| `status` | string/null | 이슈 상태 |
| `priority` | string/null | 우선순위 |
| `created_at` | string/null | Jira 생성 시각 원문 |
| `updated_at` | string/null | Jira 수정 시각 원문 |
| `source_path` | string | 원본 `issue.json` 경로 |

### 7.3 예시

```json
{"run_id":"20260804T074500Z","project_key":"ABC","issue_key":"ABC-1137","jira_id":"123456","summary":"Example summary","description_text":"정제된 본문","description_format":"html","issue_type":"Bug","status":"Open","priority":"Major","created_at":"2026-08-01T10:00:00.000+0900","updated_at":"2026-08-02T11:00:00.000+0900","source_path":"data/raw/runs/20260804T074500Z/projects/ABC/issues/ABC-1137/issue.json"}
```

### 7.4 저장하지 않는 데이터

- description HTML 원문
- rendered HTML 원문
- 댓글
- 첨부파일 바이너리
- 사용자 이메일
- Authorization, Cookie, Password
- 전체 `fields` 객체
- custom field 전체 값

---

## 8. parse_warnings.jsonl 계약

### 8.1 목적

파싱을 중단시킬 필요는 없지만 검토가 필요한 구조와, 해당 이슈만 처리하지 못한 오류를 기록합니다.

경고가 하나도 없어도 0바이트 파일을 생성합니다. 이는 경고 수집 단계가 정상 완료됐음을 명시합니다.

### 8.2 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `severity` | string | `warning` 또는 `error` |
| `run_id` | string | 수집 실행 ID |
| `project_key` | string | 경로에서 확인한 프로젝트 키 |
| `issue_key` | string | 경로에서 확인한 이슈 키 |
| `code` | string | 안정적인 경고·오류 코드 |
| `message` | string | 사람이 읽는 설명 |
| `json_path` | string/null | 문제가 발견된 JSON 경로 |
| `source_path` | string | 원본 파일 경로 |

### 8.3 현재 코드

| code | severity | 의미 |
|---|---|---|
| `issue_key_mismatch` | warning | 폴더명과 JSON 내부 이슈 키 불일치 |
| `project_key_mismatch` | warning | 폴더명과 JSON 내부 프로젝트 키 불일치 |
| `unexpected_type` | warning | 문자열 예상 위치에서 다른 타입 발견 |
| `unsupported_description_type` | warning | description이 현재 지원하지 않는 타입 |
| `missing_value` | warning | 필수로 검사하도록 지정된 값 누락 |
| `issue_parse_error` | error | JSON 손상 또는 fields 구조 문제로 해당 이슈 파싱 실패 |

### 8.4 예시

```json
{"severity":"error","run_id":"20260804T074500Z","project_key":"ABC","issue_key":"ABC-1200","code":"issue_parse_error","message":"이슈 JSON을 읽을 수 없습니다: ...","json_path":null,"source_path":"data/raw/runs/.../issue.json"}
```

---

## 9. summary.json 계약

### 9.1 기록 시점

`summary.json`은 다음 작업이 모두 끝난 뒤 마지막에 기록합니다.

1. `issues.jsonl` 저장 및 교체
2. `parse_warnings.jsonl` 저장 및 교체
3. 통계 집계
4. `summary.json` 저장 및 교체

따라서 최신 `summary.json`이 존재하면 해당 export 실행이 마지막 단계까지 도달한 것으로 판단할 수 있습니다.

단, 세 파일 전체를 하나의 트랜잭션으로 교체하는 구조는 아닙니다. 각 파일은 개별적으로 원자 저장됩니다.

### 9.2 필드

| 필드 | 설명 |
|---|---|
| `schema_version` | JSONL 출력 계약 버전 |
| `parser_version` | Parser 구현 버전 |
| `run_id` | 수집 실행 ID |
| `generated_at` | UTC ISO 8601 생성 시각 |
| `status` | `completed` 또는 `partial` |
| `discovered_issue_count` | 발견한 issue.json 수 |
| `exported_issue_count` | issues.jsonl에 기록한 수 |
| `failed_issue_count` | 파싱 실패 이슈 수 |
| `warning_count` | warning과 error를 합한 전체 기록 수 |
| `parse_error_count` | `issue_parse_error` 수 |
| `description_formats` | format별 성공 이슈 수 |
| `output_files` | data_root 기준 출력 경로 |

### 9.3 상태 정의

| status | 조건 |
|---|---|
| `completed` | 파싱 실패 이슈가 0개 |
| `partial` | 파싱 실패 이슈가 1개 이상 |

경고만 있고 실패가 없으면 `completed`입니다.

---

## 10. 원자 저장과 Windows 파일 잠금

각 출력 파일은 다음 순서로 저장합니다.

```text
대상 디렉터리에 임시 파일 생성
→ UTF-8 내용 기록
→ flush
→ fsync
→ os.replace로 대상 파일 교체
```

Windows에서 백신, 인덱서, 편집기가 파일을 잠그면 `WinError 5`, `32`, `33`을 최대 6회 재시도합니다.

기본 대기 간격:

```text
0.2초 → 0.4초 → 0.8초 → 1.6초 → 2.0초
```

재실행하면 기존 출력 파일을 같은 경로에 원자적으로 교체합니다.

---

## 11. 오류 처리

### 11.1 이슈 단위 오류

다음 오류는 해당 이슈만 실패시키고 다음 이슈를 계속 처리합니다.

- JSON 문법 오류
- UTF-8 디코딩 오류
- 파일 읽기 오류가 `IssueParseError`로 변환된 경우
- 최상위 값이 객체가 아님
- `fields`가 객체가 아님

실패 내용은 `parse_warnings.jsonl`에 `issue_parse_error`로 기록합니다.

### 11.2 실행 전체 오류

다음은 전체 명령을 실패시킵니다.

- run_id 디렉터리 없음
- 출력 디렉터리 생성 실패
- 디스크 쓰기 실패
- 원자 교체 재시도 최종 실패
- 경로 이동 시도
- 설정 파일 오류

---

## 12. CLI 종료 코드

| 코드 | 의미 |
|---:|---|
| `0` | 모든 발견 이슈 저장 성공 |
| `1` | 설정, run_id, 파일 시스템 등 명령 전체 오류 |
| `2` | 출력은 생성했지만 일부 이슈 파싱 실패 |

종료 코드 `2`인 경우 `summary.json`의 `status`는 `partial`이며, 실패 상세는 `parse_warnings.jsonl`에서 확인합니다.

---

## 13. 보안 원칙

- 실제 Jira JSON은 외부로 반출하지 않습니다.
- `data/raw`와 `data/analysis`는 Git에 commit하지 않습니다.
- 테스트는 가짜 fixture만 사용합니다.
- 로그에는 summary와 description 본문을 출력하지 않습니다.
- 분석 결과에는 Jira 인증정보가 포함되지 않습니다.
- `source_path`는 로컬 경로를 포함할 수 있으므로 외부 공유 시 마스킹합니다.
- `issues.jsonl`에는 실제 업무 제목과 본문이 포함되므로 사내 데이터로 취급합니다.

---

## 14. 재실행 의미

같은 run_id로 다시 실행하면 다음 파일을 새 결과로 교체합니다.

```text
issues.jsonl
parse_warnings.jsonl
summary.json
```

원본 run은 변하지 않으므로 Parser 코드를 개선한 뒤 같은 run_id를 반복 분석할 수 있습니다.

```text
Raw JSON snapshot 1개
→ Parser v0.1 결과
→ Parser 수정
→ 같은 Raw JSON으로 Parser v0.2 결과 재생성
```

---

## 15. 테스트 계약

실제 Jira에 접속하지 않고 임시 디렉터리와 가짜 JSON을 사용합니다.

현재 테스트 범위:

- 기존 파일의 원자 교체
- 분석 루트 밖 경로 차단
- HTML description 텍스트 변환
- HTML 원문이 issues.jsonl에 중복 저장되지 않음
- 손상된 이슈가 다른 이슈 처리를 막지 않음
- 파싱 실패가 error 레코드로 저장됨
- 경고가 없을 때 빈 warning 파일 생성
- summary의 completed/partial 상태
- output_files 상대 경로
- CLI `export-issues --run-id` 등록

실행:

```powershell
pytest tests/parser tests/exporter tests/test_cli_export.py
```

전체 회귀 테스트:

```powershell
pytest
```

---

## 16. 현재 제한

- 댓글은 아직 내보내지 않음
- 첨부파일은 메타데이터도 아직 내보내지 않음
- 이슈 링크 미지원
- custom field 미지원
- 날짜 문자열을 datetime으로 정규화하지 않음
- HTML 표의 셀 경계를 완벽히 복원하지 않음
- 전체 출력 묶음을 단일 트랜잭션으로 교체하지 않음
- Excel 미지원
- DB 적재 미지원

---

## 17. 다음 구현 순서

1. `CommentParser`
2. `comments.jsonl` Exporter
3. 첨부파일 메타데이터 Parser
4. 이슈 링크 Parser
5. Custom field 범용 Parser
6. 필드 존재율·타입 분포 Profiler
7. Excel Exporter
8. Excel 검토 후 DB 스키마 확정

DB 스키마를 먼저 고정하지 않습니다. JSONL과 프로파일링 결과를 확인한 뒤 관계와 컬럼을 결정합니다.
