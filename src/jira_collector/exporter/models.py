from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class IssueExportResult:
    """한 run_id의 이슈 JSONL 내보내기 결과를 요약합니다."""

    run_id: str
    discovered_issue_count: int
    exported_issue_count: int
    failed_issue_count: int
    warning_count: int
    parse_error_count: int
    issues_path: Path
    warnings_path: Path
    summary_path: Path
