from __future__ import annotations

import re
from pathlib import Path


CURRENT_DOCS = (
    Path("README.md"),
    Path("docs/PIPELINE_OVERVIEW.html"),
    Path("docs/index.html"),
    Path("docs/status/jira_knowledge_db_current_status.html"),
    Path("docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html"),
    Path("docs/architecture/jira_operational_two_loop_architecture.html"),
    Path("docs/architecture/jira_sync_contract.html"),
    Path("docs/architecture/jira_sync_state_schema_contract.html"),
    Path("docs/architecture/jira_knowledge_pipeline_full_explained.html"),
    Path("docs/architecture/jira_data_relationship_map.html"),
)

MILESTONE_HTML_DOCS = tuple(
    Path(f"docs/status/{name}")
    for name in (
        "M0_JIRA_COLLECTION_ANALYSIS_COMPLETION.html",
        "M1_KNOWLEDGE_INPUT_COMPLETION.html",
        "M2_KNOWLEDGE_SCHEMA_SKILL_COMPLETION.html",
        "M3_KNOWLEDGE_QUALITY_LOOP_COMPLETION.html",
        "M4_KNOWLEDGE_EXTRACTION_COMPLETION.html",
        "M5_KNOWLEDGE_PROFILING_COMPLETION.html",
        "M6_DB_LOGICAL_SCHEMA_COMPLETION.html",
        "M7_SQLITE_MATERIALIZATION.html",
        "M8_EMBEDDING_CHUNK_BGE_M3.html",
        "M9_FAISS_ACTIVE_RETRIEVAL.html",
        "M10_COMPLETION.html",
        "M11_COMPLETION.html",
    )
)

