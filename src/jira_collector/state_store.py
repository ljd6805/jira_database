from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .state_schema import STATE_SCHEMA_VERSION, ensure_state_database_v3


LOGGER = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_source_run_id() -> str:
    return f"sr_{uuid.uuid4().hex}"


def new_processing_run_id() -> str:
    return f"pr_{uuid.uuid4().hex}"


def make_work_item_id(
    jira_id: str,
    source_hash: str,
    source_hash_profile: str = "semantic_v2",
) -> str:
    """같은 Jira semantic state가 항상 같은 Work Item ID를 갖게 합니다."""

    payload = json.dumps(
        {
            "jira_id": str(jira_id),
            "source_hash": source_hash,
            "source_hash_profile": source_hash_profile,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sw_{hashlib.sha256(payload).hexdigest()}"


def _log_state_event(event: str, **fields: object) -> None:
    """본문/댓글을 제외한 운영 식별자와 상태만 key=value 형식으로 기록합니다."""

    detail = " ".join(
        f"{key}={value}"
        for key, value in sorted(fields.items())
        if value is not None
    )
    LOGGER.info("state_event=%s%s", event, f" {detail}" if detail else "")


@dataclass(frozen=True)
class ProjectRun:
    run_id: str
    project_key: str
    project_name: str
    status: str
    requested_count: int
    collected_count: int
    error_message: str | None


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: int
    run_id: str
    project_key: str | None
    issue_key: str | None
    artifact_type: str
    relative_path: str
    content_hash: str
    size_bytes: int
    collected_at: str
    jira_updated_at: str | None


@dataclass(frozen=True)
class WorkItemRecord:
    work_item_id: str
    project_id: str
    jira_id: str
    observed_issue_key: str
    source_hash: str
    source_hash_profile: str
    change_kind: str
    last_observed_source_run_id: str
    last_source_committed_run_id: str | None
    last_processing_run_id: str | None
    work_status: str
    knowledge_status: str
    embedding_status: str
    publish_status: str
    superseded_by_work_item_id: str | None


class StateStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        # 새 DB는 v3로 초기화하지만, 기존 legacy DB는 여기서 자동 Migration하지 않습니다.
        ensure_state_database_v3(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @property
    def schema_version(self) -> int:
        with self.connect() as connection:
            row = connection.execute("PRAGMA user_version").fetchone()
            return int(row[0]) if row is not None else 0

    # ------------------------------------------------------------------
    # Legacy Collector State API
    # ------------------------------------------------------------------
    def create_run(self, run_id: str, issues_per_project: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO collection_runs(
                    run_id, started_at, status, issues_per_project
                ) VALUES (?, ?, 'running', ?)
                """,
                (run_id, utc_now_iso(), issues_per_project),
            )

    def run_exists(self, run_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM collection_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            return row is not None

    def add_projects(self, run_id: str, projects: list[tuple[str, str]], requested_count: int) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO project_runs(
                    run_id, project_key, project_name, status, requested_count
                ) VALUES (?, ?, ?, 'pending', ?)
                ON CONFLICT(run_id, project_key) DO NOTHING
                """,
                [(run_id, key, name, requested_count) for key, name in projects],
            )
            connection.execute(
                "UPDATE collection_runs SET project_count = ? WHERE run_id = ?",
                (len(projects), run_id),
            )

    def start_project(self, run_id: str, project_key: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE project_runs
                SET status = 'running', started_at = ?, finished_at = NULL,
                    error_message = NULL
                WHERE run_id = ? AND project_key = ?
                """,
                (utc_now_iso(), run_id, project_key),
            )

    def complete_project(self, run_id: str, project_key: str, collected_count: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE project_runs
                SET status = 'completed', collected_count = ?, finished_at = ?,
                    error_message = NULL
                WHERE run_id = ? AND project_key = ?
                """,
                (collected_count, utc_now_iso(), run_id, project_key),
            )

    def fail_project(
        self,
        run_id: str,
        project_key: str,
        error_message: str,
        *,
        collected_count: int = 0,
    ) -> None:
        status = "partial" if collected_count > 0 else "failed"
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE project_runs
                SET status = ?, collected_count = ?, finished_at = ?, error_message = ?
                WHERE run_id = ? AND project_key = ?
                """,
                (
                    status,
                    collected_count,
                    utc_now_iso(),
                    error_message[:2000],
                    run_id,
                    project_key,
                ),
            )

    def list_projects_for_resume(self, run_id: str, *, include_failed: bool) -> list[ProjectRun]:
        statuses = ["pending", "running"]
        if include_failed:
            statuses.extend(["failed", "partial"])
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT run_id, project_key, project_name, status,
                       requested_count, collected_count, error_message
                FROM project_runs
                WHERE run_id = ? AND status IN ({placeholders})
                ORDER BY project_key
                """,
                [run_id, *statuses],
            ).fetchall()
        return [ProjectRun(**dict(row)) for row in rows]

    def list_all_projects(self, run_id: str) -> list[ProjectRun]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, project_key, project_name, status,
                       requested_count, collected_count, error_message
                FROM project_runs WHERE run_id = ? ORDER BY project_key
                """,
                (run_id,),
            ).fetchall()
        return [ProjectRun(**dict(row)) for row in rows]

    def artifact_exists(self, run_id: str, artifact_type: str, relative_path: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM artifacts
                WHERE run_id = ? AND artifact_type = ? AND relative_path = ?
                """,
                (run_id, artifact_type, relative_path),
            ).fetchone()
            return row is not None

    def record_artifact(
        self,
        *,
        run_id: str,
        project_key: str | None,
        issue_key: str | None,
        artifact_type: str,
        relative_path: str,
        content_hash: str,
        size_bytes: int,
        jira_updated_at: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts(
                    run_id, project_key, issue_key, artifact_type, relative_path,
                    content_hash, size_bytes, collected_at, jira_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, artifact_type, relative_path) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    size_bytes = excluded.size_bytes,
                    collected_at = excluded.collected_at,
                    jira_updated_at = excluded.jira_updated_at
                """,
                (
                    run_id,
                    project_key,
                    issue_key,
                    artifact_type,
                    relative_path,
                    content_hash,
                    size_bytes,
                    utc_now_iso(),
                    jira_updated_at,
                ),
            )

    def start_issue(self, run_id: str, project_key: str, issue_key: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO issue_checkpoints(
                    run_id, project_key, issue_key, status, updated_at, error_message
                ) VALUES (?, ?, ?, 'running', ?, NULL)
                ON CONFLICT(run_id, project_key, issue_key) DO UPDATE SET
                    status = 'running', updated_at = excluded.updated_at,
                    error_message = NULL
                """,
                (run_id, project_key, issue_key, utc_now_iso()),
            )

    def complete_issue(self, run_id: str, project_key: str, issue_key: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO issue_checkpoints(
                    run_id, project_key, issue_key, status, updated_at, error_message
                ) VALUES (?, ?, ?, 'completed', ?, NULL)
                ON CONFLICT(run_id, project_key, issue_key) DO UPDATE SET
                    status = 'completed', updated_at = excluded.updated_at,
                    error_message = NULL
                """,
                (run_id, project_key, issue_key, utc_now_iso()),
            )

    def fail_issue(
        self,
        run_id: str,
        project_key: str,
        issue_key: str,
        error_message: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO issue_checkpoints(
                    run_id, project_key, issue_key, status, updated_at, error_message
                ) VALUES (?, ?, ?, 'failed', ?, ?)
                ON CONFLICT(run_id, project_key, issue_key) DO UPDATE SET
                    status = 'failed', updated_at = excluded.updated_at,
                    error_message = excluded.error_message
                """,
                (run_id, project_key, issue_key, utc_now_iso(), error_message[:2000]),
            )

    def issue_is_complete(self, run_id: str, project_key: str, issue_key: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM issue_checkpoints
                WHERE run_id = ? AND project_key = ? AND issue_key = ?
                  AND status = 'completed'
                """,
                (run_id, project_key, issue_key),
            ).fetchone()
            return row is not None

    def list_artifacts(self, run_id: str) -> list[ArtifactRecord]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT artifact_id, run_id, project_key, issue_key, artifact_type,
                       relative_path, content_hash, size_bytes, collected_at,
                       jira_updated_at
                FROM artifacts WHERE run_id = ? ORDER BY artifact_id
                """,
                (run_id,),
            ).fetchall()
        return [ArtifactRecord(**dict(row)) for row in rows]

    def finish_run(self, run_id: str) -> str:
        projects = self.list_all_projects(run_id)
        success_count = sum(item.status == "completed" for item in projects)
        failure_count = sum(item.status in {"failed", "partial"} for item in projects)
        unfinished_count = len(projects) - success_count - failure_count
        status = "partial" if failure_count or unfinished_count else "completed"

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE collection_runs
                SET finished_at = ?, status = ?, success_count = ?, failure_count = ?
                WHERE run_id = ?
                """,
                (utc_now_iso(), status, success_count, failure_count, run_id),
            )
        return status

    def get_run_summary(self, run_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM collection_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"run_id를 찾을 수 없습니다: {run_id}")
        return dict(row)

    # ------------------------------------------------------------------
    # Loop A · Source Sync State API
    # ------------------------------------------------------------------
    def create_source_sync_run(
        self,
        upper_bound: str,
        *,
        source_run_id: str | None = None,
    ) -> str:
        run_id = source_run_id or new_source_run_id()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_sync_run(
                    source_run_id, started_at, upper_bound,
                    discovery_status, source_status, run_status
                ) VALUES (?, ?, ?, 'pending', 'pending', 'running')
                """,
                (run_id, utc_now_iso(), upper_bound),
            )
        return run_id

    def finish_source_sync_run(
        self,
        source_run_id: str,
        *,
        discovery_status: str,
        source_status: str,
        run_status: str,
        error_summary: str | None = None,
    ) -> None:
        if run_status not in {"completed", "partial", "failed"}:
            raise ValueError("finish_source_sync_run의 run_status는 terminal 상태여야 합니다.")
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE source_sync_run
                SET finished_at = ?, discovery_status = ?, source_status = ?,
                    run_status = ?, error_summary = ?
                WHERE source_run_id = ?
                """,
                (
                    utc_now_iso(),
                    discovery_status,
                    source_status,
                    run_status,
                    error_summary[:2000] if error_summary else None,
                    source_run_id,
                ),
            )

    def upsert_visible_project(
        self,
        *,
        source_run_id: str,
        project_id: str,
        project_key: str,
        project_name: str,
        seen_at: str | None = None,
    ) -> None:
        observed_at = seen_at or utc_now_iso()
        with self.connect() as connection:
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
                    project_id,
                    project_key,
                    project_name,
                    source_run_id,
                    source_run_id,
                    observed_at,
                ),
            )

    def mark_project_unavailable(
        self,
        project_id: str,
        *,
        unavailable_at: str | None = None,
    ) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE project_state
                SET visibility_state = 'unavailable',
                    unavailable_since = COALESCE(unavailable_since, ?)
                WHERE project_id = ?
                """,
                (unavailable_at or utc_now_iso(), project_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"project_id를 찾을 수 없습니다: {project_id}")

    def get_project_state(self, project_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM project_state WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"project_id를 찾을 수 없습니다: {project_id}")
            return dict(row)

    def start_source_project_run(
        self,
        *,
        source_run_id: str,
        project_id: str,
        operation_kind: str,
        lower_bound: str | None,
        upper_bound: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_project_run(
                    source_run_id, project_id, operation_kind,
                    lower_bound, upper_bound, source_status, started_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?)
                ON CONFLICT(source_run_id, project_id) DO UPDATE SET
                    source_status = 'running',
                    started_at = COALESCE(source_project_run.started_at, excluded.started_at),
                    finished_at = NULL,
                    error_message = NULL
                """,
                (
                    source_run_id,
                    project_id,
                    operation_kind,
                    lower_bound,
                    upper_bound,
                    utc_now_iso(),
                ),
            )

    def record_source_candidate(
        self,
        *,
        source_run_id: str,
        project_id: str,
        jira_id: str,
        observed_issue_key: str,
        jira_updated_at: str | None,
        cursor_updated_at: str,
        cursor_jira_id: str,
        change_kind: str,
        source_hash: str | None = None,
        source_hash_profile: str = "semantic_v2",
    ) -> str | None:
        if change_kind not in {"new", "changed", "unchanged"}:
            raise ValueError(f"지원하지 않는 change_kind: {change_kind}")
        if change_kind != "unchanged" and not source_hash:
            raise ValueError("NEW/CHANGED candidate에는 source_hash가 필요합니다.")

        work_item_id = (
            make_work_item_id(jira_id, source_hash or "", source_hash_profile)
            if change_kind != "unchanged"
            else None
        )
        observed_at = utc_now_iso()
        with self.connect() as connection:
            project_run = connection.execute(
                """
                SELECT cursor_updated_at, cursor_jira_id
                FROM source_project_run
                WHERE source_run_id = ? AND project_id = ?
                """,
                (source_run_id, project_id),
            ).fetchone()
            if project_run is None:
                raise KeyError(
                    f"source_project_run을 찾을 수 없습니다: {source_run_id}/{project_id}"
                )

            # 같은 cursor를 다시 호출하는 Resume replay는 count를 중복 증가시키지 않습니다.
            if (
                project_run["cursor_updated_at"] == cursor_updated_at
                and project_run["cursor_jira_id"] == cursor_jira_id
            ):
                return work_item_id

            if work_item_id is not None:
                connection.execute(
                    """
                    INSERT INTO sync_issue_change(
                        work_item_id, project_id, jira_id, observed_issue_key,
                        jira_updated_at, source_hash, source_hash_profile, change_kind,
                        first_discovered_source_run_id, last_observed_source_run_id,
                        last_observed_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(work_item_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        observed_issue_key = excluded.observed_issue_key,
                        jira_updated_at = excluded.jira_updated_at,
                        last_observed_source_run_id = excluded.last_observed_source_run_id,
                        last_observed_at = excluded.last_observed_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        work_item_id,
                        project_id,
                        jira_id,
                        observed_issue_key,
                        jira_updated_at,
                        source_hash,
                        source_hash_profile,
                        change_kind,
                        source_run_id,
                        source_run_id,
                        observed_at,
                        observed_at,
                        observed_at,
                    ),
                )

            count_column = {
                "new": "new_count",
                "changed": "changed_count",
                "unchanged": "unchanged_count",
            }[change_kind]
            connection.execute(
                f"""
                UPDATE source_project_run
                SET candidate_count = candidate_count + 1,
                    {count_column} = {count_column} + 1,
                    cursor_updated_at = ?,
                    cursor_jira_id = ?
                WHERE source_run_id = ? AND project_id = ?
                """,
                (cursor_updated_at, cursor_jira_id, source_run_id, project_id),
            )
        return work_item_id

    def commit_source_project(self, source_run_id: str, project_id: str) -> None:
        """Source Commit, Watermark, Ready Gate, supersede를 한 Transaction으로 확정합니다."""

        committed_at = utc_now_iso()
        with self.connect() as connection:
            project_run = connection.execute(
                """
                SELECT upper_bound, candidate_count, new_count, changed_count, unchanged_count
                FROM source_project_run
                WHERE source_run_id = ? AND project_id = ?
                """,
                (source_run_id, project_id),
            ).fetchone()
            if project_run is None:
                raise KeyError(
                    f"source_project_run을 찾을 수 없습니다: {source_run_id}/{project_id}"
                )

            current_rows = connection.execute(
                """
                SELECT work_item_id, jira_id, work_status,
                       knowledge_status, embedding_status, publish_status
                FROM sync_issue_change
                WHERE project_id = ? AND last_observed_source_run_id = ?
                ORDER BY jira_id, work_item_id
                """,
                (project_id, source_run_id),
            ).fetchall()

            for row in current_rows:
                current_work_id = str(row["work_item_id"])
                jira_id = str(row["jira_id"])
                prior_status = str(row["work_status"])

                superseded_rows = connection.execute(
                    """
                    SELECT work_item_id, work_status
                    FROM sync_issue_change
                    WHERE jira_id = ? AND work_item_id != ?
                      AND work_status IN ('pending','failed','running')
                    ORDER BY created_at, work_item_id
                    """,
                    (jira_id, current_work_id),
                ).fetchall()

                # 과거 semantic state가 다시 최신이 되면 Work를 재활성화합니다.
                # 이미 Knowledge/Embedding이 있던 published state는 Publish만 다시 수행합니다.
                connection.execute(
                    """
                    UPDATE sync_issue_change
                    SET last_source_committed_run_id = ?,
                        last_source_committed_at = ?,
                        work_status = CASE
                            WHEN work_status IN ('superseded','published') THEN 'pending'
                            ELSE work_status
                        END,
                        publish_status = CASE
                            WHEN work_status = 'published'
                             AND knowledge_status = 'completed'
                             AND embedding_status = 'completed'
                            THEN 'pending'
                            ELSE publish_status
                        END,
                        superseded_by_work_item_id = NULL,
                        superseded_at = NULL,
                        supersede_reason = NULL,
                        error_stage = CASE
                            WHEN work_status IN ('superseded','published') THEN NULL
                            ELSE error_stage
                        END,
                        error_message = CASE
                            WHEN work_status IN ('superseded','published') THEN NULL
                            ELSE error_message
                        END,
                        updated_at = ?
                    WHERE work_item_id = ?
                    """,
                    (source_run_id, committed_at, committed_at, current_work_id),
                )

                for old_row in superseded_rows:
                    old_work_id = str(old_row["work_item_id"])
                    connection.execute(
                        """
                        UPDATE sync_issue_change
                        SET work_status = 'superseded',
                            superseded_by_work_item_id = ?,
                            superseded_at = ?,
                            supersede_reason = 'newer_source_version',
                            updated_at = ?
                        WHERE work_item_id = ?
                          AND work_status IN ('pending','failed','running')
                        """,
                        (
                            current_work_id,
                            committed_at,
                            committed_at,
                            old_work_id,
                        ),
                    )
                    _log_state_event(
                        "work_item_superseded",
                        jira_id=jira_id,
                        old_work_item_id=old_work_id,
                        new_work_item_id=current_work_id,
                        previous_status=old_row["work_status"],
                        reason="newer_source_version",
                    )

                if prior_status in {"superseded", "published"}:
                    _log_state_event(
                        "work_item_reactivated",
                        jira_id=jira_id,
                        work_item_id=current_work_id,
                        previous_status=prior_status,
                    )

            # 이 UPDATE의 CHECK가 실패하면 아래 Watermark/Ready 변경도 모두 rollback됩니다.
            connection.execute(
                """
                UPDATE source_project_run
                SET source_status = 'source_committed',
                    finished_at = ?,
                    error_message = NULL
                WHERE source_run_id = ? AND project_id = ?
                """,
                (committed_at, source_run_id, project_id),
            )
            connection.execute(
                """
                UPDATE project_state
                SET committed_watermark = ?,
                    last_source_success_run_id = ?,
                    last_source_success_at = ?,
                    last_error = NULL
                WHERE project_id = ?
                """,
                (
                    project_run["upper_bound"],
                    source_run_id,
                    committed_at,
                    project_id,
                ),
            )

    def fail_source_project(
        self,
        source_run_id: str,
        project_id: str,
        error_message: str,
    ) -> None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT candidate_count
                FROM source_project_run
                WHERE source_run_id = ? AND project_id = ?
                """,
                (source_run_id, project_id),
            ).fetchone()
            if row is None:
                raise KeyError(
                    f"source_project_run을 찾을 수 없습니다: {source_run_id}/{project_id}"
                )
            status = "partial" if int(row["candidate_count"]) > 0 else "failed"
            connection.execute(
                """
                UPDATE source_project_run
                SET source_status = ?, finished_at = ?, error_message = ?
                WHERE source_run_id = ? AND project_id = ?
                """,
                (
                    status,
                    utc_now_iso(),
                    error_message[:2000],
                    source_run_id,
                    project_id,
                ),
            )
            connection.execute(
                "UPDATE project_state SET last_error = ? WHERE project_id = ?",
                (error_message[:2000], project_id),
            )

    def skip_unavailable_project(
        self,
        *,
        source_run_id: str,
        project_id: str,
        upper_bound: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_project_run(
                    source_run_id, project_id, operation_kind, lower_bound,
                    upper_bound, source_status, started_at, finished_at
                ) VALUES (?, ?, 'skip_unavailable', NULL, ?, 'skipped_unavailable', ?, ?)
                ON CONFLICT(source_run_id, project_id) DO UPDATE SET
                    source_status = 'skipped_unavailable',
                    finished_at = excluded.finished_at,
                    error_message = NULL
                """,
                (
                    source_run_id,
                    project_id,
                    upper_bound,
                    utc_now_iso(),
                    utc_now_iso(),
                ),
            )

    # ------------------------------------------------------------------
    # Loop B · Knowledge Processing / Publish State API
    # ------------------------------------------------------------------
    def create_processing_run(
        self,
        *,
        selected_count: int = 0,
        backlog_before: int | None = None,
        processing_run_id: str | None = None,
    ) -> str:
        run_id = processing_run_id or new_processing_run_id()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO processing_run(
                    processing_run_id, started_at, run_status,
                    selected_count, backlog_before
                ) VALUES (?, ?, 'running', ?, ?)
                """,
                (run_id, utc_now_iso(), selected_count, backlog_before),
            )
        return run_id

    def finish_processing_run(
        self,
        processing_run_id: str,
        *,
        run_status: str,
        published_count: int,
        failed_count: int,
        superseded_count: int,
        backlog_after: int | None,
        error_summary: str | None = None,
    ) -> None:
        if run_status not in {"completed", "partial", "failed"}:
            raise ValueError("finish_processing_run의 run_status는 terminal 상태여야 합니다.")
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE processing_run
                SET finished_at = ?, run_status = ?,
                    published_count = ?, failed_count = ?, superseded_count = ?,
                    backlog_after = ?, error_summary = ?
                WHERE processing_run_id = ?
                """,
                (
                    utc_now_iso(),
                    run_status,
                    published_count,
                    failed_count,
                    superseded_count,
                    backlog_after,
                    error_summary[:2000] if error_summary else None,
                    processing_run_id,
                ),
            )

    def count_latest_ready_work_items(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM sync_issue_change
                WHERE last_source_committed_run_id IS NOT NULL
                  AND last_source_committed_run_id = last_observed_source_run_id
                  AND work_status IN ('pending','failed')
                  AND superseded_by_work_item_id IS NULL
                """
            ).fetchone()
            return int(row[0]) if row is not None else 0

    def list_latest_ready_work_items(self, *, limit: int = 100) -> list[WorkItemRecord]:
        if limit <= 0:
            raise ValueError("limit은 1 이상이어야 합니다.")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT work_item_id, project_id, jira_id, observed_issue_key,
                       source_hash, source_hash_profile, change_kind,
                       last_observed_source_run_id, last_source_committed_run_id,
                       last_processing_run_id, work_status,
                       knowledge_status, embedding_status, publish_status,
                       superseded_by_work_item_id
                FROM sync_issue_change
                WHERE last_source_committed_run_id IS NOT NULL
                  AND last_source_committed_run_id = last_observed_source_run_id
                  AND work_status IN ('pending','failed')
                  AND superseded_by_work_item_id IS NULL
                ORDER BY last_source_committed_at, created_at, work_item_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [WorkItemRecord(**dict(row)) for row in rows]

    def get_work_item(self, work_item_id: str) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sync_issue_change WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"work_item_id를 찾을 수 없습니다: {work_item_id}")
            return dict(row)

    def claim_work_item(self, work_item_id: str, processing_run_id: str) -> bool:
        """Single Worker용 claim입니다. Multi-worker lease는 아직 도입하지 않습니다."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT jira_id, work_status,
                       last_source_committed_run_id, last_observed_source_run_id
                FROM sync_issue_change
                WHERE work_item_id = ?
                """,
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"work_item_id를 찾을 수 없습니다: {work_item_id}")

            is_ready = (
                row["last_source_committed_run_id"] is not None
                and row["last_source_committed_run_id"]
                == row["last_observed_source_run_id"]
            )
            if row["work_status"] not in {"pending", "failed"} or not is_ready:
                _log_state_event(
                    "processing_skip_superseded",
                    jira_id=row["jira_id"],
                    work_item_id=work_item_id,
                    work_status=row["work_status"],
                )
                return False

            connection.execute(
                """
                UPDATE sync_issue_change
                SET work_status = 'running',
                    last_processing_run_id = ?,
                    updated_at = ?
                WHERE work_item_id = ?
                """,
                (processing_run_id, utc_now_iso(), work_item_id),
            )
            _log_state_event(
                "latest_processing_started",
                jira_id=row["jira_id"],
                work_item_id=work_item_id,
                processing_run_id=processing_run_id,
            )
            return True

    def work_item_is_latest(self, work_item_id: str, *, log_stale: bool = False) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT jira_id, work_status,
                       last_source_committed_run_id, last_observed_source_run_id
                FROM sync_issue_change
                WHERE work_item_id = ?
                """,
                (work_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"work_item_id를 찾을 수 없습니다: {work_item_id}")
            latest = (
                row["work_status"] != "superseded"
                and row["last_source_committed_run_id"] is not None
                and row["last_source_committed_run_id"]
                == row["last_observed_source_run_id"]
            )
            if not latest and log_stale:
                _log_state_event(
                    "stale_inflight_detected",
                    jira_id=row["jira_id"],
                    work_item_id=work_item_id,
                    work_status=row["work_status"],
                )
            return latest

    def mark_knowledge_running(self, work_item_id: str) -> bool:
        return self._mark_stage_running(work_item_id, "knowledge")

    def mark_embedding_running(self, work_item_id: str) -> bool:
        return self._mark_stage_running(work_item_id, "embedding")

    def mark_publish_running(self, work_item_id: str) -> bool:
        return self._mark_stage_running(work_item_id, "publish")

    def _mark_stage_running(self, work_item_id: str, stage: str) -> bool:
        column = {
            "knowledge": "knowledge_status",
            "embedding": "embedding_status",
            "publish": "publish_status",
        }[stage]
        if not self.work_item_is_latest(work_item_id, log_stale=True):
            return False
        with self.connect() as connection:
            connection.execute(
                f"""
                UPDATE sync_issue_change
                SET {column} = 'running', work_status = 'running',
                    error_stage = NULL, error_message = NULL, updated_at = ?
                WHERE work_item_id = ?
                """,
                (utc_now_iso(), work_item_id),
            )
        return True

    def mark_knowledge_completed(
        self,
        work_item_id: str,
        *,
        issue_version_id: str,
        knowledge_generation_id: str,
    ) -> bool:
        if not self.work_item_is_latest(work_item_id, log_stale=True):
            return False
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sync_issue_change
                SET knowledge_status = 'completed',
                    issue_version_id = ?, knowledge_generation_id = ?,
                    error_stage = NULL, error_message = NULL, updated_at = ?
                WHERE work_item_id = ?
                """,
                (
                    issue_version_id,
                    knowledge_generation_id,
                    utc_now_iso(),
                    work_item_id,
                ),
            )
        return True

    def mark_embedding_completed(self, work_item_id: str) -> bool:
        if not self.work_item_is_latest(work_item_id, log_stale=True):
            return False
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sync_issue_change
                SET embedding_status = 'completed',
                    error_stage = NULL, error_message = NULL, updated_at = ?
                WHERE work_item_id = ?
                """,
                (utc_now_iso(), work_item_id),
            )
        return True

    def mark_published(self, work_item_id: str) -> bool:
        if not self.work_item_is_latest(work_item_id, log_stale=True):
            return False
        published_at = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sync_issue_change
                SET publish_status = 'published', work_status = 'published',
                    last_published_at = ?, error_stage = NULL,
                    error_message = NULL, updated_at = ?
                WHERE work_item_id = ?
                """,
                (published_at, published_at, work_item_id),
            )
        return True

    def mark_work_failed(
        self,
        work_item_id: str,
        *,
        stage: str,
        error_message: str,
    ) -> bool:
        column = {
            "knowledge": "knowledge_status",
            "embedding": "embedding_status",
            "publish": "publish_status",
        }.get(stage)
        if column is None:
            raise ValueError(f"지원하지 않는 failure stage: {stage}")
        if not self.work_item_is_latest(work_item_id, log_stale=True):
            return False
        with self.connect() as connection:
            connection.execute(
                f"""
                UPDATE sync_issue_change
                SET {column} = 'failed', work_status = 'failed',
                    error_stage = ?, error_message = ?, updated_at = ?
                WHERE work_item_id = ?
                """,
                (stage, error_message[:2000], utc_now_iso(), work_item_id),
            )
        return True


__all__ = [
    "ArtifactRecord",
    "ProjectRun",
    "STATE_SCHEMA_VERSION",
    "StateStore",
    "WorkItemRecord",
    "make_work_item_id",
    "new_processing_run_id",
    "new_source_run_id",
]
