from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IssueSource:
    """수집된 Jira 이슈 하나에 속하는 원본 파일 경로를 나타냅니다."""

    run_id: str
    project_key: str
    issue_key: str
    issue_path: Path
    comments_dir: Path


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """파싱은 계속할 수 있지만 추후 검토가 필요한 관찰 결과를 나타냅니다."""

    code: str
    message: str
    json_path: str | None = None


@dataclass(frozen=True, slots=True)
class IssueRecord:
    """Jira 이슈 하나를 1차 정규화한 중간 레코드입니다."""

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
    """파싱된 이슈 레코드와 비치명적 경고를 함께 보관합니다."""

    record: IssueRecord
    warnings: tuple[ParseWarning, ...] = ()
