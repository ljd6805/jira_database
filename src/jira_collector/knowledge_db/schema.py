from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_run (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    generated_at TEXT,
    analysis_schema_version TEXT,
    knowledge_input_schema_version TEXT
);

CREATE TABLE IF NOT EXISTS issue (
    jira_id TEXT PRIMARY KEY,
    issue_key TEXT NOT NULL UNIQUE,
    project_key TEXT
);

CREATE TABLE IF NOT EXISTS issue_version (
    issue_version_id TEXT PRIMARY KEY,
    jira_id TEXT NOT NULL REFERENCES issue(jira_id),
    source_hash TEXT NOT NULL,
    source_run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    source_issue_key TEXT NOT NULL,
    summary TEXT,
    description TEXT,
    description_format TEXT,
    issue_type TEXT,
    status TEXT,
    priority TEXT,
    created_at TEXT,
    updated_at TEXT,
    source_path TEXT,
    UNIQUE(jira_id, source_hash)
);

CREATE TABLE IF NOT EXISTS issue_version_observation (
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    jira_id TEXT NOT NULL REFERENCES issue(jira_id),
    observed_issue_key TEXT NOT NULL,
    issue_version_id TEXT NOT NULL REFERENCES issue_version(issue_version_id),
    PRIMARY KEY(run_id, jira_id)
);

CREATE TABLE IF NOT EXISTS comment (
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    issue_key TEXT NOT NULL,
    comment_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    author_name TEXT,
    author_key TEXT,
    created_at TEXT,
    updated_at TEXT,
    body TEXT,
    body_format TEXT,
    source_path TEXT,
    source_page TEXT,
    PRIMARY KEY(run_id, issue_key, comment_id),
    UNIQUE(run_id, issue_key, sequence)
);

CREATE TABLE IF NOT EXISTS attachment (
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    issue_key TEXT NOT NULL,
    attachment_id TEXT NOT NULL,
    filename TEXT,
    author_name TEXT,
    author_key TEXT,
    created_at TEXT,
    size_bytes INTEGER,
    mime_type TEXT,
    content_available INTEGER NOT NULL CHECK(content_available IN (0, 1)),
    source_path TEXT,
    PRIMARY KEY(run_id, attachment_id)
);

CREATE TABLE IF NOT EXISTS relationship (
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    relationship_id TEXT NOT NULL,
    relationship_category TEXT,
    relationship_type TEXT,
    relationship_text TEXT,
    source_issue_key TEXT NOT NULL,
    target_issue_key TEXT NOT NULL,
    derived INTEGER NOT NULL CHECK(derived IN (0, 1)),
    source_path TEXT,
    PRIMARY KEY(run_id, relationship_id)
);

CREATE TABLE IF NOT EXISTS custom_field_catalog (
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    field_id TEXT NOT NULL,
    field_name TEXT,
    schema_type TEXT,
    schema_items TEXT,
    schema_custom TEXT,
    schema_custom_id TEXT,
    PRIMARY KEY(run_id, field_id)
);

CREATE TABLE IF NOT EXISTS custom_field_value (
    run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    issue_key TEXT NOT NULL,
    field_id TEXT NOT NULL,
    actual_type TEXT,
    value_kind TEXT,
    display_value TEXT,
    display_values_json TEXT,
    value_id TEXT,
    value_ids_json TEXT,
    user_keys_json TEXT,
    value_shape_json TEXT,
    source_path TEXT,
    PRIMARY KEY(run_id, issue_key, field_id)
);