STALE_STATUS_MARKERS = (
    "M6 CURRENT", "M7 CURRENT", "M7 NEXT", "M8 BLOCKED",
    "M9 CURRENT", "M9-03 NEXT", "REAL QUERY NEXT", "REBUILD NEXT",
    "M10 NEXT / DESIGN NOT STARTED", "M10 DESIGN IN PROGRESS",
    "M10 IMPLEMENTATION PASS · REAL-RUN NEXT", "M10-05 REAL-RUN NEXT",
    "M10-05 NEXT", "M11 CURRENT", "M11-05 AUTO TOOL SELECTION NEXT",
    "M11-05 NEXT", "M11-06 NEXT",
    "TWO-LOOP REVIEW CURRENT", "S7 FINAL DDL = REVIEWING",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _done_or_current_milestones() -> set[str]:
    text = _read(Path("README.md"))
    milestones: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^\s*(M\d+)(?:~M(\d+))?\s+(.+)$", line)
        if not match:
            continue
        start = int(match.group(1)[1:])
        end = int(match.group(2)) if match.group(2) else start
        state = match.group(3).upper()
        if "DONE" in state or "CURRENT" in state:
            milestones.update(f"M{n}" for n in range(start, end + 1))
    return milestones


def test_current_docs_do_not_regress_to_old_status() -> None:
    for path in CURRENT_DOCS:
        text = _read(path)
        for marker in STALE_STATUS_MARKERS:
            assert marker not in text, f"{path} contains stale marker: {marker}"


def test_current_docs_record_two_loop_v2_as_source_of_truth() -> None:
    required = (
        Path("README.md"),
        Path("docs/PIPELINE_OVERVIEW.html"),
        Path("docs/index.html"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
        Path("docs/status/POST_MVP_OPERATIONAL_SERVICE_START_HERE.html"),
    )
    for path in required:
        text = _read(path)
        upper = text.upper()
        assert "TWO-LOOP" in upper or "2-LOOP" in upper, path
        assert "SOURCE" in upper and "PROCESSING" in upper, path
        assert "SYNC_ISSUE_CHANGE" in text, path
        assert "v2" in text or "V2" in text, path


def test_current_contract_and_schema_separate_source_and_processing_runs() -> None:
    contract = _read(Path("docs/architecture/jira_sync_contract.html"))
    schema = _read(Path("docs/architecture/jira_sync_state_schema_contract.html"))
    ddl = _read(Path("docs/architecture/jira_sync_state_schema_decision7_final_ddl.html"))

    for text in (contract, schema, ddl):
        assert "source_sync_run" in text
        assert "processing_run" in text
        assert "sync_issue_change" in text

    assert "STATE_SCHEMA_VERSION = 2" in schema
    assert "PRAGMA user_version = 2" in schema
    assert "CREATE TABLE IF NOT EXISTS source_sync_run" in ddl
    assert "CREATE TABLE IF NOT EXISTS processing_run" in ddl
    assert "CREATE TABLE IF NOT EXISTS sync_issue_change" in ddl


def test_historical_v1_is_explicitly_superseded_and_not_current() -> None:
    historical = _read(Path("docs/architecture/jira_sync_state_schema_contract_v1_baseline.html"))
    upper = historical.upper()
    assert "SUPERSEDED" in upper
    assert "NEVER DEPLOYED" in upper or "NEVER-DEPLOYED" in upper or "NEVER DEPLOYED" in historical
    assert "jira_sync_state_schema_contract.html" in historical

    agents = _read(Path("AGENTS.md"))
    assert "historical/superseded" in agents
    assert "jira_operational_two_loop_architecture.html" in agents
    assert "jira_sync_state_schema_contract.html" in agents


def test_two_loop_docs_preserve_source_commit_publish_boundary() -> None:
    required = (
        Path("docs/architecture/jira_operational_two_loop_architecture.html"),
        Path("docs/architecture/jira_sync_contract.html"),
        Path("docs/architecture/jira_sync_contract_easy_guide.html"),
        Path("docs/architecture/jira_knowledge_pipeline_full_explained.html"),
    )
    for path in required:
        text = _read(path)
        assert "SOURCE_COMMITTED" in text
        assert "PUBLISHED" in text or "Published" in text
        assert "backlog" in text.lower()


def test_two_loop_observability_terms_are_kept() -> None:
    required = (
        Path("docs/architecture/jira_operational_two_loop_architecture.html"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
    )
    for path in required:
        text = _read(path).lower()
        for token in ("source lag", "publish lag", "backlog", "oldest pending"):
            assert token in text, f"{path} missing {token}"


def test_m10_completion_and_real_run_are_preserved() -> None:
    text = _read(Path("docs/status/M10_COMPLETION.html"))
    upper = text.upper()
    for token in (
        "M10_REAL_RUN = PASS", "tool_count: 2", "search_result_count: 3",
        "evidence_count: 6", "warning_count: 0", "path_leak_count: 0",
        "issue_lookup_ok: true", "failure_count: 0",
    ):
        assert token in text
    assert "DONE" in upper and "PASS" in upper


def test_m11_completion_is_preserved() -> None:
    text = _read(Path("docs/status/M11_COMPLETION.html"))
    upper = text.upper()
    assert "M11" in text and "DONE" in upper and "PASS" in upper
    assert "M11-05" in text and "M11-06" in text


def test_authoritative_docs_keep_generation_attempt_identity() -> None:
    required = (
        Path("README.md"),
        Path("docs/architecture/jira_knowledge_pipeline_full_explained.html"),
        Path("docs/status/M10_START_HERE.html"),
        Path("docs/M6_DECISION_LOG.md"),
        Path("docs/M7_SQLITE_MATERIALIZATION.md"),
    )
    for path in required:
        text = _read(path)
        assert "knowledge_attempt" in text or "Knowledge Attempt" in text or "Attempt" in text
        assert "ka_" in text and "attempt_no" in text


def test_m7_completion_doc_records_real_run_gate() -> None:
    text = _read(Path("docs/M7_SQLITE_MATERIALIZATION.md"))
    for token in (
        "M7_REAL_RUN = PASS", "Evidence raw      503", "Evidence           502",
        "idempotent         true", "Evidence Failure     0", "FK Failure           0",
    ):
        assert token in text


def test_m8_final_gate_is_preserved() -> None:
    text = _read(Path("docs/M8_REAL_EMBEDDING_LOG.md"))
    for token in (
        "M8 = DONE", "corpus_rows: 285", "embedding_rows: 285",
        "batch_count: 5", "embedding_dimension: 1024",
        "mapping_failure_count: 0", "identity_failure_count: 0",
        "Semantic Quality Sanity Check · PASS",
    ):
        assert token in text


def test_m9_final_contract_and_real_gate_are_preserved() -> None:
    design = _read(Path("docs/M9_FAISS_ACTIVE_RETRIEVAL.md"))
    decision = _read(Path("docs/M9_DECISION_LOG.md"))
    log = _read(Path("docs/M9_REAL_RETRIEVAL_LOG.md"))
    visual = _read(Path("docs/status/M9_FAISS_ACTIVE_RETRIEVAL.html"))
    for text in (design, decision, visual):
        for token in ("IndexFlatIP", "Top-3", "embedding_id", "knowledge_item_id", "HNSW", "IVF"):
            assert token in text
        assert "cosine" in text.lower()
    assert "rc_" in design and "fi_" in design and "manifest" in design.lower()
    for token in (
        "M9 = DONE / PASS", "vector_count = 285", "dimension = 1024",
        "vector_exact_equal=True", "max_abs_diff=0", "cosine=1.000000000",
        "ranking_equal=True", "scores_exact_equal=True", "Top-3 noise",
    ):
        assert token in log


def test_m0_to_m11_visual_docs_exist_and_are_static() -> None:
    for path in MILESTONE_HTML_DOCS:
        assert path.is_file()
        text = _read(path)
        lower = text.lower()
        assert "<!doctype html>" in lower and "<main" in lower
        assert "fetch(" not in text and "DecompressionStream" not in text


def test_every_done_or_current_milestone_has_visual_html() -> None:
    milestones = _done_or_current_milestones()
    assert milestones
    for milestone in sorted(milestones):
        assert list(Path("docs/status").glob(f"{milestone}_*.html")), milestone


def test_documentation_hub_links_all_milestone_completion_docs() -> None:
    index = _read(Path("docs/index.html"))
    for path in MILESTONE_HTML_DOCS:
        assert path.name in index


def test_documentation_hub_links_current_two_loop_sources() -> None:
    index = _read(Path("docs/index.html"))
    for name in (
        "jira_operational_two_loop_architecture.html",
        "jira_sync_contract.html",
        "jira_sync_state_schema_contract.html",
        "jira_sync_contract_easy_guide.html",
        "jira_knowledge_pipeline_full_explained.html",
        "jira_knowledge_db_current_status.html",
        "POST_MVP_OPERATIONAL_SERVICE_START_HERE.html",
    ):
        assert name in index


def test_public_current_docs_do_not_expose_pilot_issue_keys() -> None:
    public_docs = CURRENT_DOCS + (
        Path("docs/status/M9_FAISS_ACTIVE_RETRIEVAL.html"),
        Path("docs/status/M10_COMPLETION.html"),
        Path("docs/status/M11_COMPLETION.html"),
        Path("docs/architecture/jira_knowledge_mcp_service_target.html"),
    )
    pattern = re.compile(r"\b[A-Z][A-Z0-9_]{1,15}-[1-9]\d{3,}\b")
    for path in public_docs:
        matches = pattern.findall(_read(path))
        assert not matches, f"{path}: {matches[:3]}"


def test_html_preservation_rules_require_user_approval_for_deletion() -> None:
    for text in (_read(Path("AGENTS.md")), _read(Path("docs/DOCUMENTATION_POLICY.md"))):
        for token in ("Markdown", "대체", "HTML", "삭제", "사용자", "승인"):
            assert token in text
