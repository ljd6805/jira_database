# Knowledge Input 코드 읽기 가이드

## 1. 목적

이 문서는 `src/jira_collector/knowledge_input/` 코드를 처음 읽는 개발자나 Agent가 구현 의도를 빠르게 이해하도록 함수별 책임과 중요한 분기 이유를 설명합니다.

코드 자체의 docstring과 인라인 주석은 한글을 사용하며, 이 문서는 그 주석을 보완하는 상세 설계 설명입니다.

대상 모듈:

```text
src/jira_collector/knowledge_input/
├─ __init__.py
├─ models.py
├─ analysis_loader.py
└─ builder.py
```

---

## 2. 전체 호출 흐름

CLI:

```text
build-knowledge-input --run-id <RUN_ID>
        ↓
IssueKnowledgeInputBuilder.build_run()
        ↓
AnalysisRunLoader.load()
        ↓
ANALYSIS 검증 + issue_key 인덱싱
        ↓
이슈별 package 조립
        ↓
source_hash 계산
        ↓
issues/<ISSUE_KEY>.json 저장
        ↓
package_warnings.jsonl 저장
        ↓
manifest.json 마지막 저장
```

핵심 원칙:

- RAW를 읽지 않음
- LLM을 호출하지 않음
- ANALYSIS가 완전하지 않으면 시작하지 않음
- 한 이슈의 모든 사실을 한 파일로 묶음
- manifest를 완료 표식으로 사용

---

## 3. models.py

### `KnowledgeInputBuildError`

Knowledge Input을 안전하게 만들 수 없는 구조 오류를 표현합니다.

예:

```text
필수 ANALYSIS 파일 없음
summary run_id 불일치
summary 영역 미완료
issues.jsonl 중복 issue_key
JSONL 문법 오류
안전하지 않은 issue_key 파일명
```

이 오류는 조용히 데이터를 추측하거나 복구하지 않습니다.

최종 Agent 입력을 만드는 단계이므로, 입력 계약 자체가 깨졌다면 명시적으로 중단하는 것이 더 안전합니다.

### `KnowledgeInputBuildResult`

CLI가 사용자에게 출력할 집계 정보와 생성 경로를 전달합니다.

주요 값:

```text
issue_count
package_count
comment_count
attachment_count
relationship_count
custom_field_value_count
warning_count
issues_directory
manifest_path
warnings_path
```

---

## 4. AnalysisRunLoader

`AnalysisRunLoader`는 Builder의 단순 파일 Reader가 아닙니다.

책임은 크게 세 가지입니다.

```text
1. ANALYSIS 완전성 검증
2. JSONL 타입/run_id/유일성 검증
3. issue_key 기준 Join 인덱스 구성
```

### 4.1 `load(run_id)`

전체 ANALYSIS를 로딩하는 진입점입니다.

처리 순서:

```text
run 경로 검증
→ 필수 JSONL 존재 확인
→ summary.json completed 검증
→ issues 유일 map 생성
→ Custom Field Catalog 유일 map 생성
→ Comment / Attachment / Custom Value issue별 그룹화
→ Relationship canonical edge 읽기
→ Relationship을 양 endpoint 관점으로 인덱싱
```

반환 객체는 Builder가 바로 사용할 수 있는 in-memory index입니다.

```text
issues          issue_key → issue row
catalog         field_id → catalog row
comments        issue_key → comment rows[]
attachments     issue_key → attachment rows[]
custom_values   issue_key → field rows[]
relationships   issue_key → relationship views[]
```

### 4.2 `_validate_summary()`

필수 ANALYSIS 영역을 확인합니다.

```text
issues
comments
attachments
relationships
custom_fields
```

모두 `completed`여야 합니다.

이 검증을 넣은 이유:

```text
comments export 실패
→ comments.jsonl 일부만 존재
→ Builder가 정상 패키지를 만든 것처럼 보이면 안 됨
```

즉, 파일이 존재한다는 사실보다 **이전 단계가 완료됐다는 계약**을 우선합니다.

