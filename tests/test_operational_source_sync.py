from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jira_collector.jira_client import ApiResult
from jira_collector.raw_store import RawStore
from jira_collector.source_sync import OperationalSourceSync
from jira_collector.state_store import StateStore


class FakeJiraClient:
    def __init__(
        self,
        settings: Any,
        *,
        server_time: str,
        projects: list[dict[str, Any]] | None = None,
        issues: list[dict[str, str]] | None = None,
        details: dict[str, dict[str, Any]] | None = None,
        fail_project_discovery: bool = False,
        fail_detail_issue_key: str | None = None,
    ) -> None:
        self.settings = settings
        self.server_time = server_time
        self.projects = projects if projects is not None else []
        self.issues = issues if issues is not None else []
        self.details = details if details is not None else {}
        self.fail_project_discovery = fail_project_discovery
        self.fail_detail_issue_key = fail_detail_issue_key
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> ApiResult:
        query = dict(params or {})
        self.calls.append((path, query))

        if path == "/serverInfo":
            return self._result(
                path,
                {
                    "serverTime": self.server_time,
                    "serverTimeZone": "Asia/Seoul",
                },
            )
        if path == self.settings.project_list_path:
            if self.fail_project_discovery:
                raise RuntimeError("discovery failed")
            return self._result(path, self.projects)
        if path == self.settings.issue_search_path:
            start = int(query.get("startAt", 0))
            limit = int(query.get("maxResults", len(self.issues) or 1))
            rows = self.issues[start : start + limit]
            return self._result(
                path,
                {
                    "startAt": start,
                    "maxResults": limit,
                    "total": len(self.issues),
                    "issues": [
                        {
                            "id": item["id"],
                            "key": item["key"],
                            "fields": {"updated": item["updated"]},
                        }
                        for item in rows
                    ],
                },
            )
        if path.endswith("/comment"):
            return self._result(
                path,
                {"startAt": 0, "maxResults": 100, "total": 0, "comments": []},
            )
        if path.startswith("/issue/"):
            issue_key = path.split("/")[2]
            if self.fail_detail_issue_key == issue_key:
                raise RuntimeError(f"detail failed: {issue_key}")
            return self._result(path, self.details[issue_key])
        raise AssertionError(f"unexpected Jira path: {path}")

    @staticmethod
    def _result(path: str, payload: Any) -> ApiResult:
        return ApiResult(payload=payload, status_code=200, url=path, headers={})


def _project() -> dict[str, str]:
    return {"id": "10000", "key": "ABC", "name": "Alpha"}


def _issue_stub(issue_id: str, key: str, updated: str) -> dict[str, str]:
    return {"id": issue_id, "key": key, "updated": updated}


def _issue_payload(
    issue_id: str,
    key: str,
    updated: str,
    *,
    description: str = "description",
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "key": key,
        "fields": {
            "project": {"key": "ABC"},
            "summary": f"summary {key}",
            "description": description,
            "issuetype": {"name": "Bug"},
            "status": {"name": "Open"},
            "priority": {"name": "Major"},
            "created": "2026-08-01T09:00:00.000+0900",
            "updated": updated,
            "attachment": [],
            "issuelinks": [],
            "subtasks": [],
        },
        "renderedFields": {"description": description},
        "names": {},
        "schema": {},
    }


def _components(app_settings: Any) -> tuple[RawStore, StateStore]:
    raw = RawStore(app_settings.storage.data_root, app_settings.storage.raw_directory)
    state = StateStore(app_settings.storage.state_root / "collector.db")
    return raw, state


