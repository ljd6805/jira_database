# Run Summary와 Warning 공통 저장 계약

## 1. 목적

Issue Exporter와 Comment Exporter가 같은 run_id의 분석 결과를 독립적으로 생성하면서도 서로의 통계와 경고를 지우지 않도록 공통 저장 규칙을 정의합니다.

공통 파일:

```text
data/analysis/<run_id>/summary.json
data/analysis/<run_id>/parse_warnings.jsonl
```

## 2. 핵심 원칙

- Exporter는 자기 영역만 갱신
- 다른 Exporter 영역은 보존
- 기존 파일이 없으면 새로 생성
- 기존 Issue 전용 Summary 1.0은 2.0으로 자동 변환
- 깨진 기존 파일은 조용히 덮어쓰지 않음
- run_id 불일치를 허용하지 않음
- 모든 교체는 임시 파일과 `os.replace` 사용

## 3. Summary 2.0 구조

```json
{
  "schema_version": "2.0",
  "run_id": "20260804T043628Z",
  "created_at": "2026-08-04T11:00:00Z",
  "updated_at": "2026-08-04T12:00:00Z",
  "status": "completed",
  "issues": {
    "status": "completed"
  },
  "comments": {
    "status": "completed"
  },
  "output_files": {
    "issues": "analysis/20260804T043628Z/issues.jsonl",
    "comments": "analysis/20260804T043628Z/comments.jsonl",
    "warnings": "analysis/20260804T043628Z/parse_warnings.jsonl",
    "summary": "analysis/20260804T043628Z/summary.json"
  }
}
```

## 4. Summary 파일이 없는 경우

`RunSummaryStore`는 다음 기본값을 만듭니다.

```json
{
  "schema_version": "2.0",
  "run_id": "run1",
  "status": "incomplete",
  "issues": {"status": "not_run"},
  "comments": {"status": "not_run"},
  "output_files": {
    "summary": "analysis/run1/summary.json"
  }
}
```

이후 실행한 Exporter의 영역만 실제 통계로 교체합니다.

## 5. Summary 1.0 마이그레이션

기존 Issue Exporter가 생성한 1.0 예:

```json
{
  "schema_version": "1.0",
  "run_id": "run1",
  "status": "completed",
  "discovered_issue_count": 30,
  "exported_issue_count": 30,
  "failed_issue_count": 0,
  "warning_count": 0,
  "parse_error_count": 0,
  "description_formats": {"html": 30}
}
```

2.0 변환 결과:

```json
{
  "schema_version": "2.0",
  "run_id": "run1",
  "status": "incomplete",
  "issues": {
    "status": "completed",
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

Comment Exporter가 이어서 실행되면 comments 영역이 추가되고 전체 status가 다시 계산됩니다.

## 6. 전체 status 계산

우선순위:

```text
failed
→ partial
→ completed
→ incomplete
```

규칙:

| issues | comments | 전체 status |
|---|---|---|
| completed | completed | completed |
| completed | not_run | incomplete |
| not_run | completed | incomplete |
| partial | completed | partial |
| completed | partial | partial |
| failed | 어떤 상태 | failed |

현재 Issue와 Comment Exporter는 처리 가능한 일부 실패를 `partial`로 기록합니다.

## 7. 영역 갱신

Issue Exporter:

```text
summary.issues 갱신
summary.comments 보존
output_files.issues 갱신
```

Comment Exporter:

```text
summary.comments 갱신
summary.issues 보존
output_files.comments 갱신
```

## 8. 손상 보호

다음 상황에서는 기존 summary.json을 덮어쓰지 않습니다.

- JSON 문법 오류
- 최상위 값이 객체가 아님
- 경로 run_id와 내부 run_id 불일치
- 지원하지 않는 schema_version
- issues, comments, output_files가 객체가 아님

오류는 CLI 종료 코드 1로 전달됩니다.

## 9. `parse_warnings.jsonl`

한 줄에 경고 또는 오류 객체 하나를 저장합니다.

```json
{
  "component": "comments",
  "severity": "error",
  "run_id": "run1",
  "project_key": "ABC",
  "issue_key": "ABC-1",
  "code": "comment_page_parse_error",
  "message": "...",
  "json_path": null,
  "source_path": ".../comments"
}
```

## 10. Warning component

지원 component:

```text
issues
comments
```

Exporter 재실행 규칙:

```text
현재 component 기존 경고 제거
→ 현재 실행에서 생성한 경고 추가
→ 다른 component 경고 보존
→ 전체 파일 원자 교체
```

## 11. 기존 경고 파일 마이그레이션

기존 Issue 전용 경고에는 `component` 필드가 없습니다.

```json
{"severity":"error","code":"issue_parse_error"}
```

공통 저장소는 component가 없는 기존 문서를 `issues`로 해석합니다.

다른 component를 갱신할 때 기존 줄의 원문은 그대로 보존합니다. 해당 Issue Exporter를 다시 실행하면 새 형식의 `component=issues` 문서로 교체됩니다.

## 12. 경고 파일 손상 보호

다음 상황에서는 기존 파일을 덮어쓰지 않습니다.

- 한 줄이라도 JSON 문법 오류
- JSON 객체가 아닌 값
- 파일 읽기 실패

잘못된 경고 파일을 자동으로 비우면 과거 오류 정보가 사라질 수 있으므로 명시적으로 중단합니다.

## 13. 원자 저장

Summary와 Warning 파일은 다음 순서로 저장합니다.

```text
대상 디렉터리에 임시 파일 생성
→ UTF-8 기록
→ flush
→ fsync
→ os.replace
```

Windows 파일 잠금 오류는 설정된 횟수만 재시도합니다.

## 14. 실행 순서 독립성

다음 순서를 모두 지원합니다.

```text
export-issues → export-comments
export-comments → export-issues
export-issues → export-comments → export-issues
export-comments → export-issues → export-comments
```

마지막으로 실행한 Exporter는 자기 영역만 최신화합니다.

## 15. 동시 실행 제한

현재는 여러 Exporter 프로세스가 같은 run_id의 Summary와 Warning 파일을 동시에 갱신하는 파일 잠금 기능이 없습니다.

따라서 파일럿에서는 다음 명령을 동시에 실행하지 마십시오.

```text
export-issues
export-comments
```

순차 실행을 전제로 합니다.

## 16. 테스트

```powershell
pytest tests/exporter/test_run_summary_store.py
pytest tests/exporter/test_run_warning_store.py
```

검증 항목:

- 파일 없음에서 생성
- 1.0 → 2.0 변환
- 다른 영역 보존
- 전체 status 계산
- 깨진 Summary 보존
- run_id 불일치 거부
- component별 경고 교체
- 다른 component 경고 보존
- legacy Issue 경고 해석
- 깨진 Warning 파일 보존
