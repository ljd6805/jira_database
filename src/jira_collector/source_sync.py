from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .exporter.atomic_writer import AtomicTextWriter
from .jira_client import JiraClient
from .knowledge_input import IssueKnowledgeInputBuilder
from .parser import CommentParser, IssueParser, IssueSource, IssueStructureParser
from .project_discovery import _project_items
from .raw_store import RawStore, safe_component
from .state_store import StateStore

LOGGER = logging.getLogger(__name__)

_OVERLAP = timedelta(minutes=5)
_SERVER_INFO_PATH = "/serverInfo"


class SourceSyncError(RuntimeError):
    """Continuous Source Sync의 안전 계약을 만족할 수 없을 때 발생합니다."""


class SourceMaterializationError(SourceSyncError):
    """한 Issue의 RAW/정제/Knowledge Input을 안전하게 만들지 못한 오류입니다."""


@dataclass(frozen=True)
class DiscoveredProject:
    project_id: str
    key: str
    name: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class CandidateStub:
    jira_id: str
    issue_key: str
    updated_at: str


@dataclass(frozen=True)
class MaterializedCandidate:
    jira_id: str
    issue_key: str
    jira_updated_at: str | None
    source_hash: str
    source_hash_profile: str
    package_path: Path
    analysis_path: Path


@dataclass(frozen=True)
class SourceSyncResult:
    source_run_id: str
    status: str
    visible_project_count: int
    source_committed_project_count: int
    failed_project_count: int


