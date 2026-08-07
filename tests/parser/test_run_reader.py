from __future__ import annotations

from pathlib import Path

import pytest

from jira_collector.parser import RunNotFoundError, RunReader


def _touch_issue(root: Path, project_key: str, issue_key: str) -> None:
    """테스트용 issue.json을 실제 수집 경로 형태로 생성합니다."""

    issue_dir = root / "projects" / project_key / "issues" / issue_key
    issue_dir.mkdir(parents=True)
    (issue_dir / "issue.json").write_text("{}", encoding="utf-8")


def test_lists_issue_sources_in_stable_order(tmp_path: Path) -> None:
    """프로젝트와 이슈 경로를 안정적인 정렬 순서로 반환하는지 확인합니다."""

    run_root = tmp_path / "raw" / "runs" / "run1"
    _touch_issue(run_root, "XYZ", "XYZ-2")
    _touch_issue(run_root, "ABC", "ABC-10")
    _touch_issue(run_root, "ABC", "ABC-2")
    missing = run_root / "projects" / "ABC" / "issues" / "ABC-99"
    missing.mkdir(parents=True)

    sources = RunReader(tmp_path).list_issue_sources("run1")

    assert [(item.project_key, item.issue_key) for item in sources] == [
        ("ABC", "ABC-10"),
        ("ABC", "ABC-2"),
        ("XYZ", "XYZ-2"),
    ]
    assert sources[0].comments_dir.name == "comments"


def test_rejects_missing_run_and_path_components(tmp_path: Path) -> None:
    """없는 run_id와 경로 이동 문자열을 거부하는지 확인합니다."""

    reader = RunReader(tmp_path)

    with pytest.raises(RunNotFoundError):
        reader.list_issue_sources("missing")
    with pytest.raises(ValueError):
        reader.list_issue_sources("../run1")
