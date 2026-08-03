from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .jira_client import JiraClient
from .project_discovery import ProjectDiscovery, ProjectInfo
from .raw_store import RawStore, safe_component
from .state_store import ProjectRun, StateStore

LOGGER = logging.getLogger(__name__)


class ProjectCollectionError(RuntimeError):
    def __init__(self, message: str, *, collected_count: int) -> None:
        super().__init__(message)
        self.collected_count = collected_count


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class JiraCollector:
    def __init__(self, client: JiraClient, raw_store: RawStore, state: StateStore) -> None:
        self.client = client
        self.raw_store = raw_store
        self.state = state
        self.discovery = ProjectDiscovery(client, raw_store, state)

    def collect_new_run(
        self,
        *,
        issues_per_project: int,
        project_filter: str | None = None,
    ) -> RunResult:
        run_id = new_run_id()
        self.state.create_run(run_id, issues_per_project)

        projects = self.discovery.discover(run_id)
        if project_filter:
            projects = [item for item in projects if item.key == project_filter]
            if not projects:
                self.state.finish_run(run_id)
                raise KeyError(f"접근 가능한 프로젝트에서 {project_filter}를 찾을 수 없습니다.")

        self.state.add_projects(
            run_id,
            [(item.key, item.name) for item in projects],
            issues_per_project,
        )
        project_map = {item.key: item for item in projects}
        self._collect_project_list(
            run_id,
            self.state.list_projects_for_resume(run_id, include_failed=False),
            project_map=project_map,
        )
        return RunResult(run_id=run_id, status=self.state.finish_run(run_id))

    def resume_run(self, run_id: str, *, include_failed: bool) -> RunResult:
        if not self.state.run_exists(run_id):
            raise KeyError(f"run_id를 찾을 수 없습니다: {run_id}")
        projects = self.state.list_projects_for_resume(run_id, include_failed=include_failed)
        self._collect_project_list(run_id, projects, project_map={})
        return RunResult(run_id=run_id, status=self.state.finish_run(run_id))

    def _collect_project_list(
        self,
        run_id: str,
        projects: list[ProjectRun],
        *,
        project_map: dict[str, ProjectInfo],
    ) -> None:
        for project_run in projects:
            project_key = project_run.project_key
            self.state.start_project(run_id, project_key)
            LOGGER.info("프로젝트 수집 시작: %s", project_key)
            try:
                project_info = project_map.get(project_key)
                if project_info is not None:
                    self._store_project_snapshot(run_id, project_info)
                count = self.collect_project(
                    run_id,
                    project_key,
                    issues_per_project=project_run.requested_count,
                )
                self.state.complete_project(run_id, project_key, count)
                LOGGER.info("프로젝트 수집 완료: %s (%s개)", project_key, count)
            except Exception as exc:  # project boundary must isolate failures
                LOGGER.error("프로젝트 수집 실패: %s: %s", project_key, exc)
                collected_count = (
                    exc.collected_count if isinstance(exc, ProjectCollectionError) else 0
                )
                self.state.fail_project(
                    run_id,
                    project_key,
                    str(exc),
                    collected_count=collected_count,
                )

    def _store_project_snapshot(self, run_id: str, project: ProjectInfo) -> None:
        artifact = self.raw_store.save_json(
            f"runs/{safe_component(run_id)}/projects/{safe_component(project.key)}/project.json",
            project.raw,
        )
        self.state.record_artifact(
            run_id=run_id,
            project_key=project.key,
            issue_key=None,
            artifact_type="project",
            relative_path=artifact.relative_path,
            content_hash=artifact.content_sha256,
            size_bytes=artifact.size_bytes,
        )

    def collect_project(self, run_id: str, project_key: str, *, issues_per_project: int) -> int:
        issues = self._search_issues(run_id, project_key, issues_per_project)
        completed = 0
        failures: list[str] = []

        for issue_stub in issues:
            issue_key = str(issue_stub.get("key") or "").strip()
            if not issue_key:
                failures.append("검색 결과에 issue key가 없는 항목이 있습니다.")
                continue

            if self.state.issue_is_complete(run_id, project_key, issue_key):
                completed += 1
                continue

            self.state.start_issue(run_id, project_key, issue_key)
            try:
                self._collect_issue(run_id, project_key, issue_key)
                self.state.complete_issue(run_id, project_key, issue_key)
                completed += 1
            except Exception as exc:
                self.state.fail_issue(run_id, project_key, issue_key, str(exc))
                failures.append(f"{issue_key}: {exc}")
                LOGGER.error("이슈 수집 실패: %s: %s", issue_key, exc)

        if failures:
            joined = "; ".join(failures[:10])
            if len(failures) > 10:
                joined += f"; 그 외 {len(failures) - 10}건"
            raise ProjectCollectionError(joined, collected_count=completed)

        return completed

    def _search_issues(
        self,
        run_id: str,
        project_key: str,
        issues_per_project: int,
    ) -> list[dict[str, Any]]:
        settings = self.client.settings
        start_at = 0
        page_number = 1
        found: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        escaped_key = project_key.replace('"', '\\"')
        jql = f'project = "{escaped_key}" ORDER BY updated DESC'

        while len(found) < issues_per_project:
            remaining = issues_per_project - len(found)
            page_size = min(settings.pagination.search_page_size, remaining)
            result = self.client.get_json(
                settings.issue_search_path,
                params={
                    "jql": jql,
                    "startAt": start_at,
                    "maxResults": page_size,
                    "fields": "*all",
                    "expand": "names,schema",
                },
            )
            artifact = self.raw_store.save_json(
                (
                    f"runs/{safe_component(run_id)}/projects/{safe_component(project_key)}"
                    f"/issue_search/page_{page_number:04d}.json"
                ),
                result.payload,
            )
            self.state.record_artifact(
                run_id=run_id,
                project_key=project_key,
                issue_key=None,
                artifact_type="issue_search_page",
                relative_path=artifact.relative_path,
                content_hash=artifact.content_sha256,
                size_bytes=artifact.size_bytes,
            )

            if not isinstance(result.payload, dict):
                raise ValueError("이슈 검색 응답이 객체가 아닙니다.")
            raw_issues = result.payload.get("issues", [])
            if not isinstance(raw_issues, list):
                raise ValueError("이슈 검색 응답의 issues가 배열이 아닙니다.")

            for item in raw_issues:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "")
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    found.append(item)
                    if len(found) >= issues_per_project:
                        break

            total = int(result.payload.get("total", start_at + len(raw_issues)))
            if not raw_issues or start_at + len(raw_issues) >= total:
                break
            start_at += len(raw_issues)
            page_number += 1

        return found

    def _collect_issue(self, run_id: str, project_key: str, issue_key: str) -> None:
        settings = self.client.settings
        path = settings.issue_path.format(issue_key=issue_key)
        result = self.client.get_json(
            path,
            params={"fields": "*all", "expand": "names,schema,renderedFields"},
        )
        artifact = self.raw_store.save_json(
            (
                f"runs/{safe_component(run_id)}/projects/{safe_component(project_key)}"
                f"/issues/{safe_component(issue_key)}/issue.json"
            ),
            result.payload,
        )
        jira_updated_at = self._jira_updated_at(result.payload)
        self.state.record_artifact(
            run_id=run_id,
            project_key=project_key,
            issue_key=issue_key,
            artifact_type="issue",
            relative_path=artifact.relative_path,
            content_hash=artifact.content_sha256,
            size_bytes=artifact.size_bytes,
            jira_updated_at=jira_updated_at,
        )

        if settings.collection.collect_comments:
            self._collect_missing_comment_pages(run_id, project_key, issue_key, result.payload)

    def _collect_missing_comment_pages(
        self,
        run_id: str,
        project_key: str,
        issue_key: str,
        issue_payload: Any,
    ) -> None:
        settings = self.client.settings
        embedded_start = 0
        embedded_count = 0
        embedded_total: int | None = None

        if isinstance(issue_payload, dict):
            fields = issue_payload.get("fields")
            if isinstance(fields, dict):
                comment = fields.get("comment")
                if isinstance(comment, dict):
                    comments = comment.get("comments", [])
                    if isinstance(comments, list):
                        embedded_count = len(comments)
                    embedded_start = int(comment.get("startAt", 0))
                    embedded_total = int(comment.get("total", embedded_count))

        if embedded_total is not None and embedded_start == 0 and embedded_count >= embedded_total:
            return

        start_at = embedded_count if embedded_start == 0 else 0
        page_number = 1
        while True:
            result = self.client.get_json(
                settings.comment_path.format(issue_key=issue_key),
                params={
                    "startAt": start_at,
                    "maxResults": settings.pagination.comment_page_size,
                },
            )
            artifact = self.raw_store.save_json(
                (
                    f"runs/{safe_component(run_id)}/projects/{safe_component(project_key)}"
                    f"/issues/{safe_component(issue_key)}/comments/page_{page_number:04d}.json"
                ),
                result.payload,
            )
            self.state.record_artifact(
                run_id=run_id,
                project_key=project_key,
                issue_key=issue_key,
                artifact_type="comment_page",
                relative_path=artifact.relative_path,
                content_hash=artifact.content_sha256,
                size_bytes=artifact.size_bytes,
            )

            if not isinstance(result.payload, dict):
                raise ValueError("댓글 응답이 객체가 아닙니다.")
            comments = result.payload.get("comments", [])
            if not isinstance(comments, list):
                raise ValueError("댓글 응답의 comments가 배열이 아닙니다.")
            page_start = int(result.payload.get("startAt", start_at))
            total = int(result.payload.get("total", page_start + len(comments)))
            if not comments or page_start + len(comments) >= total:
                break
            start_at = page_start + len(comments)
            page_number += 1

    @staticmethod
    def _jira_updated_at(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            return None
        updated = fields.get("updated")
        return str(updated) if updated is not None else None