CREATE TABLE IF NOT EXISTS knowledge_generation (
    knowledge_generation_id TEXT PRIMARY KEY,
    issue_version_id TEXT NOT NULL REFERENCES issue_version(issue_version_id),
    jira_id TEXT NOT NULL REFERENCES issue(jira_id),
    source_run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    source_issue_key TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    knowledge_contract_hash TEXT NOT NULL,
    knowledge_schema_version TEXT NOT NULL,
    skill_version TEXT NOT NULL,
    runtime_version TEXT NOT NULL,
    model_profile TEXT NOT NULL,
    accepted_attempt_id TEXT REFERENCES knowledge_attempt(knowledge_attempt_id),
    state TEXT NOT NULL CHECK(
        state IN ('candidate', 'active', 'historical', 'review_required')
    ),
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_attempt (
    knowledge_attempt_id TEXT PRIMARY KEY,
    knowledge_generation_id TEXT NOT NULL
        REFERENCES knowledge_generation(knowledge_generation_id),
    attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1),
    knowledge_content_hash TEXT,
    content_available INTEGER NOT NULL CHECK(content_available IN (0, 1)),
    validator_status TEXT,
    generated_at TEXT,
    UNIQUE(knowledge_generation_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS knowledge_item (
    knowledge_item_id TEXT PRIMARY KEY,
    knowledge_attempt_id TEXT NOT NULL
        REFERENCES knowledge_attempt(knowledge_attempt_id),
    category TEXT NOT NULL CHECK(category IN (
        'issue_summary',
        'problem_or_goal',
        'key_findings',
        'actions_and_decisions',
        'outcomes',
        'open_items'
    )),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    statement TEXT NOT NULL CHECK(length(statement) > 0),
    UNIQUE(knowledge_attempt_id, category, ordinal)
);

CREATE TABLE IF NOT EXISTS knowledge_evidence (
    knowledge_evidence_id TEXT PRIMARY KEY,
    knowledge_item_id TEXT NOT NULL REFERENCES knowledge_item(knowledge_item_id),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    evidence_ref TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK(evidence_type IN (
        'summary', 'description', 'comment', 'attachment', 'relationship', 'custom_field'
    )),
    source_run_id TEXT NOT NULL REFERENCES pipeline_run(run_id),
    source_issue_key TEXT NOT NULL,
    source_entity_key TEXT,
    UNIQUE(knowledge_item_id, ordinal),
    UNIQUE(knowledge_item_id, evidence_ref)
);

CREATE TABLE IF NOT EXISTS knowledge_review (
    knowledge_review_id INTEGER PRIMARY KEY,
    knowledge_attempt_id TEXT NOT NULL UNIQUE
        REFERENCES knowledge_attempt(knowledge_attempt_id),
    review_schema_version TEXT NOT NULL,
    review_content_hash TEXT NOT NULL,
    score REAL NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('PASS', 'REGENERATE')),
    critical_error INTEGER NOT NULL CHECK(critical_error IN (0, 1)),
    major_issue_count INTEGER NOT NULL CHECK(major_issue_count >= 0),
    factual_fidelity_score REAL NOT NULL,
    evidence_coverage_score REAL NOT NULL,
    certainty_preservation_score REAL NOT NULL,
    classification_score REAL NOT NULL,
    retrieval_value_score REAL NOT NULL,
    language_quality_score REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS review_finding (
    review_finding_id INTEGER PRIMARY KEY,
    knowledge_review_id INTEGER NOT NULL REFERENCES knowledge_review(knowledge_review_id),
    finding_group TEXT NOT NULL,
    severity TEXT NOT NULL,
    audit_category TEXT NOT NULL DEFAULT '',
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    finding_type TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    UNIQUE(knowledge_review_id, finding_group, audit_category, ordinal)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_knowledge_generation_active_issue
ON knowledge_generation(jira_id)
WHERE state = 'active';

CREATE INDEX IF NOT EXISTS ix_issue_current_key ON issue(issue_key);
CREATE INDEX IF NOT EXISTS ix_issue_version_hash ON issue_version(jira_id, source_hash);
CREATE INDEX IF NOT EXISTS ix_knowledge_item_attempt ON knowledge_item(knowledge_attempt_id);
CREATE INDEX IF NOT EXISTS ix_evidence_source
ON knowledge_evidence(evidence_type, source_run_id, source_issue_key, source_entity_key);
"""


def connect_database(path: str | Path) -> sqlite3.Connection:
    """SQLite 연결을 만들고 FK 검증을 활성화합니다."""

    db_path = Path(path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    """빈 DB에 M7 schema v1을 만들고 호환되지 않는 버전은 거부합니다."""

    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current not in (0, SCHEMA_VERSION):
        raise ValueError(
            f"지원하지 않는 Knowledge DB schema version입니다: {current}"
        )
    connection.executescript(_SCHEMA_SQL)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
