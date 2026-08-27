from __future__ import annotations

import re
from pathlib import Path


CURRENT_DOCS = (
    Path("README.md"),
    Path("docs/PIPELINE_OVERVIEW.md"),
    Path("docs/index.html"),
    Path("docs/status/jira_knowledge_db_current_status.html"),
    Path("docs/architecture/jira_data_relationship_map.html"),
    Path("docs/architecture/jira_data_relationship_map.data_a.js"),
    Path("docs/architecture/jira_data_relationship_map.data_b.js"),
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
    )
)

STALE_STATUS_MARKERS = (
    "M6 CURRENT", "M7 CURRENT", "M7 NEXT", "M8 BLOCKED",
    "M9 CURRENT", "M9-03 NEXT", "REAL QUERY NEXT", "REBUILD NEXT",
    "M10 NEXT / DESIGN NOT STARTED", "M10 DESIGN IN PROGRESS",
    "M10 IMPLEMENTATION PASS · REAL-RUN NEXT", "M10-05 REAL-RUN NEXT",
    "M10-05 NEXT",
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


def test_current_docs_record_m10_done_and_real_run_pass() -> None:
    required = (
        Path("README.md"),
        Path("docs/PIPELINE_OVERVIEW.md"),
        Path("docs/index.html"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
    )
    for path in required:
        text = _read(path); upper = text.upper()
        assert "M8" in text and "DONE" in upper
        assert "M9" in text and "DONE" in upper and "PASS" in upper
        assert "M10" in text and "DONE" in upper
        assert "REAL-RUN" in upper and "PASS" in upper
        assert "M10_REAL_RUN = PASS" in text


def test_authoritative_docs_keep_generation_attempt_identity() -> None:
    required = (
        Path("README.md"), Path("docs/PIPELINE_OVERVIEW.md"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
        Path("docs/status/M10_START_HERE.html"),
        Path("docs/M6_DECISION_LOG.md"), Path("docs/M7_SQLITE_MATERIALIZATION.md"),
    )
    for path in required:
        text = _read(path)
        assert "knowledge_attempt" in text or "Knowledge Attempt" in text
        assert "ka_" in text and "attempt_no" in text


def test_architecture_map_uses_attempt_as_item_and_review_parent() -> None:
    for path in (
        Path("docs/architecture/jira_data_relationship_map.data_a.js"),
        Path("docs/architecture/jira_data_relationship_map.data_b.js"),
    ):
        compact = _read(path).replace(" ", "").replace("\n", "")
        assert '"from":"generation","to":"attempt"' in compact
        assert '"from":"attempt","to":"item"' in compact
        assert '"from":"attempt","to":"review"' in compact
        assert '"from":"generation","to":"item"' not in compact
        assert '"from":"generation","to":"review"' not in compact


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
    assert "M9 = DONE / PASS" in design and "M10" in design
    for token in (
        "M9 = DONE / PASS", "vector_count = 285", "dimension = 1024",
        "vector_exact_equal=True", "max_abs_diff=0", "cosine=1.000000000",
        "ranking_equal=True", "scores_exact_equal=True", "Top-3 noise",
    ):
        assert token in log
    lower_decision = decision.lower()
    assert "delta-first" in lower_decision or "delta first" in lower_decision


def test_m10_completion_and_troubleshooting_docs_are_static_html() -> None:
    paths = (
        Path("docs/status/M10_START_HERE.html"),
        Path("docs/status/M10_EVIDENCE_MCP_CONTRACT.html"),
        Path("docs/status/M10_EVIDENCE_RESOLVER_IMPLEMENTATION.html"),
        Path("docs/status/M10_MCP_IMPLEMENTATION.html"),
        Path("docs/status/M10_REAL_RUN_GATE.html"),
        Path("docs/status/M10_COMPLETION.html"),
        Path("docs/status/M10_TROUBLESHOOTING_MCP_IMPORT.html"),
        Path("docs/status/M10_TROUBLESHOOTING_REAL_RUN_QUERY.html"),
        Path("docs/status/M10_TROUBLESHOOTING_RUNTIME_SETTINGS.html"),
    )
    for path in paths:
        assert path.is_file()
        text = _read(path); lower = text.lower()
        assert "<!doctype html>" in lower and "<main" in lower
        assert "fetch(" not in text and "DecompressionStream" not in text

    handoff = _read(paths[0])
    for token in (
        "M0~M10 DONE", "M10_REAL_RUN = PASS", "Evidence",
        "knowledge_attempt", "ka_", "attempt_no",
        "DESIGN → IMPLEMENTATION → VALIDATION → DOCUMENTATION SYNC",
    ):
        assert token in handoff

    contract = _read(paths[1])
    for token in (
        "M10-01", "CONTRACT", "FROZEN", "Evidence Package",
        "search_jira_knowledge", "get_jira_issue", "Top-3",
        "active", "accepted", "M10-02",
    ):
        assert token in contract

    implementation = _read(paths[3])
    for token in (
        "M10-04", "search_jira_knowledge", "get_jira_issue",
        "mode=ro", "query_only", "M10-05",
    ):
        assert token in implementation

    real_run = _read(paths[4])
    for token in (
        "M10-05", "JIRA_KNOWLEDGE_DB_PATH", "JIRA_RETRIEVAL_ARTIFACT_DIR",
        "M10_REAL_RUN_QUERY", "warning_count: 0", "path_leak_count: 0",
        "M10_REAL_RUN = PASS",
    ):
        assert token in real_run


def test_m10_completion_explains_real_run_metrics() -> None:
    text = _read(Path("docs/status/M10_COMPLETION.html"))
    for token in (
        "tool_count: 2", "search_result_count: 3", "evidence_count: 6",
        "warning_count: 0", "path_leak_count: 0", "issue_lookup_ok: true",
        "failure_count: 0", "M10_REAL_RUN = PASS",
        "Tool을 2번 호출했다는 뜻이 아닙니다",
        "Issue 6개나 Knowledge 6개라는 뜻이 아닙니다",
        "ModuleNotFoundError", "McpRuntimeSettingsError",
    ):
        assert token in text


def test_m10_real_run_validator_exists_and_is_privacy_preserving() -> None:
    path = Path("tools/jira_knowledge/validate_m10_real_run.py")
    assert path.is_file()
    text = _read(path)
    for token in (
        "M10_REAL_RUN_QUERY", "search_jira_knowledge", "get_jira_issue",
        "search_result_count", "evidence_count", "warning_count",
        "path_leak_count", "M10_REAL_RUN =",
    ):
        assert token in text
    assert 'print(query' not in text and 'print(issue_key' not in text


def test_m0_to_m10_visual_docs_exist_and_are_static() -> None:
    for path in MILESTONE_HTML_DOCS:
        assert path.is_file()
        text = _read(path); lower = text.lower()
        assert "<!doctype html>" in lower and "<main" in lower
        assert "fetch(" not in text and "DecompressionStream" not in text


def test_every_done_or_current_milestone_has_visual_html() -> None:
    milestones = _done_or_current_milestones(); assert milestones
    for milestone in sorted(milestones):
        assert list(Path("docs/status").glob(f"{milestone}_*.html")), milestone


def test_documentation_hub_links_milestones_completion_and_troubleshooting() -> None:
    index = _read(Path("docs/index.html"))
    for path in MILESTONE_HTML_DOCS:
        assert path.name in index
    for name in (
        "M10_START_HERE.html", "M10_EVIDENCE_MCP_CONTRACT.html",
        "M10_MCP_IMPLEMENTATION.html", "M10_REAL_RUN_GATE.html",
        "M10_COMPLETION.html", "M10_TROUBLESHOOTING_MCP_IMPORT.html",
        "M10_TROUBLESHOOTING_REAL_RUN_QUERY.html",
        "M10_TROUBLESHOOTING_RUNTIME_SETTINGS.html",
    ):
        assert name in index


def test_public_docs_do_not_expose_pilot_issue_keys() -> None:
    public_docs = CURRENT_DOCS + (
        Path("docs/M8_REAL_EMBEDDING_LOG.md"),
        Path("docs/M9_FAISS_ACTIVE_RETRIEVAL.md"),
        Path("docs/M9_DECISION_LOG.md"),
        Path("docs/M9_REAL_RETRIEVAL_LOG.md"),
        Path("docs/M9_FAISS_ACTIVE_RETRIEVAL.html"),
        Path("docs/M9_DECISION_LOG.html"),
        Path("docs/M9_REAL_RETRIEVAL_LOG.html"),
        Path("docs/status/M9_FAISS_ACTIVE_RETRIEVAL.html"),
        Path("docs/status/M10_START_HERE.html"),
        Path("docs/M10_EVIDENCE_MCP_DESIGN.html"),
        Path("docs/status/M10_EVIDENCE_MCP_CONTRACT.html"),
        Path("docs/status/M10_EVIDENCE_RESOLVER_IMPLEMENTATION.html"),
        Path("docs/status/M10_MCP_IMPLEMENTATION.html"),
        Path("docs/status/M10_REAL_RUN_GATE.html"),
        Path("docs/status/M10_COMPLETION.html"),
        Path("docs/status/M10_TROUBLESHOOTING_MCP_IMPORT.html"),
        Path("docs/status/M10_TROUBLESHOOTING_REAL_RUN_QUERY.html"),
        Path("docs/status/M10_TROUBLESHOOTING_RUNTIME_SETTINGS.html"),
    )
    pattern = re.compile(r"\b[A-Z][A-Z0-9_]{1,15}-[1-9]\d{3,}\b")
    for path in public_docs:
        matches = pattern.findall(_read(path)); assert not matches, f"{path}: {matches[:3]}"


def test_html_preservation_rules_require_user_approval_for_deletion() -> None:
    for text in (_read(Path("AGENTS.md")), _read(Path("docs/DOCUMENTATION_POLICY.md"))):
        for token in ("Markdown", "대체", "HTML", "삭제", "사용자", "승인"):
            assert token in text
