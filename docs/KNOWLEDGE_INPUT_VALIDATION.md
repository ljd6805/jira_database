# Knowledge Input 실환경 검증 기록

## 1. 목적

이 문서는 `IssueKnowledgeInputBuilder`가 실제 사내 Jira 파일럿 ANALYSIS 데이터에서 정상 동작했는지 검증한 기준 결과를 기록합니다.

실제 Jira 업무 내용은 문서에 저장하지 않고 **건수, 상태, 경고 여부**만 기록합니다.

---

## 2. 검증 대상

입력 계층:

```text
[ANALYSIS]
data/analysis/<run_id>/
```

필수 입력:

```text
issues.jsonl
comments.jsonl
attachments.jsonl
issue_relationships.jsonl
custom_field_catalog.jsonl
custom_field_values.jsonl
summary.json
```

선행 ANALYSIS 단계는 모두 실환경에서 `completed` 상태를 확인했습니다.

---

## 3. 선행 데이터 집계

### Issue

```text
30건
```

### Comment

```text
278건
```

### Attachment metadata

```text
79건
```

### Canonical Relationship

```text
6건
├─ issue_link 2
└─ hierarchy 4
```

### Custom Field

```text
Catalog 정의        220
실제 사용 Field      16
non-null Value       447
```

선행 Structure Export 경고 및 실패:

```text
0건
```

---

## 4. Knowledge Input 실행 결과

실행 명령:

```powershell
python -m jira_collector.cli build-knowledge-input --run-id <RUN_ID>
```

실제 출력 집계:

```text
대상 이슈: 30개
생성 패키지: 30개
포함 댓글: 278개
포함 첨부파일: 79개
canonical 관계: 6개
Custom Field 값: 447개
패키지 경고: 0개
```

`manifest.json` 확인 결과:

```text
status = completed
```

---

## 5. 정합성 검증 결과

선행 ANALYSIS 집계와 Knowledge Input manifest 집계가 일치했습니다.

| 항목 | ANALYSIS | KNOWLEDGE INPUT | 결과 |
|---|---:|---:|---|
| Issue | 30 | 30 package | 일치 |
| Comment | 278 | 278 | 일치 |
| Attachment | 79 | 79 | 일치 |
| Canonical Relationship | 6 | 6 | 일치 |
| Custom Field Value | 447 | 447 | 일치 |
| Package Warning | - | 0 | 정상 |

Relationship은 package 내부에서 양 endpoint 관점으로 표시될 수 있으므로 각 package의 `relationship_count` 합계와 canonical 관계 6건은 같을 필요가 없습니다.

manifest의 `relationship_count=6`은 ANALYSIS의 canonical edge 수를 의미합니다.

---

## 6. 테스트 결과

사용자 환경에서 전체 테스트를 실행했습니다.

```powershell
pytest
```

결과:

```text
100% PASS
```

Knowledge Input 구현 전용 단위 테스트에서도 다음 항목을 검증합니다.

```text
완료되지 않은 ANALYSIS 거부
Issue 1건 → Package 1건
Comment / Attachment / Custom Field Join
Relationship source/target 관점 생성
파일럿 밖 Relationship endpoint 보존
개인정보 재복제 방지
source_hash의 경로 독립성
고아 ANALYSIS 레코드 경고
stale package 삭제
manifest 최종 완료 표식
```

---

## 7. 완료 판정

파일럿 기준으로 다음 조건을 모두 만족했으므로 Knowledge Input 단계는 완료로 판정합니다.

```text
[완료] 대상 Issue와 Package 수 일치
[완료] Comment 전체 포함
[완료] Attachment metadata 전체 포함
[완료] Canonical Relationship 전체 반영
[완료] Custom Field Value 전체 반영
[완료] package warning 0
[완료] manifest completed
[완료] pytest 100% pass
```

---

## 8. 회귀 기준

향후 Builder를 변경한 뒤 같은 파일럿 snapshot으로 재검증할 수 있다면 최소 다음 조건을 확인합니다.

```text
package_count == issue_count
ANALYSIS Comment count == manifest Comment count
ANALYSIS Attachment count == manifest Attachment count
ANALYSIS canonical Relationship count == manifest Relationship count
ANALYSIS Custom Field Value count == manifest count
warning_count == 0  # 동일 snapshot 기준 기대값
```

`source_hash` 알고리즘 또는 package schema를 변경하는 경우 이 문서의 기준을 그대로 사용하기 전에 schema version과 변경 이유를 먼저 기록해야 합니다.