### 4.3 `_unique_map()`

`issues.jsonl`과 `custom_field_catalog.jsonl`처럼 식별자가 유일해야 하는 파일을 dict로 바꿉니다.

Issue의 경우:

```text
issue_key → row
```

Catalog의 경우:

```text
field_id → definition
```

중복 key를 마지막 값으로 덮어쓰지 않고 오류로 중단합니다.

왜냐하면 어느 레코드가 기준인지 임의로 선택하면 이후 Knowledge Input 자체가 비결정적이 되기 때문입니다.

### 4.4 `_group_issue_rows()`

Comment / Attachment / Custom Field Value처럼 여러 레코드가 하나의 Issue에 연결되는 데이터를 묶습니다.

```text
ABC-123 → [row1, row2, ...]
```

`issue_key`가 없거나 `issues.jsonl`에 존재하지 않는 레코드는 package에 넣지 않습니다.

대신:

```text
missing_issue_key
orphan_analysis_record
```

오류 경고를 생성합니다.

이 경우 나머지 정상 Issue package는 계속 생성할 수 있습니다.

### 4.5 `_relationship_index()`

ANALYSIS의 relationship은 canonical edge입니다.

예:

```text
A --blocks--> B
```

하지만 A package와 B package 모두 이 관계를 볼 수 있어야 합니다.

따라서:

```text
A package
current_issue_role=source
current_issue_direction=outgoing
other_issue_key=B

B package
current_issue_role=target
current_issue_direction=incoming
other_issue_key=A
```

형태의 view를 생성합니다.

canonical edge 자체는 바꾸지 않습니다.

연결 이슈가 현재 파일럿 범위 밖이면:

```text
other_package_available=false
```

를 사용합니다.

### 4.6 `_read_jsonl()`

모든 JSONL을 줄 단위로 읽습니다.

검증:

```text
빈 줄은 건너뜀
JSON 문법 확인
최상위 객체 여부 확인
run_id 일치 확인
```

전체 파일을 하나의 거대한 배열로 읽지 않는 이유는 이후 운영 데이터 증가에 대비하기 위함입니다.

---

## 5. IssueKnowledgeInputBuilder

Builder는 Loader가 준비한 index를 실제 JSON package로 조립합니다.

### 5.1 `build_run()`

run 전체 빌드의 orchestration 함수입니다.

처리 순서:

```text
ANALYSIS load
→ 기존 manifest 제거
→ issue_key 정렬
→ 이슈별 package 생성
→ 파일 원자 저장
→ stale package 제거
→ warnings 저장
→ manifest 마지막 저장
```

### 기존 manifest를 먼저 지우는 이유

`manifest.json`은 완료 표식입니다.

기존 manifest를 남긴 채 재빌드하다 프로세스가 중단되면 과거 manifest 때문에 현재 run이 정상 완료된 것처럼 오해할 수 있습니다.

따라서:

```text
빌드 시작
→ old manifest 삭제
→ package 생성
→ warning 저장
→ 모든 작업 성공
→ new manifest 저장
```

순서를 사용합니다.

### 5.2 `_package()`

Issue 하나의 데이터를 계층형 JSON으로 만듭니다.

정렬 규칙:

```text
comments      sequence → comment_id
attachments   attachment_id
relationships category → type → other_issue_key
custom_fields field_id
```

정렬은 단순 보기 편의를 위한 것이 아니라 **source_hash 재현성**을 위해 필요합니다.

같은 데이터가 순서만 달라져 hash가 바뀌면 증분 재분석 기준으로 사용할 수 없습니다.

### 5.3 Custom Field Catalog Join

Value는 `field_id`를 이용해 Catalog와 결합합니다.

```text
Custom Field Value
+ Catalog Definition
→ package custom_fields[]
```

Catalog가 없더라도 Value를 버리지는 않습니다.

대신:

```text
custom_field_definition_missing
```

warning을 기록합니다.

이는 값 손실보다 정의 누락을 명시적으로 보여주는 편이 안전하기 때문입니다.

