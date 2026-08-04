from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IssueSource:
    """Filesystem locations that belong to one collected Jira issue."""

    run_id: str
    project_key: str
    issue_key: str
    issue_path: Path
    comments_dir: Path


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """Non-fatal parser observation that should be reviewed later."""

    code: str
    message: str
    json_path: str | None = None


@dataclass(frozen=True, slots=True)
class IssueRecord:
    """First-stage normalized view of one Jira issue."""

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
    """Parsed issue plus observations that did not prevent parsing."""

    record: IssueRecord
    warnings: tuple[ParseWarning, ...] = ()
