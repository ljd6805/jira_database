from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class KnowledgeInputBuildError(ValueError):
    """ANALYSIS 입력을 안전하게 Knowledge Input으로 만들 수 없을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class KnowledgeInputBuildResult:
    """한 run_id의 이슈 패키지 생성 결과를 요약합니다."""

    run_id: str
    status: str
    issue_count: int
    package_count: int
    comment_count: int
    attachment_count: int
    relationship_count: int
    custom_field_value_count: int
    warning_count: int
    issues_directory: Path
    manifest_path: Path
    warnings_path: Path
