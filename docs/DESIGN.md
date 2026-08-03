# Jira Raw Data Collector 설계

## 목표

현재 인증 계정이 Jira REST API로 조회할 수 있는 모든 프로젝트를 발견하고, 파일럿에서는 프로젝트별 최근 수정 이슈 최대 30개의 원본 응답을 보존한다.

## 이번 단계의 경계

포함:

- 프로젝트 발견
- 이슈 검색 및 상세 수집
- 누락된 댓글 페이지 추가 수집
- Raw JSON snapshot
- SQLite checkpoint
- 중단 후 재개
- SHA-256 검증
- 프로젝트별 부분 실패 격리

제외:

- 첨부파일 바이너리 다운로드
- 임베딩 및 벡터 검색
- RAG, MCP, Agent LLM
- 온톨로지
- Jira 데이터 수정

## 설정 분리

사용자별 값은 `.env`에 둔다.

```dotenv
JIRA_BASE_URL=
JIRA_USERNAME=
JIRA_PASSWORD=
```

동작 정책과 Jira REST 경로는 `config/settings.yaml`에 둔다. `.env`와 데이터 디렉터리는 Git에서 제외한다.

## 호출 제한

- 최대 20 requests/minute
- 단일 worker
- 요청 시작 간 최소 3초
- 재시도도 호출 횟수에 포함
- 429의 `Retry-After`가 3초보다 길면 해당 값 우선

## 저장 원칙

모든 Raw 응답은 `data/raw/runs/<run_id>/` 아래에 snapshot으로 저장한다. 다른 실행에서 같은 이슈가 갱신되어도 이전 실행의 파일과 hash가 변하지 않는다.

파일 저장 순서:

1. 같은 디렉터리에 임시 파일 생성
2. JSON 전체 기록
3. flush 및 fsync
4. `os.replace`로 atomic 교체
5. SQLite에 artifact와 SHA-256 기록

## checkpoint 경계

이슈 상세 JSON이 저장되어도 댓글 추가 페이지 수집이 끝나기 전에는 이슈를 완료로 표시하지 않는다. 중간 종료 시 해당 이슈를 다시 실행한다.

프로젝트 상태:

- `pending`: 대기
- `running`: 수집 중
- `completed`: 모든 대상 이슈 성공
- `partial`: 일부 이슈만 성공
- `failed`: 성공한 이슈 없이 실패

한 프로젝트가 실패해도 다음 프로젝트는 계속 진행한다.

## Jira API 호환성

사내 Jira의 정확한 배포 유형과 API 버전이 아직 코드에 고정되지 않았으므로 모든 경로를 YAML로 분리한다.

기본값:

- `/rest/api/2/project`
- `/rest/api/2/search`
- `/rest/api/2/issue/{issue_key}`
- `/rest/api/2/issue/{issue_key}/comment`

프로젝트 목록 응답은 다음 두 형태를 모두 처리한다.

- 배열을 한 번에 반환하는 Jira Server/Data Center 방식
- `values`, `startAt`, `total`, `isLast`를 사용하는 페이지 응답
