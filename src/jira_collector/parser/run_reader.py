from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .models import IssueSource


class RunNotFoundError(FileNotFoundError):
    pass


class RunReader:
    """Discover issue artifacts from one immutable collector run."""

    def __init__(self, data_root: str | Path, raw_directory: str = "raw") -> None:
        self.data_root = Path(data_root)
        self.raw_root = self.data_root / raw_directory

    def run_root(self, run_id: str) -> Path:
        self._validate_component(run_id, "run_id")
        root = self.raw_root / "runs" / run_id
        if not root.is_dir():
            raise RunNotFoundError(f"run_id directory not found: {root}")
        return root

    def iter_issue_sources(self, run_id: str) -> Iterator[IssueSource]:
        projects_dir = self.run_root(run_id) / "projects"
        if not projects_dir.is_dir():
            return

        for project_dir in sorted(projects_dir.iterdir(), key=lambda item: item.name):
            if not project_dir.is_dir():
                continue
            issues_dir = project_dir / "issues"
            if not issues_dir.is_dir():
                continue
            for issue_dir in sorted(issues_dir.iterdir(), key=lambda item: item.name):
                if not issue_dir.is_dir():
                    continue
                issue_path = issue_dir / "issue.json"
                if not issue_path.is_file():
                    continue
                yield IssueSource(
                    run_id=run_id,
                    project_key=project_dir.name,
                    issue_key=issue_dir.name,
                    issue_path=issue_path,
                    comments_dir=issue_dir / "comments",
                )

    def list_issue_sources(self, run_id: str) -> list[IssueSource]:
        return list(self.iter_issue_sources(run_id))

    @staticmethod
    def _validate_component(value: str, label: str) -> None:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError(f"invalid {label}: {value!r}")