def _project_run(state: StateStore, source_run_id: str) -> dict[str, Any]:
    with state.connect() as connection:
        row = connection.execute(
            "SELECT * FROM source_project_run WHERE source_run_id = ? AND project_id = '10000'",
            (source_run_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _work_rows(state: StateStore) -> list[dict[str, Any]]:
    with state.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM sync_issue_change ORDER BY created_at, work_item_id"
        ).fetchall()
    return [dict(row) for row in rows]


def _search_jql(client: FakeJiraClient) -> str:
    calls = [params for path, params in client.calls if path == client.settings.issue_search_path]
    assert calls
    return str(calls[0]["jql"])


def test_initial_ingest_uses_jira_clock_fixed_upper_and_creates_ready_work(
    app_settings: Any,
) -> None:
    raw, state = _components(app_settings)
    updated = "2026-08-31T20:35:00.000+0900"
    client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:40:42.000+0900",
        projects=[_project()],
        issues=[_issue_stub("20000", "ABC-1", updated)],
        details={"ABC-1": _issue_payload("20000", "ABC-1", updated)},
    )

    result = OperationalSourceSync(client, raw, state).run()

    assert result.status == "completed"
    assert result.source_committed_project_count == 1
    project = state.get_project_state("10000")
    assert project["committed_watermark"] == "2026-08-31T11:40:00+00:00"
    run = _project_run(state, result.source_run_id)
    assert run["operation_kind"] == "initial_ingest"
    assert run["lower_bound"] is None
    assert run["new_count"] == 1
    assert run["changed_count"] == 0
    assert run["unchanged_count"] == 0

    jql = _search_jql(client)
    assert 'updated < "2026-08-31 20:40"' in jql
    assert "ORDER BY updated ASC, id ASC" in jql
    assert "updated >=" not in jql

    work = _work_rows(state)
    assert len(work) == 1
    assert work[0]["change_kind"] == "new"
    assert work[0]["last_source_committed_run_id"] == result.source_run_id
    assert work[0]["work_status"] == "pending"

    package_path = (
        app_settings.storage.data_root
        / "knowledge_input"
        / "runs"
        / result.source_run_id
        / "issues"
        / "ABC-1.json"
    )
    analysis_path = (
        app_settings.storage.data_root
        / "analysis"
        / result.source_run_id
        / "projects"
        / "ABC"
        / "issues"
        / "ABC-1"
        / "analysis.json"
    )
    assert package_path.is_file()
    assert analysis_path.is_file()
    package = json.loads(package_path.read_text(encoding="utf-8"))
    assert package["source_hash_profile"] == "semantic_v2"


def test_timestamp_only_delta_is_unchanged_and_advances_watermark(
    app_settings: Any,
) -> None:
    raw, state = _components(app_settings)
    first_updated = "2026-08-31T20:35:00.000+0900"
    first_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:40:42.000+0900",
        projects=[_project()],
        issues=[_issue_stub("20000", "ABC-1", first_updated)],
        details={"ABC-1": _issue_payload("20000", "ABC-1", first_updated)},
    )
    first = OperationalSourceSync(first_client, raw, state).run()
    first_hash = _work_rows(state)[0]["source_hash"]

    second_updated = "2026-08-31T20:45:00.000+0900"
    second_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:50:12.000+0900",
        projects=[_project()],
        issues=[_issue_stub("20000", "ABC-1", second_updated)],
        details={"ABC-1": _issue_payload("20000", "ABC-1", second_updated)},
    )
    second = OperationalSourceSync(second_client, raw, state).run()

    run = _project_run(state, second.source_run_id)
    assert run["operation_kind"] == "delta"
    assert run["new_count"] == 0
    assert run["changed_count"] == 0
    assert run["unchanged_count"] == 1
    assert state.get_project_state("10000")["committed_watermark"] == (
        "2026-08-31T11:50:00+00:00"
    )
    assert len(_work_rows(state)) == 1
    assert _work_rows(state)[0]["source_hash"] == first_hash
    assert _work_rows(state)[0]["last_source_committed_run_id"] == first.source_run_id

    jql = _search_jql(second_client)
    assert 'updated >= "2026-08-31 20:35"' in jql
    assert 'updated < "2026-08-31 20:50"' in jql


def test_meaningful_delta_creates_changed_work_and_supersedes_pending_old_work(
    app_settings: Any,
) -> None:
    raw, state = _components(app_settings)
    first_updated = "2026-08-31T20:35:00.000+0900"
    first_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:40:42.000+0900",
        projects=[_project()],
        issues=[_issue_stub("20000", "ABC-1", first_updated)],
        details={"ABC-1": _issue_payload("20000", "ABC-1", first_updated)},
    )
    first = OperationalSourceSync(first_client, raw, state).run()
    old_work_id = _work_rows(state)[0]["work_item_id"]

    second_updated = "2026-08-31T20:45:00.000+0900"
    second_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:50:12.000+0900",
        projects=[_project()],
        issues=[_issue_stub("20000", "ABC-1", second_updated)],
        details={
            "ABC-1": _issue_payload(
                "20000",
                "ABC-1",
                second_updated,
                description="meaningfully changed description",
            )
        },
    )
    second = OperationalSourceSync(second_client, raw, state).run()

    run = _project_run(state, second.source_run_id)
    assert run["changed_count"] == 1
    rows = _work_rows(state)
    assert len(rows) == 2
    old = next(row for row in rows if row["work_item_id"] == old_work_id)
    new = next(row for row in rows if row["work_item_id"] != old_work_id)
    assert old["work_status"] == "superseded"
    assert old["superseded_by_work_item_id"] == new["work_item_id"]
    assert new["work_status"] == "pending"
    assert new["last_source_committed_run_id"] == second.source_run_id
    assert state.count_latest_ready_work_items() == 1
    assert first.source_run_id != second.source_run_id


