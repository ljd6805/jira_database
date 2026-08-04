from __future__ import annotations

from pathlib import Path

import pytest

from jira_collector.parser import RunNotFoundError, RunReader


def _touch_issue(root: Path, project_key: str, issue_key: str) -> None:
    issue_dir = root / "projects" / project_key / "issues" / issue_key
    issue_dir.mkdir(parents=True)
    (issue_dir / "issue.json").write_text("{}", encoding="utf-8")


def test_lists_issue_sources_in_stable_order(tmp_path: Path) -> None:
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
    reader = RunReader(tmp_path)

    with pytest.raises(RunNotFoundError):
        reader.list_issue_sources("missing")
    with pytest.raises(ValueError):
        reader.list_issue_sources("../run1")