### 5.4 `source_hash`

Hash 대상은 실제 분석 의미 데이터입니다.

```text
issue
comments
attachments
relationships
custom_fields
```

Hash 전에 `_strip_paths()`로 다음 필드를 제거합니다.

```text
source_path
source_page
```

`generated_at`은 애초에 hash material 밖에 있습니다.

따라서 데이터 루트가 다른 PC로 이동해도 같은 업무 내용이면 같은 hash를 만들 수 있습니다.

### 5.5 `_manifest()`

manifest는 전체 run의 index와 완료 결과입니다.

포함:

```text
전체 count
input_files
warnings_file
각 package path
각 package source_hash
각 package 구성요소 count
```

오류 severity가 하나라도 있으면:

```text
status=partial
```

오류가 없으면:

```text
status=completed
```

### 5.6 `_issue_doc()`

Issue에서 Agent가 분석할 핵심 필드만 선택합니다.

원본 HTML은 포함하지 않고 `description_text`를 `description`으로 사용합니다.

### 5.7 `_comment_doc()`

댓글 본문은 정제된 `body_text`를 사용합니다.

`comment_id`, `sequence`, 작성자, 시간, source를 유지해 향후 Knowledge evidence를 특정 댓글로 연결할 수 있게 합니다.

### 5.8 `_attachment_doc()`

현재는 Attachment 파일 본문을 읽지 않았으므로:

```text
content_available=false
```

를 명시합니다.

이 값은 Agent가 filename만 보고 실제 내용을 읽었다고 착각하지 않게 하기 위한 계약입니다.

### 5.9 `_relationship_doc()`

canonical edge와 현재 issue 관점을 둘 다 보존합니다.

이 구조 덕분에 향후 DB에서는 canonical graph를 유지하고, Agent 입력에서는 현재 issue 중심으로 읽을 수 있습니다.

### 5.10 `_field_doc()`

ANALYSIS의 정규화 값만 사용합니다.

Builder는 RAW를 다시 읽지 않으므로 다음 개인정보가 새로 들어오지 않습니다.

```text
emailAddress
avatarUrls
self
timeZone
전체 user object
```

### 5.11 `_portable_path()`

가능한 source_path를 `data_root` 기준 상대 경로로 바꿉니다.

목적:

- Windows / Linux 설치 경로 차이 최소화
- 다른 PC로 데이터 이동 가능
- 절대 경로의 불필요한 정보 노출 감소

상대화가 불가능한 경로는 정보 손실을 피하기 위해 원문을 유지합니다.

### 5.12 `_remove_stale()`

같은 run을 재빌드할 때 과거에는 존재했지만 현재 ANALYSIS에는 없는 Issue package를 삭제합니다.

Knowledge Input은 append log가 아니라 **현재 ANALYSIS snapshot의 재현물**이기 때문입니다.

---

## 6. AtomicTextWriter 재사용

Knowledge Input도 기존 ANALYSIS Exporter와 같은 원자 저장 도구를 사용합니다.

```text
임시 파일 작성
→ flush
→ fsync
→ os.replace
```

따라서 package JSON이나 manifest가 중간 상태로 노출되는 위험을 줄입니다.

Windows file lock 재시도 정책도 기존 코드와 동일합니다.

---

## 7. 코드 변경 시 체크리스트

Builder 또는 Loader를 수정하면 다음을 함께 확인합니다.

```text
[ ] KNOWLEDGE_INPUT_SPEC.md 갱신
[ ] PIPELINE_OVERVIEW.md의 계층 계약 확인
[ ] tests/knowledge_input/test_builder.py 갱신
[ ] source_hash 의미 변경 여부 확인
[ ] 개인정보 필드 추가 여부 확인
[ ] manifest 완료 표식 규칙 유지
[ ] stale package 처리 유지
[ ] ANALYSIS completed gate 유지
```

`source_hash`에 포함되는 필드가 달라지면 향후 Knowledge 증분 처리 의미도 달라지므로 사실상 schema contract 변경으로 봐야 합니다.
