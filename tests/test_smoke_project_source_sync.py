from __future__ import annotations

from pathlib import Path

import pytest

from jira_collector.source_sync import DiscoveredProject, SourceSyncError
from jira_collector.source_sync_smoke import (
    SmokeProjectSourceSync,
    validate_smoke_project_options,
)


def _project(project_id: str, key: str) -> DiscoveredProject:
    return DiscoveredProject(
        project_id=project_id,
        key=key,
        name=key,
        raw={"id": project_id, "key": key},
    )


def test_smoke_project_filter_selects_exact_project_case_insensitively() -> None:
    projects = [_project("100", "AAA"), _project("200", "ABC")]

    selected = SmokeProjectSourceSync._select_project(projects, "abc")

    assert selected.project_id == "200"
    assert selected.key == "ABC"


def test_smoke_project_filter_fails_when_project_is_not_visible() -> None:
    projects = [_project("100", "AAA")]

    with pytest.raises(SourceSyncError, match="Smoke 대상 Project"):
        SmokeProjectSourceSync._select_project(projects, "ABC")


def test_project_key_requires_isolated_data_smoke_root() -> None:
    with pytest.raises(ValueError, match="Smoke 전용"):
        validate_smoke_project_options(
            project_key="ABC",
            resume_source_run_id=None,
            data_root=Path("data"),
        )

    validate_smoke_project_options(
        project_key="ABC",
        resume_source_run_id=None,
        data_root=Path("data_smoke"),
    )


def test_project_key_smoke_does_not_allow_resume() -> None:
    with pytest.raises(ValueError, match="resume-source-run-id"):
        validate_smoke_project_options(
            project_key="ABC",
            resume_source_run_id="sr_test",
            data_root=Path("data_smoke"),
        )