def test_successful_discovery_absence_marks_project_unavailable_without_moving_watermark(
    app_settings: Any,
) -> None:
    raw, state = _components(app_settings)
    updated = "2026-08-31T20:35:00.000+0900"
    first_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:40:42.000+0900",
        projects=[_project()],
        issues=[_issue_stub("20000", "ABC-1", updated)],
        details={"ABC-1": _issue_payload("20000", "ABC-1", updated)},
    )
    OperationalSourceSync(first_client, raw, state).run()
    watermark = state.get_project_state("10000")["committed_watermark"]

    missing_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T21:00:12.000+0900",
        projects=[],
    )
    missing = OperationalSourceSync(missing_client, raw, state).run()

    project = state.get_project_state("10000")
    assert missing.status == "completed"
    assert missing.visible_project_count == 0
    assert project["visibility_state"] == "unavailable"
    assert project["committed_watermark"] == watermark
    with state.connect() as connection:
        row = connection.execute(
            "SELECT source_status FROM source_project_run WHERE source_run_id = ? AND project_id = '10000'",
            (missing.source_run_id,),
        ).fetchone()
    assert row is not None
    assert row["source_status"] == "skipped_unavailable"


def test_failed_discovery_does_not_change_existing_visibility(app_settings: Any) -> None:
    raw, state = _components(app_settings)
    updated = "2026-08-31T20:35:00.000+0900"
    first_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:40:42.000+0900",
        projects=[_project()],
        issues=[_issue_stub("20000", "ABC-1", updated)],
        details={"ABC-1": _issue_payload("20000", "ABC-1", updated)},
    )
    OperationalSourceSync(first_client, raw, state).run()

    failed_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T21:00:12.000+0900",
        fail_project_discovery=True,
    )
    with pytest.raises(RuntimeError, match="discovery failed"):
        OperationalSourceSync(failed_client, raw, state).run()

    project = state.get_project_state("10000")
    assert project["visibility_state"] == "visible"
    assert project["unavailable_since"] is None


def test_same_source_run_resume_uses_cursor_and_commits_after_failed_candidate(
    app_settings: Any,
) -> None:
    raw, state = _components(app_settings)
    first_updated = "2026-08-31T20:31:00.000+0900"
    second_updated = "2026-08-31T20:32:00.000+0900"
    issues = [
        _issue_stub("20000", "ABC-1", first_updated),
        _issue_stub("20001", "ABC-2", second_updated),
    ]
    details = {
        "ABC-1": _issue_payload("20000", "ABC-1", first_updated),
        "ABC-2": _issue_payload("20001", "ABC-2", second_updated),
    }
    failing_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:40:42.000+0900",
        projects=[_project()],
        issues=issues,
        details=details,
        fail_detail_issue_key="ABC-2",
    )

    first_attempt = OperationalSourceSync(failing_client, raw, state).run()
    assert first_attempt.status == "failed"
    failed_run = _project_run(state, first_attempt.source_run_id)
    assert failed_run["candidate_count"] == 1
    assert failed_run["cursor_jira_id"] == "20000"
    assert state.get_project_state("10000")["committed_watermark"] is None
    assert state.count_latest_ready_work_items() == 0

    resume_client = FakeJiraClient(
        app_settings.jira,
        server_time="2026-08-31T20:55:00.000+0900",
        projects=[_project()],
        issues=issues,
        details=details,
    )
    resumed = OperationalSourceSync(resume_client, raw, state).resume(
        first_attempt.source_run_id
    )

    assert resumed.source_run_id == first_attempt.source_run_id
    assert resumed.status == "completed"
    completed_run = _project_run(state, resumed.source_run_id)
    assert completed_run["candidate_count"] == 2
    assert completed_run["new_count"] == 2
    assert completed_run["cursor_jira_id"] == "20001"
    assert state.get_project_state("10000")["committed_watermark"] == (
        "2026-08-31T11:40:00+00:00"
    )
    assert state.count_latest_ready_work_items() == 2
    detail_calls = [path for path, _ in resume_client.calls if path.startswith("/issue/") and not path.endswith("/comment")]
    assert detail_calls == ["/issue/ABC-2"]
