from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class StateStore:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS collection_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    issues_per_project INTEGER NOT NULL,
                    project_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS project_runs (
                    run_id TEXT NOT NULL,
                    project_key TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_count INTEGER NOT NULL,
                    collected_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    error_message TEXT,
                    PRIMARY KEY (run_id, project_key),
                    FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    project_key TEXT,
                    issue_key TEXT,
                    artifact_type TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    collected_at TEXT NOT NULL,
                    jira_updated_at TEXT,
                    UNIQUE(run_id, artifact_type, relative_path),
                    FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS issue_checkpoints (
                    run_id TEXT NOT NULL,
                    project_key TEXT NOT NULL,
                    issue_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT,
                    PRIMARY KEY (run_id, project_key, issue_key),
                    FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_run
                    ON artifacts(run_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_issue
                    ON artifacts(run_id, project_key, issue_key);
                """
            )

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
        if failure_count or unfinished_count:
            status = "partial"
        else:
            status = "completed"

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
