# Run Summary와 Warning 공통 저장 계약

## 1. 목적

각 Exporter가 같은 run_id의 ANALYSIS 결과를 독립적으로 생성하면서도 서로의 통계와 경고를 지우지 않도록 공통 저장 규칙을 정의합니다.

공통 파일:

```text
[ANALYSIS]
data/analysis/<run_id>/summary.json
data/analysis/<run_id>/parse_warnings.jsonl
```

현재 지원 Exporter 영역:

```text
issues
comments
attachments
relationships
custom_fields
```

구조 파일 자체를 읽지 못한 공통 오류는 Warning component `structure`로 기록합니다.

## 2. 핵심 원칙

- Exporter는 자기 영역만 갱신
- 다른 Exporter 영역은 보존
- 여러 영역을 한 단계에서 갱신할 때는 한 번의 원자 저장 사용
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
  "status": "completed",
  "issues": {"status": "completed"},
  "comments": {"status": "completed"},
  "attachments": {"status": "completed"},
  "relationships": {"status": "completed"},
  "custom_fields": {"status": "completed"},
  "output_files": {
    "issues": "analysis/.../issues.jsonl",
    "comments": "analysis/.../comments.jsonl",
    "attachments": "analysis/.../attachments.jsonl",
    "relationships": "analysis/.../issue_relationships.jsonl",
    "custom_field_catalog": "analysis/.../custom_field_catalog.jsonl",
    "custom_field_values": "analysis/.../custom_field_values.jsonl",
    "warnings": "analysis/.../parse_warnings.jsonl",
    "summary": "analysis/.../summary.json"
  }
}
```

## 4. Summary 파일이 없는 경우

새 문서는 모든 영역을 `not_run`으로 시작합니다.

```json
{
  "schema_version": "2.0",
  "run_id": "run1",
  "status": "incomplete",
  "issues": {"status": "not_run"},
  "comments": {"status": "not_run"},
  "attachments": {"status": "not_run"},
  "relationships": {"status": "not_run"},
  "custom_fields": {"status": "not_run"}
}
```

## 5. 기존 2.0 파일 확장

기존 2.0 Summary가 `issues`, `comments`만 가지고 있어도 읽을 수 있습니다.

누락된 새 영역은 메모리에서 다음처럼 보완합니다.

```text
attachments.status   = not_run
relationships.status = not_run
custom_fields.status = not_run
```

기존 파일을 강제 마이그레이션 명령으로 별도 변환하지 않습니다. 다음 Exporter 갱신 시 자연스럽게 새 영역이 기록됩니다.

## 6. 1.0 → 2.0 마이그레이션

기존 Issue 전용 필드는 `issues` 영역으로 이동하고 나머지는 `not_run`으로 생성합니다.

```text
discovered_issue_count → issues.discovered_count
exported_issue_count   → issues.exported_count
failed_issue_count     → issues.failed_count
description_formats    → issues.description_formats
```

## 7. 전체 status 계산

우선순위:

```text
failed
→ partial
→ completed
→ incomplete
```

기본 완료 기준은 기존 호환성을 위해 `issues`와 `comments`입니다.

```text
issues=completed + comments=completed
→ 기본 전체 상태 completed
```

Attachment/Relationship/Custom Field가 아직 `not_run`이어도 기존 2.0 Summary 의미를 깨지 않습니다.

단, 새 선택 영역을 실행했고 해당 영역이 `partial` 또는 `failed`이면 전체 status에도 반영합니다.

예:

| issues | comments | attachments | 전체 |
|---|---|---|---|
| completed | completed | not_run | completed |
| completed | completed | completed | completed |
| completed | completed | partial | partial |
| completed | not_run | completed | incomplete |
| completed | completed | failed | failed |

## 8. 단일 영역 갱신

기존 Exporter는 `update_section()`을 사용합니다.

```text
export-issues   → issues만 갱신
export-comments → comments만 갱신
```

`update_section()` 내부에서는 다중 영역 API인 `update_sections()`로 위임합니다.

## 9. 다중 영역 원자 갱신

4단계 `export-structure`는 한 실행에서 세 Summary 영역을 함께 갱신합니다.

```text
attachments
relationships
custom_fields
```

따라서 다음 순서로 처리합니다.

```text
기존 summary 읽기
→ 세 영역 메모리 갱신
→ output_files 갱신
→ 전체 status 계산
→ summary.json 한 번 원자 교체
```

중간에 `attachments`만 갱신되고 `relationships`가 이전 값으로 남는 상태를 최소화합니다.

## 10. 4단계 Summary 항목

### attachments

```text
status
parser_version
issue_count
discovered_count
exported_count
failed_count
failed_issue_count
warning_count
```

### relationships

```text
status
parser_version
issue_count
discovered_count
exported_count
duplicate_count
issue_link_count
hierarchy_count
failed_count
failed_issue_count
warning_count
```

### custom_fields

```text
status
parser_version
issue_count
catalog_count
used_field_count
discovered_value_count
exported_value_count
failed_value_count
definition_mismatch_count
failed_issue_count
warning_count
value_kinds
```

## 11. 손상 보호

다음 상황에서는 기존 summary.json을 덮어쓰지 않습니다.

- JSON 문법 오류
- 최상위 값이 객체가 아님
- 경로 run_id와 내부 run_id 불일치
- 지원하지 않는 schema_version
- 각 영역 또는 output_files가 객체가 아님

오류는 CLI 종료 코드 1로 전달됩니다.

## 12. `parse_warnings.jsonl`

한 줄에 경고 또는 오류 객체 하나를 저장합니다.

```json
{
  "component": "relationships",
  "severity": "error",
  "run_id": "run1",
  "project_key": "ABC",
  "issue_key": "ABC-1",
  "code": "missing_linked_issue_key",
  "message": "...",
  "json_path": "/fields/issuelinks/0/outwardIssue/key",
  "source_path": ".../issue.json"
}
```

## 13. Warning component

지원 component:

```text
issues
comments
attachments
relationships
custom_fields
structure
```

기존 component가 없는 Warning은 `issues`로 해석합니다.

## 14. 단일·다중 Warning 교체

단일 Exporter:

```text
replace_component()
```

4단계 Exporter:

```text
replace_components()
```

4단계에서는 다음 네 component를 한 번에 교체합니다.

```text
attachments
relationships
custom_fields
structure
```

기존 `issues`와 `comments` 경고는 보존합니다.

## 15. Warning 파일 손상 보호

다음 상황에서는 기존 파일을 덮어쓰지 않습니다.

- 한 줄이라도 JSON 문법 오류
- JSON 객체가 아닌 값
- 파일 읽기 실패

## 16. 원자 저장

Summary와 Warning 파일은 다음 순서로 저장합니다.

```text
대상 디렉터리에 임시 파일 생성
→ UTF-8 기록
→ flush
→ fsync
→ os.replace
```

Windows 파일 잠금 오류는 설정된 횟수만 재시도합니다.

## 17. 실행 순서 독립성

다음 실행을 순차적으로 지원합니다.

```text
export-issues
export-comments
export-structure
```

각 명령은 자신의 영역만 최신화합니다.

예:

```text
export-structure → export-issues
```

을 실행해도 Structure Summary와 Warning은 유지됩니다.

## 18. 동시 실행 제한

현재 서로 다른 프로세스가 같은 run_id의 Summary/Warning을 동시에 수정하는 프로세스 간 파일 잠금은 없습니다.

따라서 파일럿에서는 다음 명령을 동시에 실행하지 않습니다.

```text
export-issues
export-comments
export-structure
```

## 19. 테스트

```powershell
pytest tests/exporter/test_run_summary_store.py
pytest tests/exporter/test_run_warning_store.py
pytest tests/exporter/test_structure_jsonl_exporter.py
```

검증 항목:

- 파일 없음에서 생성
- 1.0 → 2.0 변환
- 기존 2.0에 새 영역 자동 보완
- 다른 영역 보존
- 여러 영역 원자 갱신
- 깨진 Summary 보존
- run_id 불일치 거부
- component별 경고 교체
- 여러 component 동시 교체
- legacy Issue 경고 해석
- 깨진 Warning 파일 보존