class OperationalSourceSync:
    """Loop A: Jira Source를 최신화하고 durable latest-only Work backlog를 생산합니다."""

    def __init__(
        self,
        client: JiraClient,
        raw_store: RawStore,
        state: StateStore,
        *,
        data_root: str | Path | None = None,
    ) -> None:
        self.client = client
        self.raw_store = raw_store
        self.state = state
        self.data_root = Path(data_root or raw_store.data_root).resolve()
        self.analysis_writer = AtomicTextWriter(self.data_root / "analysis")
        self.package_builder = IssueKnowledgeInputBuilder(self.data_root)
        self.issue_parser = IssueParser()
        self.comment_parser = CommentParser()
        self.structure_parser = IssueStructureParser()

    def run(self, *, max_issues_per_project: int | None = None) -> SourceSyncResult:
        """새 Source Run을 Jira server clock 기준 fixed upper로 시작합니다."""

        self._validate_limit(max_issues_per_project)
        server_info = self._fetch_server_info()
        server_tz = self._server_timezone(server_info)
        upper_server = self._source_upper_from_server_info(server_info, server_tz)
        upper_utc = self._iso_utc(upper_server)
        source_run_id = self.state.create_source_sync_run(upper_utc)
        self.raw_store.save_json(
            Path("runs") / safe_component(source_run_id) / "server_info.json",
            server_info,
        )
        return self._execute(
            source_run_id,
            server_tz=server_tz,
            max_issues_per_project=max_issues_per_project,
        )

    def resume(
        self,
        source_run_id: str,
        *,
        max_issues_per_project: int | None = None,
    ) -> SourceSyncResult:
        """같은 fixed upper와 cursor를 유지해 중단된 Source Run을 재개합니다."""

        self._validate_limit(max_issues_per_project)
        source_run = self._source_run(source_run_id)
        server_info = self._load_server_info(source_run_id)
        server_tz = self._server_timezone(server_info)
        self._reopen_source_run(source_run_id, source_run)
        return self._execute(
            source_run_id,
            server_tz=server_tz,
            max_issues_per_project=max_issues_per_project,
        )

    def _execute(
        self,
        source_run_id: str,
        *,
        server_tz: tzinfo,
        max_issues_per_project: int | None,
    ) -> SourceSyncResult:
        source_run = self._source_run(source_run_id)
        upper_utc = str(source_run["upper_bound"])

        try:
            projects = self._discovery_stage(source_run_id, upper_utc, server_tz)
        except Exception as exc:
            self.state.finish_source_sync_run(
                source_run_id,
                discovery_status="failed",
                source_status="failed",
                run_status="failed",
                error_summary=str(exc),
            )
            raise

        for project in projects:
            project_run = self._source_project_run(source_run_id, project.project_id)
            if project_run is None:
                raise SourceSyncError(
                    f"Discovery 완료 후 source_project_run이 없습니다: {project.project_id}"
                )
            if project_run["source_status"] == "source_committed":
                continue
            if project_run["source_status"] == "skipped_unavailable":
                continue

            try:
                self._sync_project(
                    source_run_id,
                    project,
                    project_run,
                    server_tz=server_tz,
                    max_issues_per_project=max_issues_per_project,
                )
            except Exception as exc:
                LOGGER.error(
                    "Source Project 실패: project_id=%s key=%s error=%s",
                    project.project_id,
                    project.key,
                    exc,
                )
                self.state.fail_source_project(
                    source_run_id,
                    project.project_id,
                    str(exc),
                )

        source_status, run_status, committed_count, failed_count = self._aggregate_run(
            source_run_id
        )
        self.state.finish_source_sync_run(
            source_run_id,
            discovery_status="completed",
            source_status=source_status,
            run_status=run_status,
        )
        return SourceSyncResult(
            source_run_id=source_run_id,
            status=run_status,
            visible_project_count=len(projects),
            source_committed_project_count=committed_count,
            failed_project_count=failed_count,
        )

    def _discovery_stage(
        self,
        source_run_id: str,
        upper_utc: str,
        server_tz: tzinfo,
    ) -> list[DiscoveredProject]:
        source_run = self._source_run(source_run_id)
        if source_run["discovery_status"] == "completed":
            projects = self._load_discovery_snapshot(source_run_id)
            if not projects:
                return []
            return projects

        projects = self._discover_projects(source_run_id)
        self._save_discovery_snapshot(source_run_id, projects)
        self._apply_discovery_snapshot(
            source_run_id,
            projects,
            upper_utc=upper_utc,
            server_tz=server_tz,
        )
        return projects

    def _discover_projects(self, source_run_id: str) -> list[DiscoveredProject]:
        settings = self.client.settings
        start_at = 0
        page_number = 1
        found: dict[str, DiscoveredProject] = {}

        while True:
            result = self.client.get_json(
                settings.project_list_path,
                params={
                    "startAt": start_at,
                    "maxResults": settings.pagination.project_page_size,
                },
            )
            self.raw_store.save_json(
                Path("runs")
                / safe_component(source_run_id)
                / "project_discovery"
                / f"page_{page_number:04d}.json",
                result.payload,
            )
            items, is_last, total = _project_items(result.payload)
            for item in items:
                project_id = str(item.get("id") or "").strip()
                key = str(item.get("key") or "").strip()
                if not project_id or not key:
                    raise SourceSyncError(
                        "Project Discovery 응답에 authoritative id 또는 key가 없습니다."
                    )
                name = str(item.get("name") or key)
                existing = found.get(project_id)
                if existing is not None and existing.key != key:
                    raise SourceSyncError(
                        f"같은 project_id가 서로 다른 key로 발견됐습니다: {project_id}"
                    )
                found[project_id] = DiscoveredProject(
                    project_id=project_id,
                    key=key,
                    name=name,
                    raw=item,
                )

            if is_last:
                break
            if not items:
                raise SourceSyncError("Project Discovery pagination이 완료 전에 멈췄습니다.")
            start_at += len(items)
            if start_at >= total:
                break
            page_number += 1

        return sorted(found.values(), key=lambda item: (item.key, item.project_id))

    def _save_discovery_snapshot(
        self,
        source_run_id: str,
        projects: list[DiscoveredProject],
    ) -> None:
        self.raw_store.save_json(
            Path("runs")
            / safe_component(source_run_id)
            / "project_discovery"
            / "snapshot.json",
            {
                "source_run_id": source_run_id,
                "status": "completed",
                "projects": [
                    {
                        "project_id": item.project_id,
                        "key": item.key,
                        "name": item.name,
                        "raw": item.raw,
                    }
                    for item in projects
                ],
            },
        )

    def _load_discovery_snapshot(self, source_run_id: str) -> list[DiscoveredProject]:
        path = (
            self.raw_store.raw_root
            / "runs"
            / safe_component(source_run_id)
            / "project_discovery"
            / "snapshot.json"
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SourceSyncError(
                f"완료된 Discovery snapshot을 읽을 수 없습니다: {path}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("status") != "completed":
            raise SourceSyncError(f"Discovery snapshot 구조가 잘못됐습니다: {path}")
        rows = payload.get("projects")
        if not isinstance(rows, list):
            raise SourceSyncError(f"Discovery snapshot projects가 배열이 아닙니다: {path}")

        projects: list[DiscoveredProject] = []
        for row in rows:
            if not isinstance(row, dict):
                raise SourceSyncError(f"Discovery snapshot Project가 객체가 아닙니다: {path}")
            project_id = str(row.get("project_id") or "").strip()
            key = str(row.get("key") or "").strip()
            if not project_id or not key:
                raise SourceSyncError(f"Discovery snapshot Project identity가 비었습니다: {path}")
            raw = row.get("raw")
            projects.append(
                DiscoveredProject(
                    project_id=project_id,
                    key=key,
                    name=str(row.get("name") or key),
                    raw=raw if isinstance(raw, dict) else {},
                )
            )
        return sorted(projects, key=lambda item: (item.key, item.project_id))

    def _apply_discovery_snapshot(
        self,
        source_run_id: str,
        projects: list[DiscoveredProject],
        *,
        upper_utc: str,
        server_tz: tzinfo,
    ) -> None:
        """완전한 Discovery 결과를 Registry + Project Run에 한 Transaction으로 반영합니다."""

        observed_at = datetime.now(timezone.utc).isoformat()
        visible_ids = {item.project_id for item in projects}
        with self.state.connect() as connection:
            prior_rows = connection.execute("SELECT * FROM project_state").fetchall()
            prior = {str(row["project_id"]): dict(row) for row in prior_rows}

            for item in projects:
                previous = prior.get(item.project_id)
                previous_watermark = (
                    str(previous["committed_watermark"])
                    if previous and previous.get("committed_watermark")
                    else None
                )
                previous_visibility = (
                    str(previous["visibility_state"]) if previous else None
                )

                if previous_watermark is None:
                    operation_kind = "initial_ingest"
                    lower_utc = None
                else:
                    operation_kind = (
                        "catchup" if previous_visibility == "unavailable" else "delta"
                    )
                    lower_utc = self._subtract_overlap(previous_watermark)

                connection.execute(
                    """
                    INSERT INTO project_state(
                        project_id, current_key, current_name, visibility_state,
                        first_seen_source_run_id, last_seen_source_run_id,
                        last_seen_at, unavailable_since
                    ) VALUES (?, ?, ?, 'visible', ?, ?, ?, NULL)
                    ON CONFLICT(project_id) DO UPDATE SET
                        current_key = excluded.current_key,
                        current_name = excluded.current_name,
                        visibility_state = 'visible',
                        last_seen_source_run_id = excluded.last_seen_source_run_id,
                        last_seen_at = excluded.last_seen_at,
                        unavailable_since = NULL
                    """,
                    (
                        item.project_id,
                        item.key,
                        item.name,
                        source_run_id,
                        source_run_id,
                        observed_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO source_project_run(
                        source_run_id, project_id, operation_kind,
                        lower_bound, upper_bound, source_status
                    ) VALUES (?, ?, ?, ?, ?, 'pending')
                    ON CONFLICT(source_run_id, project_id) DO NOTHING
                    """,
                    (
                        source_run_id,
                        item.project_id,
                        operation_kind,
                        lower_utc,
                        upper_utc,
                    ),
                )

            for project_id, previous in prior.items():
                if project_id in visible_ids:
                    continue
                unavailable_since = previous.get("unavailable_since") or observed_at
                connection.execute(
                    """
                    UPDATE project_state
                    SET visibility_state = 'unavailable',
                        unavailable_since = ?
                    WHERE project_id = ?
                    """,
                    (unavailable_since, project_id),
                )
                connection.execute(
                    """
                    INSERT INTO source_project_run(
                        source_run_id, project_id, operation_kind, lower_bound,
                        upper_bound, source_status, started_at, finished_at
                    ) VALUES (?, ?, 'skip_unavailable', NULL, ?, 'skipped_unavailable', ?, ?)
                    ON CONFLICT(source_run_id, project_id) DO NOTHING
                    """,
                    (
                        source_run_id,
                        project_id,
                        upper_utc,
                        observed_at,
                        observed_at,
                    ),
                )

            connection.execute(
                """
                UPDATE source_sync_run
                SET discovery_status = 'completed', source_status = 'running',
                    error_summary = NULL
                WHERE source_run_id = ?
                """,
                (source_run_id,),
            )

    def _sync_project(
        self,
        source_run_id: str,
        project: DiscoveredProject,
        project_run: dict[str, object],
        *,
        server_tz: tzinfo,
        max_issues_per_project: int | None,
    ) -> None:
        operation_kind = str(project_run["operation_kind"])
        lower_utc = (
            str(project_run["lower_bound"])
            if project_run.get("lower_bound") is not None
            else None
        )
        upper_utc = str(project_run["upper_bound"])
        self.state.start_source_project_run(
            source_run_id=source_run_id,
            project_id=project.project_id,
            operation_kind=operation_kind,
            lower_bound=lower_utc,
            upper_bound=upper_utc,
        )

        refreshed_run = self._source_project_run(source_run_id, project.project_id)
        assert refreshed_run is not None
        cursor = self._cursor_key(
            refreshed_run.get("cursor_updated_at"),
            refreshed_run.get("cursor_jira_id"),
        )
        candidates = self._search_candidates(
            source_run_id,
            project,
            lower_utc=lower_utc,
            upper_utc=upper_utc,
            server_tz=server_tz,
            max_issues=max_issues_per_project,
        )

        for candidate in candidates:
            candidate_key = self._candidate_key(candidate.updated_at, candidate.jira_id)
            if cursor is not None and candidate_key <= cursor:
                continue

            materialized = self._materialize_candidate(
                source_run_id,
                project,
                candidate,
            )
            change_kind = self._classify_candidate(materialized)
            self.state.record_source_candidate(
                source_run_id=source_run_id,
                project_id=project.project_id,
                jira_id=materialized.jira_id,
                observed_issue_key=materialized.issue_key,
                jira_updated_at=materialized.jira_updated_at,
                cursor_updated_at=candidate.updated_at,
                cursor_jira_id=candidate.jira_id,
                change_kind=change_kind,
                source_hash=(
                    materialized.source_hash if change_kind != "unchanged" else None
                ),
                source_hash_profile=materialized.source_hash_profile,
            )
            cursor = candidate_key

        self.state.commit_source_project(source_run_id, project.project_id)

    def _search_candidates(
        self,
        source_run_id: str,
        project: DiscoveredProject,
        *,
        lower_utc: str | None,
        upper_utc: str,
        server_tz: tzinfo,
        max_issues: int | None,
    ) -> list[CandidateStub]:
        settings = self.client.settings
        jql = self._delta_jql(
            project.key,
            lower_utc=lower_utc,
            upper_utc=upper_utc,
            server_tz=server_tz,
        )
        start_at = 0
        page_number = 1
        found: dict[str, CandidateStub] = {}

        while max_issues is None or len(found) < max_issues:
            page_size = settings.pagination.search_page_size
            if max_issues is not None:
                page_size = min(page_size, max_issues - len(found))
                if page_size <= 0:
                    break
            result = self.client.get_json(
                settings.issue_search_path,
                params={
                    "jql": jql,
                    "startAt": start_at,
                    "maxResults": page_size,
                    "fields": "updated",
                },
            )
            self.raw_store.save_json(
                Path("runs")
                / safe_component(source_run_id)
                / "projects"
                / safe_component(project.key)
                / "issue_search"
                / f"page_{page_number:04d}.json",
                result.payload,
            )
            if not isinstance(result.payload, dict):
                raise SourceSyncError("Issue search 응답이 객체가 아닙니다.")
            rows = result.payload.get("issues")
            if not isinstance(rows, list):
                raise SourceSyncError("Issue search issues가 배열이 아닙니다.")

            for row in rows:
                if not isinstance(row, dict):
                    raise SourceSyncError("Issue search 항목이 객체가 아닙니다.")
                jira_id = str(row.get("id") or "").strip()
                issue_key = str(row.get("key") or "").strip()
                fields = row.get("fields")
                updated_at = (
                    str(fields.get("updated") or "").strip()
                    if isinstance(fields, dict)
                    else ""
                )
                if not jira_id or not issue_key or not updated_at:
                    raise SourceSyncError(
                        "Delta candidate에 id/key/fields.updated가 모두 필요합니다."
                    )
                found[jira_id] = CandidateStub(
                    jira_id=jira_id,
                    issue_key=issue_key,
                    updated_at=updated_at,
                )
                if max_issues is not None and len(found) >= max_issues:
                    break

            total = int(result.payload.get("total", start_at + len(rows)))
            if not rows or start_at + len(rows) >= total:
                break
            start_at += len(rows)
            page_number += 1

        return sorted(
            found.values(),
            key=lambda item: self._candidate_key(item.updated_at, item.jira_id),
        )

    def _materialize_candidate(
        self,
        source_run_id: str,
        project: DiscoveredProject,
        candidate: CandidateStub,
    ) -> MaterializedCandidate:
        settings = self.client.settings
        issue_result = self.client.get_json(
            settings.issue_path.format(issue_key=candidate.issue_key),
            params={"fields": "*all", "expand": "names,schema,renderedFields"},
        )
        if not isinstance(issue_result.payload, dict):
            raise SourceMaterializationError("Issue detail 응답이 객체가 아닙니다.")

        issue_relative = (
            Path("runs")
            / safe_component(source_run_id)
            / "projects"
            / safe_component(project.key)
            / "issues"
            / safe_component(candidate.issue_key)
        )
        issue_artifact = self.raw_store.save_json(
            issue_relative / "issue.json",
            issue_result.payload,
        )
        comments_dir = self.raw_store.raw_root / issue_relative / "comments"
        if settings.collection.collect_comments:
            self._collect_comment_pages(
                source_run_id,
                project.key,
                candidate.issue_key,
                issue_relative,
            )
        else:
            self.raw_store.save_json(
                issue_relative / "comments" / "page_0001.json",
                {"startAt": 0, "maxResults": 0, "total": 0, "comments": []},
            )

        source = IssueSource(
            run_id=source_run_id,
            project_key=project.key,
            issue_key=candidate.issue_key,
            issue_path=self.data_root / issue_artifact.relative_path,
            comments_dir=comments_dir,
        )
        issue_parse = self.issue_parser.parse_payload(issue_result.payload, source)
        comment_parse = self.comment_parser.parse_issue(source)
        structure_parse = self.structure_parser.parse_payload(issue_result.payload, source)
        self._assert_materialization_complete(comment_parse, structure_parse)

        issue_doc = asdict(issue_parse.record)
        comment_docs = [asdict(row) for row in comment_parse.records]
        attachment_docs = [asdict(row) for row in structure_parse.attachments]
        relationship_docs = [
            self._relationship_view(asdict(row), candidate.issue_key)
            for row in structure_parse.relationships
        ]
        catalog = {
            row.field_id: asdict(row)
            for row in structure_parse.custom_field_definitions
        }
        custom_values = [asdict(row) for row in structure_parse.custom_field_values]
        package_warnings: list[dict[str, Any]] = []
        package = self.package_builder._package(
            source_run_id,
            issue_doc,
            comment_docs,
            attachment_docs,
            relationship_docs,
            custom_values,
            catalog,
            self.package_builder._utc_now(),
            package_warnings,
        )

        detail_jira_id = str(issue_doc.get("jira_id") or "").strip()
        detail_issue_key = str(issue_doc.get("issue_key") or "").strip()
        if detail_jira_id != candidate.jira_id or detail_issue_key != candidate.issue_key:
            raise SourceMaterializationError(
                "Search candidate와 detail payload의 Jira identity가 다릅니다."
            )

        warnings = [
            *[asdict(item) for item in issue_parse.warnings],
            *[asdict(item) for item in comment_parse.warnings],
            *[asdict(item) for item in structure_parse.attachment_warnings],
            *[asdict(item) for item in structure_parse.relationship_warnings],
            *[asdict(item) for item in structure_parse.custom_field_warnings],
            *package_warnings,
        ]
        analysis_relative = (
            Path(source_run_id)
            / "projects"
            / safe_component(project.key)
            / "issues"
            / safe_component(candidate.issue_key)
            / "analysis.json"
        )
        analysis_path = self.analysis_writer.write_text(
            analysis_relative,
            json.dumps(
                {
                    "source_run_id": source_run_id,
                    "project_id": project.project_id,
                    "project_key": project.key,
                    "issue": issue_doc,
                    "comments": comment_docs,
                    "attachments": attachment_docs,
                    "relationships": relationship_docs,
                    "custom_field_catalog": catalog,
                    "custom_fields": custom_values,
                    "warnings": warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        package_relative = (
            Path(source_run_id) / "issues" / f"{safe_component(candidate.issue_key)}.json"
        )
        package_path = self.package_builder.writer.write_text(
            package_relative,
            json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        )
        return MaterializedCandidate(
            jira_id=detail_jira_id,
            issue_key=detail_issue_key,
            jira_updated_at=(
                str(issue_doc.get("updated_at"))
                if issue_doc.get("updated_at") is not None
                else None
            ),
            source_hash=str(package["source_hash"]),
            source_hash_profile=str(package["source_hash_profile"]),
            package_path=package_path,
            analysis_path=analysis_path,
        )

    def _collect_comment_pages(
        self,
        source_run_id: str,
        project_key: str,
        issue_key: str,
        issue_relative: Path,
    ) -> None:
        settings = self.client.settings
        start_at = 0
        page_number = 1
        while True:
            result = self.client.get_json(
                settings.comment_path.format(issue_key=issue_key),
                params={
                    "startAt": start_at,
                    "maxResults": settings.pagination.comment_page_size,
                },
            )
            self.raw_store.save_json(
                issue_relative / "comments" / f"page_{page_number:04d}.json",
                result.payload,
            )
            if not isinstance(result.payload, dict):
                raise SourceMaterializationError("Comment 응답이 객체가 아닙니다.")
            comments = result.payload.get("comments")
            if not isinstance(comments, list):
                raise SourceMaterializationError("Comment comments가 배열이 아닙니다.")
            page_start = int(result.payload.get("startAt", start_at))
            total = int(result.payload.get("total", page_start + len(comments)))
            next_start = page_start + len(comments)
            if not comments or next_start >= total:
                break
            if next_start <= start_at:
                raise SourceMaterializationError(
                    f"Comment pagination이 진행되지 않습니다: {project_key}/{issue_key}"
                )
            start_at = next_start
            page_number += 1

    @staticmethod
    def _assert_materialization_complete(comment_parse: Any, structure_parse: Any) -> None:
        failures = (
            int(comment_parse.failed_page_count)
            + int(comment_parse.failed_comment_count)
            + int(comment_parse.missing_comment_source_count)
            + int(structure_parse.failed_attachment_count)
            + int(structure_parse.failed_relationship_count)
            + int(structure_parse.failed_custom_field_value_count)
        )
        if failures:
            raise SourceMaterializationError(
                f"Issue 정제 중 {failures}개의 치명적 하위 레코드 오류가 발생했습니다."
            )

    @staticmethod
    def _relationship_view(row: dict[str, Any], issue_key: str) -> dict[str, Any]:
        source_key = str(row.get("source_issue_key") or "")
        target_key = str(row.get("target_issue_key") or "")
        if issue_key == source_key:
            role = "source"
            other = target_key
        elif issue_key == target_key:
            role = "target"
            other = source_key
        else:
            raise SourceMaterializationError(
                f"현재 Issue가 relationship endpoint에 없습니다: {issue_key}"
            )
        result = dict(row)
        result.update(
            {
                "current_issue_role": role,
                "current_issue_direction": "outgoing" if role == "source" else "incoming",
                "other_issue_key": other,
                # Incremental package scope는 run 순서에 따라 달라질 수 있으므로 source semantics로 사용하지 않습니다.
                "other_package_available": False,
            }
        )
        return result

    def _classify_candidate(self, candidate: MaterializedCandidate) -> str:
        with self.state.connect() as connection:
            row = connection.execute(
                """
                SELECT source_hash, source_hash_profile
                FROM sync_issue_change
                WHERE jira_id = ? AND last_source_committed_run_id IS NOT NULL
                ORDER BY last_source_committed_at DESC, updated_at DESC
                LIMIT 1
                """,
                (candidate.jira_id,),
            ).fetchone()
        if row is None:
            return "new"
        if (
            str(row["source_hash"]) == candidate.source_hash
            and str(row["source_hash_profile"]) == candidate.source_hash_profile
        ):
            return "unchanged"
        return "changed"

    def _aggregate_run(self, source_run_id: str) -> tuple[str, str, int, int]:
        with self.state.connect() as connection:
            rows = connection.execute(
                """
                SELECT source_status
                FROM source_project_run
                WHERE source_run_id = ?
                  AND source_status != 'skipped_unavailable'
                """,
                (source_run_id,),
            ).fetchall()
        statuses = [str(row["source_status"]) for row in rows]
        committed_count = sum(item == "source_committed" for item in statuses)
        failed_count = sum(item in {"partial", "failed"} for item in statuses)
        unfinished_count = sum(item in {"pending", "running"} for item in statuses)
        if failed_count or unfinished_count:
            if committed_count:
                return "partial", "partial", committed_count, failed_count + unfinished_count
            return "failed", "failed", committed_count, failed_count + unfinished_count
        return "completed", "completed", committed_count, 0

    def _source_run(self, source_run_id: str) -> dict[str, object]:
        with self.state.connect() as connection:
            row = connection.execute(
                "SELECT * FROM source_sync_run WHERE source_run_id = ?",
                (source_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"source_run_id를 찾을 수 없습니다: {source_run_id}")
        return dict(row)

    def _source_project_run(
        self,
        source_run_id: str,
        project_id: str,
    ) -> dict[str, object] | None:
        with self.state.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM source_project_run
                WHERE source_run_id = ? AND project_id = ?
                """,
                (source_run_id, project_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def _reopen_source_run(
        self,
        source_run_id: str,
        source_run: dict[str, object],
    ) -> None:
        discovery_status = str(source_run.get("discovery_status") or "pending")
        with self.state.connect() as connection:
            connection.execute(
                """
                UPDATE source_sync_run
                SET finished_at = NULL,
                    source_status = CASE
                        WHEN ? = 'completed' THEN 'running'
                        ELSE 'pending'
                    END,
                    run_status = 'running',
                    error_summary = NULL
                WHERE source_run_id = ?
                """,
                (discovery_status, source_run_id),
            )

    def _fetch_server_info(self) -> dict[str, Any]:
        result = self.client.get_json(_SERVER_INFO_PATH)
        if not isinstance(result.payload, dict):
            raise SourceSyncError("Jira serverInfo 응답이 객체가 아닙니다.")
        return result.payload

    def _load_server_info(self, source_run_id: str) -> dict[str, Any]:
        path = (
            self.raw_store.raw_root
            / "runs"
            / safe_component(source_run_id)
            / "server_info.json"
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SourceSyncError(f"Source Run server_info를 읽을 수 없습니다: {path}") from exc
        if not isinstance(payload, dict):
            raise SourceSyncError("Source Run server_info가 객체가 아닙니다.")
        return payload

    @staticmethod
    def _server_timezone(server_info: dict[str, Any]) -> tzinfo:
        zone_name = str(server_info.get("serverTimeZone") or "").strip()
        if zone_name:
            try:
                return ZoneInfo(zone_name)
            except ZoneInfoNotFoundError:
                LOGGER.warning("알 수 없는 Jira serverTimeZone입니다: %s", zone_name)

        server_time = OperationalSourceSync._parse_datetime(
            str(server_info.get("serverTime") or "")
        )
        if server_time.tzinfo is None:
            raise SourceSyncError("Jira server timezone을 결정할 수 없습니다.")
        LOGGER.warning(
            "Jira serverTimeZone 이름이 없어 serverTime의 fixed offset을 사용합니다."
        )
        return server_time.tzinfo

    @staticmethod
    def _source_upper_from_server_info(
        server_info: dict[str, Any],
        server_tz: tzinfo,
    ) -> datetime:
        server_time = OperationalSourceSync._parse_datetime(
            str(server_info.get("serverTime") or "")
        ).astimezone(server_tz)
        # Jira JQL absolute date/time은 분 단위이므로 upper와 Watermark도 같은 경계로 맞춥니다.
        return server_time.replace(second=0, microsecond=0)

    @staticmethod
    def _delta_jql(
        project_key: str,
        *,
        lower_utc: str | None,
        upper_utc: str,
        server_tz: tzinfo,
    ) -> str:
        escaped_key = project_key.replace('"', '\\"')
        upper = OperationalSourceSync._format_jql_datetime(upper_utc, server_tz)
        clauses = [f'project = "{escaped_key}"']
        if lower_utc is not None:
            lower = OperationalSourceSync._format_jql_datetime(lower_utc, server_tz)
            clauses.append(f'updated >= "{lower}"')
        clauses.append(f'updated < "{upper}"')
        return " AND ".join(clauses) + " ORDER BY updated ASC, id ASC"

    @staticmethod
    def _format_jql_datetime(value: str, server_tz: tzinfo) -> str:
        return OperationalSourceSync._parse_datetime(value).astimezone(server_tz).strftime(
            "%Y-%m-%d %H:%M"
        )

    @staticmethod
    def _subtract_overlap(value: str) -> str:
        return OperationalSourceSync._iso_utc(
            OperationalSourceSync._parse_datetime(value) - _OVERLAP
        )

    @staticmethod
    def _candidate_key(updated_at: str, jira_id: str) -> tuple[datetime, tuple[int, object]]:
        numeric_id: tuple[int, object]
        if jira_id.isdigit():
            numeric_id = (0, int(jira_id))
        else:
            numeric_id = (1, jira_id)
        return OperationalSourceSync._parse_datetime(updated_at).astimezone(timezone.utc), numeric_id

    @staticmethod
    def _cursor_key(
        updated_at: object,
        jira_id: object,
    ) -> tuple[datetime, tuple[int, object]] | None:
        if updated_at is None and jira_id is None:
            return None
        if updated_at is None or jira_id is None:
            raise SourceSyncError("Source cursor의 updated_at/jira_id 쌍이 깨졌습니다.")
        return OperationalSourceSync._candidate_key(str(updated_at), str(jira_id))

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        text = value.strip()
        if not text:
            raise SourceSyncError("빈 datetime 값은 사용할 수 없습니다.")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise SourceSyncError(f"datetime 형식을 해석할 수 없습니다: {value}") from exc
        if parsed.tzinfo is None:
            raise SourceSyncError(f"timezone이 없는 datetime은 사용할 수 없습니다: {value}")
        return parsed

    @staticmethod
    def _iso_utc(value: datetime) -> str:
        if value.tzinfo is None:
            raise SourceSyncError("timezone이 없는 datetime은 UTC로 저장할 수 없습니다.")
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _validate_limit(value: int | None) -> None:
        if value is not None and value <= 0:
            raise ValueError("max_issues_per_project는 1 이상이어야 합니다.")
