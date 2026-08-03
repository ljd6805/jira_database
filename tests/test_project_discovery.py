from __future__ import annotations

from collections import deque
from pathlib import Path

from jira_collector.jira_client import ApiResult
from jira_collector.project_discovery import ProjectDiscovery
from jira_collector.raw_store import RawStore
from jira_collector.state_store import StateStore


class FakeClient:
    def __init__(self, settings, payloads):
        self.settings = settings
        self.payloads = deque(payloads)
        self.calls = []

    def get_json(self, path, *, params=None):
        self.calls.append((path, params))
        payload = self.payloads.popleft()
        return ApiResult(payload=payload, status_code=200, url="https://jira/api", headers={})


def test_discovers_paginated_projects(app_settings, tmp_path: Path) -> None:
    client = FakeClient(
        app_settings.jira,
        [
            {
                "startAt": 0,
                "maxResults": 2,
                "total": 3,
                "isLast": False,
                "values": [
                    {"key": "ABC", "name": "Alpha"},
                    {"key": "DEF", "name": "Delta"},
                ],
            },
            {
                "startAt": 2,
                "maxResults": 2,
                "total": 3,
                "isLast": True,
                "values": [{"key": "GHI", "name": "Gamma"}],
            },
        ],
    )
    state = StateStore(tmp_path / "collector.db")
    state.create_run("run1", 30)
    discovery = ProjectDiscovery(client, RawStore(tmp_path / "data"), state)

    projects = discovery.discover("run1")

    assert [project.key for project in projects] == ["ABC", "DEF", "GHI"]
    assert len(client.calls) == 2
    assert client.calls[1][1]["startAt"] == 2
    assert len(state.list_artifacts("run1")) == 2


def test_accepts_non_paginated_project_array(app_settings, tmp_path: Path) -> None:
    client = FakeClient(
        app_settings.jira,
        [[{"key": "ABC", "name": "Alpha"}]],
    )
    state = StateStore(tmp_path / "collector.db")
    state.create_run("run1", 30)

    projects = ProjectDiscovery(client, RawStore(tmp_path / "data"), state).discover("run1")

    assert [(project.key, project.name) for project in projects] == [("ABC", "Alpha")]
    assert len(client.calls) == 1
