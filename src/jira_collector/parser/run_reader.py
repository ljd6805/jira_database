from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .models import IssueSource


class RunNotFoundError(FileNotFoundError):
    """요청한 run_id의 원본 수집 디렉터리를 찾지 못했을 때 발생합니다."""


class RunReader:
    """변경하지 않는 수집 실행 디렉터리에서 이슈 원본 파일을 탐색합니다."""

    def __init__(self, data_root: str | Path, raw_directory: str = "raw") -> None:
        """데이터 루트와 Raw 디렉터리 이름을 기준으로 탐색기를 초기화합니다."""

        self.data_root = Path(data_root)
        self.raw_root = self.data_root / raw_directory

    def run_root(self, run_id: str) -> Path:
        """run_id에 해당하는 수집 실행 디렉터리를 검증해 반환합니다."""

        self._validate_component(run_id, "run_id")
        root = self.raw_root / "runs" / run_id
        if not root.is_dir():
            raise RunNotFoundError(f"run_id 디렉터리를 찾을 수 없습니다: {root}")
        return root

    def iter_issue_sources(self, run_id: str) -> Iterator[IssueSource]:
        """run_id 아래의 모든 issue.json을 정렬된 순서로 순회합니다."""

        projects_dir = self.run_root(run_id) / "projects"
        if not projects_dir.is_dir():
            return

        # 프로젝트와 이슈 폴더 이름을 정렬해 실행마다 동일한 순서를 보장합니다.
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
        """run_id 아래의 모든 이슈 원본 경로를 목록으로 반환합니다."""

        return list(self.iter_issue_sources(run_id))

    @staticmethod
    def _validate_component(value: str, label: str) -> None:
        """경로 이동을 유발할 수 있는 위험한 경로 구성요소를 거부합니다."""

        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError(f"유효하지 않은 {label}입니다: {value!r}")
