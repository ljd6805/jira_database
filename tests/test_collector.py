from __future__ import annotations

from collections import deque
from pathlib import Path

from jira_collector.collector import JiraCollector
from jira_collector.jira_client import ApiResult
from jira_collector.raw_store import RawStore
from jira_collector.state_store import StateStore


class RoutedFakeClient:
    def __init__(self, settings, routes):
        self.settings = settings
        self.routes = {key: deque(values) for key, values in routes.items()}
        self.calls = []

    def get_json(self, path, *, params=None):
        self.calls.append((path, dict(params or {})))
        if path not in self.routes or not self.routes[path]:
            raise AssertionError(f"unexpected call: {path} {params}")
        payload = self.routes[path].popleft()
        return ApiResult(payload=payload, status_code=200, url=f"https://jira{path}", headers={})


def _new_collector(app_settings, tmp_path: Path, client: RoutedFakeClient):
    state = StateStore(tmp_path / "collector.db")
    state.create_run("run1", 30)
    state.add_projects("run1", [("ABC", "Alpha")], 30)
    return JiraCollector(client, RawStore(tmp_path / "data"), state), state


def test_collects_all_comment_pages_from_zero_even_when_issue_embeds_comments(
    app_settings,
    tmp_path: Path,
) -> None:
    client = RoutedFakeClient(
        app_settings.jira,
        {
            "/search": [
                {
                    "startAt": 0,
                    "maxResults": 2,
                    "total": 1,
                    "issues": [{"key": "ABC-1"}],
                }
            ],
            "/issue/ABC-1": [
                {
                    "key": "ABC-1",
                    "fields": {
                        "updated": "2026-08-03T10:00:00.000+0900",
                        "comment": {
                            "startAt": 0,
                            "maxResults": 1,
                            "total": 3,
                            "comments": [{"id": "1", "body": "embedded"}],
                        },
                    },
                }
            ],
            "/issue/ABC-1/comment": [
                {
                    "startAt": 0,
                    "maxResults": 2,
                    "total": 3,
                    "comments": [
                        {"id": "1", "body": "first"},
                        {"id": "2", "body": "second"},
                    ],
                },
                {
                    "startAt": 2,
                    "maxResults": 2,
                    "total": 3,
                    "comments": [{"id": "3", "body": "third"}],
                },
            ],
        },
    )
    collector, state = _new_collector(app_settings, tmp_path, client)

    count = collector.collect_project("run1", "ABC", issues_per_project=30)

    assert count == 1
    assert state.issue_is_complete("run1", "ABC", "ABC-1")
    assert [item.artifact_type for item in state.list_artifacts("run1")] == [
        "issue_search_page",
        "issue",
        "comment_page",
        "comment_page",
    ]
    comment_calls = [call for call in client.calls if call[0].endswith("/comment")]
    assert [call[1]["startAt"] for call in comment_calls] == [0, 2]


def test_calls_comment_api_even_when_issue_contains_all_comments(
    app_settings,
    tmp_path: Path,
) -> None:
    client = RoutedFakeClient(
        app_settings.jira,
        {
            "/search": [
                {"startAt": 0, "total": 1, "issues": [{"key": "ABC-1"}]}
            ],
            "/issue/ABC-1": [
                {
                    "key": "ABC-1",
                    "fields": {
                        "comment": {
                            "startAt": 0,
                            "total": 1,
                            "comments": [{"id": "1", "body": "embedded"}],
                        }
                    },
                }
            ],
            "/issue/ABC-1/comment": [
                {
                    "startAt": 0,
                    "total": 1,
                    "comments": [{"id": "1", "body": "from comment API"}],
                }
            ],
        },
    )
    collector, state = _new_collector(app_settings, tmp_path, client)

    assert collector.collect_project("run1", "ABC", issues_per_project=30) == 1

    comment_calls = [call for call in client.calls if call[0].endswith("/comment")]
    assert len(comment_calls) == 1
    assert comment_calls[0][1]["startAt"] == 0
    assert [item.artifact_type for item in state.list_artifacts("run1")].count(
        "comment_page"
    ) == 1


def test_saves_empty_comment_page_for_issue_without_comments(
    app_settings,
    tmp_path: Path,
) -> None:
    client = RoutedFakeClient(
        app_settings.jira,
        {
            "/search": [
                {"startAt": 0, "total": 1, "issues": [{"key": "ABC-1"}]}
            ],
            "/issue/ABC-1": [{"key": "ABC-1", "fields": {}}],
            "/issue/ABC-1/comment": [
                {"startAt": 0, "maxResults": 100, "total": 0, "comments": []}
            ],
        },
    )
    collector, state = _new_collector(app_settings, tmp_path, client)

    assert collector.collect_project("run1", "ABC", issues_per_project=30) == 1
    assert state.issue_is_complete("run1", "ABC", "ABC-1")
    comment_artifacts = [
        item for item in state.list_artifacts("run1") if item.artifact_type == "comment_page"
    ]
    assert len(comment_artifacts) == 1
    assert comment_artifacts[0].relative_path.endswith(
        "projects/ABC/issues/ABC-1/comments/page_0001.json"
    )
