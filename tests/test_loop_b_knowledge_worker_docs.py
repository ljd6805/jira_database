from __future__ import annotations

from pathlib import Path


REPORT = Path("docs/status/LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html")


def _read(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_loop_b_knowledge_report_exists_and_records_real_gate() -> None:
    assert REPORT.is_file()
    text = _read(REPORT)
    assert "<!doctype html>" in text.lower()
    for token in (
        "IMPLEMENTED",
        "CI PASS",
        "REAL OPENCODE RUN PENDING",
        "knowledge_processing.py",
        "run_knowledge_worker.py",
        "jira-knowledge-orchestrator",
        "stale",
        "Embedding/Publish",
    ):
        assert token in text


def test_loop_b_report_is_linked_from_current_entry_docs() -> None:
    for path in (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html",
    ):
        text = _read(path)
        assert "LOOP_B_KNOWLEDGE_WORKER_IMPLEMENTATION.html" in text, path


def test_current_docs_do_not_claim_full_loop_b_publish_done() -> None:
    for path in (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html",
    ):
        text = _read(path)
        assert "Loop B" in text and "Knowledge" in text
        assert "Data Plane" in text and "NEXT" in text
        assert "Loop B PUBLISHED DONE" not in text


def test_loop_b_code_has_latest_staging_and_review_guards() -> None:
    source = _read("src/jira_collector/knowledge_processing.py")
    for token in (
        "opencode",
        "jira-knowledge-orchestrator",
        "staging",
        "validate_knowledge_document",
        "_assert_review_pass",
        "work_item_is_latest",
        "mark_knowledge_completed",
        "knowledge_generation_id",
    ):
        assert token in source
