from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IssueSource:
    """수집된 Jira 이슈 한 건과 연결된 파일 시스템 위치를 나타냅니다."""

    run_id: str
    project_key: str
    issue_key: str
    issue_path: Path
    comments_dir: Path


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """파싱은 계속할 수 있지만 나중에 검토해야 하는 관찰 결과를 나타냅니다."""

    code: str
    message: str
    json_path: str | None = None
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class IssueRecord:
    """Jira 이슈 한 건의 1차 표준화 결과를 나타냅니다."""

    run_id: str
    project_key: str
    issue_key: str
    jira_id: str | None
    summary: str | None
    description_raw: Any
    description_rendered: str | None
    description_text: str | None
    description_format: str
    issue_type: str | None
    status: str | None
    priority: str | None
    created_at: str | None
    updated_at: str | None
    source_path: str


@dataclass(frozen=True, slots=True)
class IssueParseResult:
    """이슈 파싱 결과와 비치명적 경고를 함께 보관합니다."""

    record: IssueRecord
    warnings: tuple[ParseWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class CommentRecord:
    """Jira 댓글 한 건의 1차 표준화 결과를 나타냅니다."""

    run_id: str
    project_key: str
    issue_key: str
    comment_id: str
    sequence: int
    author_name: str | None
    author_key: str | None
    created_at: str | None
    updated_at: str | None
    body_raw: Any
    body_text: str | None
    body_format: str
    source_path: str
    source_page: str


@dataclass(frozen=True, slots=True)
class CommentParseResult:
    """한 이슈의 댓글 페이지 전체를 파싱한 결과와 집계값을 보관합니다."""

    records: tuple[CommentRecord, ...]
    warnings: tuple[ParseWarning, ...] = ()
    page_count: int = 0
    discovered_comment_count: int = 0
    duplicate_comment_count: int = 0
    failed_page_count: int = 0
    failed_comment_count: int = 0
    missing_comment_source_count: int = 0
