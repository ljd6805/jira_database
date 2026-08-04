# Jira 댓글 수집 계약

## 목적

Jira 이슈 상세 응답의 `fields.comment` 포함 범위는 Jira 버전과 서버 설정에 따라 달라질 수 있습니다. 일부 환경에서는 전체 댓글이 들어오고, 일부 환경에서는 일부 댓글만 들어오거나 필드 자체가 생략될 수 있습니다.

후속 처리에서 이러한 차이를 매번 해석하지 않도록 댓글 전용 API 응답을 댓글의 기준 원본으로 사용합니다.

## 확정 동작

`config/settings.yaml`의 다음 설정이 `true`이면:

```yaml
jira:
  collection:
    collect_comments: true
```

수집기는 모든 이슈에 대해 다음 순서로 동작합니다.

1. 이슈 상세 API 응답을 `issue.json`으로 저장합니다.
2. 상세 응답에 댓글이 이미 포함되어 있는지 확인하지 않습니다.
3. 댓글 전용 API를 `startAt=0`부터 호출합니다.
4. 응답을 `comments/page_0001.json`부터 순서대로 저장합니다.
5. `startAt + len(comments) >= total`이 될 때까지 다음 페이지를 호출합니다.
6. 댓글이 0개여도 빈 첫 응답을 `comments/page_0001.json`으로 저장합니다.
7. 이슈 상세와 댓글 페이지 저장이 모두 끝난 뒤에만 이슈 checkpoint를 `completed`로 변경합니다.

## 저장 예시

```text
data/raw/runs/<run_id>/projects/ABC/issues/ABC-123/
├─ issue.json
└─ comments/
   ├─ page_0001.json
   └─ page_0002.json
```

## 중복에 대한 결정

이슈 상세 응답의 `fields.comment.comments`에 댓글이 들어 있으면 동일 댓글이 `issue.json`과 `comments/page_*.json`에 중복될 수 있습니다.

이는 현재 원본 수집 MVP에서 허용합니다. 후속 정규화 단계에서는 댓글 전용 API 파일을 기준으로 댓글을 읽고, `comment.id`를 기준으로 중복을 제거합니다.

## 호출량 영향

댓글 수집을 켜면 이슈마다 댓글 API 호출이 최소 1회 추가됩니다. 댓글이 많으면 페이지 수만큼 호출이 늘어납니다. 모든 요청은 기존 분당 20회 rate limiter를 통과합니다.

## 실패 처리

댓글 전용 API 호출 또는 댓글 페이지 저장이 실패하면 해당 이슈는 `completed`로 처리하지 않습니다. 오류는 이슈 checkpoint에 기록되며 기존 `run_id`를 이용해 재개할 수 있습니다.
