from __future__ import annotations

from pathlib import Path

from jira_collector.state_store import StateStore


def test_resume_returns_running_and_optional_failed_projects(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "collector.db")
    state.create_run("run1", 30)
    state.add_projects("run1", [("ABC", "A"), ("DEF", "D"), ("GHI", "G")], 30)
    state.start_project("run1", "ABC")
    state.complete_project("run1", "ABC", 30)
    state.start_project("run1", "DEF")
    state.fail_project("run1", "DEF", "boom")
    state.start_project("run1", "GHI")

    default = state.list_projects_for_resume("run1", include_failed=False)
    with_failed = state.list_projects_for_resume("run1", include_failed=True)

    assert [item.project_key for item in default] == ["GHI"]
    assert [item.project_key for item in with_failed] == ["DEF", "GHI"]


def test_issue_checkpoint_requires_explicit_completion(tmp_path: Path) -> None:
    state = StateStore(tmp_path / "collector.db")
    state.create_run("run1", 30)
    state.add_projects("run1", [("ABC", "A")], 30)

    state.start_issue("run1", "ABC", "ABC-1")
    assert not state.issue_is_complete("run1", "ABC", "ABC-1")

    state.complete_issue("run1", "ABC", "ABC-1")
    assert state.issue_is_complete("run1", "ABC", "ABC-1")
