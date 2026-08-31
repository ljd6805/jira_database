from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


STATE_SCHEMA_VERSION = 3
STATE_MIGRATION_ID = "legacy-to-state-v3"
STATE_INITIALIZATION_ID = "state-v3-initialization"

LEGACY_TABLES = (
    "collection_runs",
    "project_runs",
    "artifacts",
    "issue_checkpoints",
)

OPERATIONAL_TABLES = (
    "source_sync_run",
    "project_state",
    "source_project_run",
    "sync_issue_change",
    "processing_run",
)

MIGRATION_TABLE = "state_schema_migration"


class StateSchemaError(RuntimeError):
    """Operational State DB의 schema/migration 계약 위반입니다."""


class StateMigrationRequiredError(StateSchemaError):
    """알려진 legacy DB가 발견되어 명시적 Migration이 필요합니다."""


class UnknownStateSchemaError(StateSchemaError):
    """자동으로 해석하면 안 되는 알 수 없는 State DB 구조입니다."""


class UnsupportedStateSchemaError(StateSchemaError):
    """현재 코드가 읽거나 쓸 수 없는 State Schema version입니다."""


@dataclass(frozen=True)
class StateSchemaInspection:
    user_version: int
    fingerprint: str
    user_tables: tuple[str, ...]
    is_empty: bool
    is_known_legacy: bool
    is_current: bool


@dataclass(frozen=True)
class StateMigrationResult:
    database_path: Path
    from_version: int
    to_version: int
    migrated: bool
    backup_path: Path | None
    source_fingerprint: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backup_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


