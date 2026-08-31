from __future__ import annotations

from pathlib import Path


REPORT = Path("docs/status/LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html")


def _read(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_loop_a_implementation_report_exists_and_records_real_gate() -> None:
    assert REPORT.is_file()
    text = _read(REPORT)
    assert "<!doctype html>" in text.lower()
    for token in (
        "IMPLEMENTED",
        "CI PASS",
        "REAL JIRA ENV GATE PENDING",
        "source_sync.py",
        "semantic_v2",
        "updated ASC, id ASC",
        "same-run Resume",
        "run_source_sync.py",
    ):
        assert token in text


def test_loop_a_report_is_linked_from_current_entry_docs() -> None:
    for path in (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html",
    ):
        text = _read(path)
        assert "LOOP_A_DELTA_SOURCE_SYNC_IMPLEMENTATION.html" in text, path


def test_current_entry_docs_keep_loop_a_done_and_advance_to_atomic_publish() -> None:
    for path in (
        "README.md",
        "docs/index.html",
        "docs/PIPELINE_OVERVIEW.html",
        "docs/status/jira_knowledge_db_current_status.html",
        "docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html",
    ):
        text = _read(path)
        assert "Loop A" in text and "IMPLEMENTED" in text, path
        assert "Loop B" in text and "Knowledge" in text and "IMPLEMENTED" in text, path
        assert "Atomic Publish" in text and "NEXT" in text, path


def test_loop_a_code_keeps_fixed_upper_delta_and_resume_contract() -> None:
    source = _read("src/jira_collector/source_sync.py")
    for token in (
        "/serverInfo",
        "committed_watermark",
        "updated >=",
        "updated <",
        "ORDER BY updated ASC, id ASC",
        "record_source_candidate",
        "commit_source_project",
        "resume",
    ):
        assert token in source


def test_semantic_v2_code_excludes_non_semantic_runtime_metadata() -> None:
    builder = _read("src/jira_collector/knowledge_input/builder.py")
    assert 'SOURCE_HASH_PROFILE = "semantic_v2"' in builder
    for token in (
        'issue_material.pop("updated_at", None)',
        'comment.pop("updated_at", None)',
        '"source_path"',
        '"source_page"',
        '"other_package_available"',
    ):
        assert token in builder