LEGACY_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS collection_runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        issues_per_project INTEGER NOT NULL,
        project_count INTEGER NOT NULL DEFAULT 0,
        success_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS issue_checkpoints (
        run_id TEXT NOT NULL,
        project_key TEXT NOT NULL,
        issue_key TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        error_message TEXT,
        PRIMARY KEY (run_id, project_key, issue_key),
        FOREIGN KEY (run_id) REFERENCES collection_runs(run_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_artifacts_issue ON artifacts(run_id, project_key, issue_key)",
)


OPERATIONAL_SCHEMA_V3_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS state_schema_migration (
        migration_id TEXT PRIMARY KEY,
        from_version INTEGER NOT NULL CHECK(from_version >= 0),
        to_version INTEGER NOT NULL CHECK(to_version > from_version),
        applied_at TEXT NOT NULL,
        source_fingerprint TEXT NOT NULL,
        backup_name TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_sync_run (
        source_run_id TEXT PRIMARY KEY
            CHECK(length(source_run_id) = 35 AND substr(source_run_id, 1, 3) = 'sr_'),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        upper_bound TEXT NOT NULL,
        discovery_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(discovery_status IN ('pending','running','completed','failed')),
        source_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(source_status IN ('pending','running','completed','partial','failed')),
        run_status TEXT NOT NULL DEFAULT 'running'
            CHECK(run_status IN ('running','completed','partial','failed')),
        error_summary TEXT,
        CHECK(
            (run_status = 'running' AND finished_at IS NULL)
            OR
            (run_status IN ('completed','partial','failed') AND finished_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS project_state (
        project_id TEXT PRIMARY KEY,
        current_key TEXT NOT NULL CHECK(length(current_key) > 0),
        current_name TEXT NOT NULL,
        visibility_state TEXT NOT NULL
            CHECK(visibility_state IN ('visible','unavailable')),
        first_seen_source_run_id TEXT NOT NULL
            REFERENCES source_sync_run(source_run_id),
        last_seen_source_run_id TEXT NOT NULL
            REFERENCES source_sync_run(source_run_id),
        last_seen_at TEXT NOT NULL,
        unavailable_since TEXT,
        committed_watermark TEXT,
        last_source_success_run_id TEXT
            REFERENCES source_sync_run(source_run_id),
        last_source_success_at TEXT,
        last_error TEXT,
        CHECK(
            (visibility_state = 'visible' AND unavailable_since IS NULL)
            OR
            (visibility_state = 'unavailable' AND unavailable_since IS NOT NULL)
        ),
        CHECK(
            (committed_watermark IS NULL
             AND last_source_success_run_id IS NULL
             AND last_source_success_at IS NULL)
            OR
            (committed_watermark IS NOT NULL
             AND last_source_success_run_id IS NOT NULL
             AND last_source_success_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS source_project_run (
        source_run_id TEXT NOT NULL
            REFERENCES source_sync_run(source_run_id),
        project_id TEXT NOT NULL
            REFERENCES project_state(project_id),
        operation_kind TEXT NOT NULL
            CHECK(operation_kind IN ('initial_ingest','delta','catchup','skip_unavailable')),
        lower_bound TEXT,
        upper_bound TEXT NOT NULL,
        source_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(source_status IN (
                'pending','running','source_committed','partial','failed','skipped_unavailable'
            )),
        started_at TEXT,
        finished_at TEXT,
        candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(candidate_count >= 0),
        new_count INTEGER NOT NULL DEFAULT 0 CHECK(new_count >= 0),
        changed_count INTEGER NOT NULL DEFAULT 0 CHECK(changed_count >= 0),
        unchanged_count INTEGER NOT NULL DEFAULT 0 CHECK(unchanged_count >= 0),
        cursor_updated_at TEXT,
        cursor_jira_id TEXT,
        error_message TEXT,
        PRIMARY KEY(source_run_id, project_id),
        CHECK(
            (cursor_updated_at IS NULL AND cursor_jira_id IS NULL)
            OR
            (cursor_updated_at IS NOT NULL AND cursor_jira_id IS NOT NULL)
        ),
        CHECK(new_count + changed_count + unchanged_count <= candidate_count),
        CHECK(
            source_status != 'source_committed'
            OR new_count + changed_count + unchanged_count = candidate_count
        ),
        CHECK(
            (operation_kind IN ('delta','catchup') AND lower_bound IS NOT NULL)
            OR
            (operation_kind IN ('initial_ingest','skip_unavailable') AND lower_bound IS NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS processing_run (
        processing_run_id TEXT PRIMARY KEY
            CHECK(length(processing_run_id) = 35 AND substr(processing_run_id, 1, 3) = 'pr_'),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        run_status TEXT NOT NULL DEFAULT 'running'
            CHECK(run_status IN ('running','completed','partial','failed')),
        selected_count INTEGER NOT NULL DEFAULT 0 CHECK(selected_count >= 0),
        published_count INTEGER NOT NULL DEFAULT 0 CHECK(published_count >= 0),
        failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
        superseded_count INTEGER NOT NULL DEFAULT 0 CHECK(superseded_count >= 0),
        backlog_before INTEGER CHECK(backlog_before IS NULL OR backlog_before >= 0),
        backlog_after INTEGER CHECK(backlog_after IS NULL OR backlog_after >= 0),
        error_summary TEXT,
        CHECK(published_count + failed_count + superseded_count <= selected_count),
        CHECK(
            (run_status = 'running' AND finished_at IS NULL)
            OR
            (run_status IN ('completed','partial','failed') AND finished_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_issue_change (
        work_item_id TEXT PRIMARY KEY
            CHECK(length(work_item_id) = 67 AND substr(work_item_id, 1, 3) = 'sw_'),
        project_id TEXT NOT NULL REFERENCES project_state(project_id),
        jira_id TEXT NOT NULL,
        observed_issue_key TEXT NOT NULL,
        jira_updated_at TEXT,
        source_hash TEXT NOT NULL CHECK(length(source_hash) > 0),
        source_hash_profile TEXT NOT NULL
            CHECK(source_hash_profile = 'semantic_v2'),
        change_kind TEXT NOT NULL CHECK(change_kind IN ('new','changed')),
        first_discovered_source_run_id TEXT NOT NULL
            REFERENCES source_sync_run(source_run_id),
        last_observed_source_run_id TEXT NOT NULL
            REFERENCES source_sync_run(source_run_id),
        last_source_committed_run_id TEXT
            REFERENCES source_sync_run(source_run_id),
        last_source_committed_at TEXT,
        last_observed_at TEXT NOT NULL,
        work_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(work_status IN ('pending','running','published','failed','superseded')),
        superseded_by_work_item_id TEXT
            REFERENCES sync_issue_change(work_item_id),
        superseded_at TEXT,
        supersede_reason TEXT
            CHECK(supersede_reason IS NULL OR supersede_reason = 'newer_source_version'),
        last_processing_run_id TEXT
            REFERENCES processing_run(processing_run_id),
        issue_version_id TEXT,
        knowledge_generation_id TEXT,
        knowledge_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(knowledge_status IN ('pending','running','completed','failed')),
        embedding_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(embedding_status IN ('pending','running','completed','failed')),
        publish_status TEXT NOT NULL DEFAULT 'pending'
            CHECK(publish_status IN ('pending','running','published','failed')),
        error_stage TEXT
            CHECK(error_stage IS NULL OR error_stage IN ('knowledge','embedding','publish')),
        error_message TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_published_at TEXT,
        UNIQUE(jira_id, source_hash, source_hash_profile),
        CHECK(
            (last_source_committed_run_id IS NULL AND last_source_committed_at IS NULL)
            OR
            (last_source_committed_run_id IS NOT NULL AND last_source_committed_at IS NOT NULL)
        ),
        CHECK(
            (work_status = 'superseded'
             AND superseded_by_work_item_id IS NOT NULL
             AND superseded_at IS NOT NULL
             AND supersede_reason = 'newer_source_version')
            OR
            (work_status != 'superseded'
             AND superseded_by_work_item_id IS NULL
             AND superseded_at IS NULL
             AND supersede_reason IS NULL)
        ),
        CHECK(
            superseded_by_work_item_id IS NULL
            OR superseded_by_work_item_id != work_item_id
        ),
        CHECK(embedding_status = 'pending' OR knowledge_status = 'completed'),
        CHECK(publish_status = 'pending' OR embedding_status = 'completed'),
        CHECK(work_status != 'published' OR publish_status = 'published'),
        CHECK(
            error_stage IS NULL
            OR (error_stage = 'knowledge' AND knowledge_status = 'failed')
            OR (error_stage = 'embedding' AND embedding_status = 'failed')
            OR (error_stage = 'publish' AND publish_status = 'failed')
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_source_sync_run_started_at ON source_sync_run(started_at)",
    "CREATE INDEX IF NOT EXISTS ix_project_state_visibility ON project_state(visibility_state)",
    """
    CREATE INDEX IF NOT EXISTS ix_source_project_run_run_status
        ON source_project_run(source_run_id, source_status)
    """,
    "CREATE INDEX IF NOT EXISTS ix_processing_run_started_at ON processing_run(started_at)",
    """
    CREATE INDEX IF NOT EXISTS ix_sync_issue_change_jira_work_status
        ON sync_issue_change(jira_id, work_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_sync_issue_change_source_ready
        ON sync_issue_change(
            last_source_committed_run_id,
            last_observed_source_run_id,
            work_status
        )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_sync_issue_change_superseded_by
        ON sync_issue_change(superseded_by_work_item_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_sync_issue_change_knowledge_status
        ON sync_issue_change(knowledge_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_sync_issue_change_embedding_status
        ON sync_issue_change(embedding_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_sync_issue_change_publish_status
        ON sync_issue_change(publish_status)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_sync_issue_change_last_processing_run
        ON sync_issue_change(last_processing_run_id)
    """,
)


def _execute_statements(connection: sqlite3.Connection, statements: Iterable[str]) -> None:
    for statement in statements:
        connection.execute(statement)


def _schema_shape(connection: sqlite3.Connection) -> dict[str, Any]:
    """테이블/컬럼/FK/Index 구조만 정규화해 schema fingerprint 재료를 만듭니다."""

    tables = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()
    ]
    shape: dict[str, Any] = {"tables": {}}
    for table in tables:
        quoted = _quote_identifier(table)
        columns = [
            [
                row[1],
                row[2],
                int(row[3]),
                row[4],
                int(row[5]),
            ]
            for row in connection.execute(f"PRAGMA table_info({quoted})").fetchall()
        ]
        foreign_keys = sorted(
            [
                [
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[7],
                ]
                for row in connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
            ]
        )
        indexes: list[list[Any]] = []
        for index_row in connection.execute(f"PRAGMA index_list({quoted})").fetchall():
            index_name = str(index_row[1])
            columns_for_index = [
                info[2]
                for info in connection.execute(
                    f"PRAGMA index_info({_quote_identifier(index_name)})"
                ).fetchall()
            ]
            indexes.append(
                [
                    index_name if str(index_row[3]) == "c" else str(index_row[3]),
                    int(index_row[2]),
                    int(index_row[4]),
                    columns_for_index,
                ]
            )
        shape["tables"][table] = {
            "columns": columns,
            "foreign_keys": foreign_keys,
            "indexes": sorted(indexes, key=lambda item: json.dumps(item, sort_keys=True)),
        }
    return shape


def _fingerprint(connection: sqlite3.Connection) -> str:
    payload = json.dumps(
        _schema_shape(connection),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@lru_cache(maxsize=1)
def _expected_legacy_fingerprint() -> str:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        _execute_statements(connection, LEGACY_SCHEMA_STATEMENTS)
        return _fingerprint(connection)
    finally:
        connection.close()


@lru_cache(maxsize=1)
def _expected_v3_fingerprint() -> str:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        _execute_statements(connection, LEGACY_SCHEMA_STATEMENTS)
        _execute_statements(connection, OPERATIONAL_SCHEMA_V3_STATEMENTS)
        return _fingerprint(connection)
    finally:
        connection.close()


def _user_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row is not None else 0


def inspect_state_database(database_path: Path) -> StateSchemaInspection:
    if not database_path.exists() or database_path.stat().st_size == 0:
        return StateSchemaInspection(
            user_version=0,
            fingerprint="empty",
            user_tables=(),
            is_empty=True,
            is_known_legacy=False,
            is_current=False,
        )

    connection = sqlite3.connect(database_path)
    try:
        tables = tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        )
        fingerprint = _fingerprint(connection)
        version = _user_version(connection)
        return StateSchemaInspection(
            user_version=version,
            fingerprint=fingerprint,
            user_tables=tables,
            is_empty=not tables,
            is_known_legacy=(
                version == 0 and fingerprint == _expected_legacy_fingerprint()
            ),
            is_current=(
                version == STATE_SCHEMA_VERSION
                and fingerprint == _expected_v3_fingerprint()
            ),
        )
    finally:
        connection.close()


def _integrity_check(database_path: Path) -> None:
    connection = sqlite3.connect(database_path)
    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        result = str(row[0]) if row is not None else "missing"
        if result.lower() != "ok":
            raise StateSchemaError(
                f"SQLite integrity_check 실패: {database_path}: {result}"
            )
    finally:
        connection.close()


def _create_fresh_v3_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("BEGIN")
        try:
            _execute_statements(connection, LEGACY_SCHEMA_STATEMENTS)
            _execute_statements(connection, OPERATIONAL_SCHEMA_V3_STATEMENTS)
            connection.execute(
                """
                INSERT INTO state_schema_migration(
                    migration_id, from_version, to_version, applied_at,
                    source_fingerprint, backup_name
                ) VALUES (?, 0, ?, ?, 'empty', NULL)
                """,
                (STATE_INITIALIZATION_ID, STATE_SCHEMA_VERSION, utc_now_iso()),
            )
            connection.execute(f"PRAGMA user_version = {STATE_SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()

    verify_state_schema_v3(database_path)


def ensure_state_database_v3(database_path: Path) -> None:
    """새 DB는 v3로 만들고, 기존 legacy DB는 자동 변경하지 않습니다."""

    inspection = inspect_state_database(database_path)
    if inspection.is_empty:
        _create_fresh_v3_database(database_path)
        return
    if inspection.is_current:
        return
    if inspection.user_version == 0 and inspection.is_known_legacy:
        raise StateMigrationRequiredError(
            "기존 collector.db가 발견되었습니다. 일반 실행에서 자동 Migration하지 않습니다. "
            "먼저 `jira-collector migrate-state`를 실행하세요."
        )
    if inspection.user_version in {1, 2}:
        raise UnsupportedStateSchemaError(
            f"State Schema v{inspection.user_version} DB는 자동 변환하지 않습니다. "
            "v1/v2는 never-deployed baseline이므로 운영자 확인이 필요합니다."
        )
    if inspection.user_version > STATE_SCHEMA_VERSION:
        raise UnsupportedStateSchemaError(
            f"State DB version {inspection.user_version}은 현재 코드의 v{STATE_SCHEMA_VERSION}보다 새 버전입니다."
        )
    raise UnknownStateSchemaError(
        "알 수 없는 State DB 구조입니다. fail-closed 정책에 따라 자동 수정하지 않습니다. "
        f"version={inspection.user_version}, fingerprint={inspection.fingerprint}"
    )


def verify_state_schema_v3(database_path: Path) -> StateSchemaInspection:
    _integrity_check(database_path)
    inspection = inspect_state_database(database_path)
    if inspection.user_version != STATE_SCHEMA_VERSION:
        raise StateSchemaError(
            f"State DB user_version 불일치: expected={STATE_SCHEMA_VERSION}, actual={inspection.user_version}"
        )
    if inspection.fingerprint != _expected_v3_fingerprint():
        raise StateSchemaError(
            "State Schema v3 fingerprint 불일치: "
            f"actual={inspection.fingerprint}"
        )
    return inspection


def _default_backup_path(database_path: Path) -> Path:
    return database_path.with_name(
        f"{database_path.name}.pre-state-v3.{_backup_timestamp()}.bak"
    )


def _backup_database(source_path: Path, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    _integrity_check(backup_path)


def migrate_legacy_state_database(
    database_path: Path,
    *,
    backup_path: Path | None = None,
) -> StateMigrationResult:
    """known legacy collector.db를 명시적으로 State Schema v3로 승격합니다."""

    inspection = inspect_state_database(database_path)
    if inspection.is_current:
        return StateMigrationResult(
            database_path=database_path,
            from_version=STATE_SCHEMA_VERSION,
            to_version=STATE_SCHEMA_VERSION,
            migrated=False,
            backup_path=None,
            source_fingerprint=inspection.fingerprint,
        )
    if inspection.is_empty:
        _create_fresh_v3_database(database_path)
        return StateMigrationResult(
            database_path=database_path,
            from_version=0,
            to_version=STATE_SCHEMA_VERSION,
            migrated=True,
            backup_path=None,
            source_fingerprint="empty",
        )
    if inspection.user_version != 0 or not inspection.is_known_legacy:
        raise UnknownStateSchemaError(
            "명시적 Migration은 known legacy version 0만 허용합니다. "
            f"version={inspection.user_version}, fingerprint={inspection.fingerprint}"
        )

    target_backup = backup_path or _default_backup_path(database_path)
    if target_backup.exists():
        raise StateSchemaError(f"Backup 파일이 이미 존재합니다: {target_backup}")

    # BEGIN IMMEDIATE로 다른 writer를 막은 상태에서 legacy snapshot을 backup합니다.
    guard = sqlite3.connect(database_path, isolation_level=None)
    guard.execute("PRAGMA foreign_keys=ON")
    try:
        guard.execute("BEGIN IMMEDIATE")
        locked_fingerprint = _fingerprint(guard)
        if locked_fingerprint != inspection.fingerprint:
            guard.rollback()
            raise StateSchemaError("Migration 직전 schema fingerprint가 변경되었습니다.")

        _backup_database(database_path, target_backup)
        try:
            _execute_statements(guard, OPERATIONAL_SCHEMA_V3_STATEMENTS)
            guard.execute(
                """
                INSERT INTO state_schema_migration(
                    migration_id, from_version, to_version, applied_at,
                    source_fingerprint, backup_name
                ) VALUES (?, 0, ?, ?, ?, ?)
                """,
                (
                    STATE_MIGRATION_ID,
                    STATE_SCHEMA_VERSION,
                    utc_now_iso(),
                    inspection.fingerprint,
                    target_backup.name,
                ),
            )
            guard.execute(f"PRAGMA user_version = {STATE_SCHEMA_VERSION}")
            guard.commit()
        except Exception:
            guard.rollback()
            raise
    finally:
        guard.close()

    verify_state_schema_v3(database_path)
    return StateMigrationResult(
        database_path=database_path,
        from_version=0,
        to_version=STATE_SCHEMA_VERSION,
        migrated=True,
        backup_path=target_backup,
        source_fingerprint=inspection.fingerprint,
    )
