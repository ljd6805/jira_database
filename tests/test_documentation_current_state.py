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
    )
)

STALE_STATUS_MARKERS = (
    "M6 CURRENT",
    "M7 CURRENT",
    "M7 NEXT",
    "M8 BLOCKED",
    "M9 CURRENT",
    "M9-03 NEXT",
    "REAL QUERY NEXT",
    "REBUILD NEXT",
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


def test_current_docs_record_m9_done_and_m10_next() -> None:
    required = (
        Path("README.md"),
        Path("docs/PIPELINE_OVERVIEW.md"),
        Path("docs/index.html"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
    )
    for path in required:
        text = _read(path)
        upper = text.upper()
        assert "M8" in text and "DONE" in upper
        assert "M9" in text and "DONE" in upper and "PASS" in upper
        assert "M10" in text and "NEXT" in upper
        assert "DESIGN" in upper


def test_authoritative_docs_keep_generation_attempt_identity() -> None:
    required = (
        Path("README.md"),
        Path("docs/PIPELINE_OVERVIEW.md"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
        Path("docs/status/M10_START_HERE.html"),
        Path("docs/M6_DECISION_LOG.md"),
        Path("docs/M7_SQLITE_MATERIALIZATION.md"),
    )
    for path in required:
        text = _read(path)
        assert "knowledge_attempt" in text or "Knowledge Attempt" in text
        assert "ka_" in text
        assert "attempt_no" in text


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
    assert "M7_REAL_RUN = PASS" in text
    assert "Evidence raw      503" in text
    assert "Evidence           502" in text
    assert "idempotent         true" in text
    assert "Evidence Failure     0" in text
    assert "FK Failure           0" in text


def test_m8_final_gate_is_preserved() -> None:
    text = _read(Path("docs/M8_REAL_EMBEDDING_LOG.md"))
    assert "M8 = DONE" in text
    assert "corpus_rows: 285" in text
    assert "embedding_rows: 285" in text
    assert "batch_count: 5" in text
    assert "embedding_dimension: 1024" in text
    assert "mapping_failure_count: 0" in text
    assert "identity_failure_count: 0" in text
    assert "Semantic Quality Sanity Check · PASS" in text


def test_m9_final_contract_and_real_gate_are_preserved() -> None:
    design = _read(Path("docs/M9_FAISS_ACTIVE_RETRIEVAL.md"))
    decision = _read(Path("docs/M9_DECISION_LOG.md"))
    log = _read(Path("docs/M9_REAL_RETRIEVAL_LOG.md"))
    visual = _read(Path("docs/status/M9_FAISS_ACTIVE_RETRIEVAL.html"))

    for text in (design, decision, visual):
        assert "IndexFlatIP" in text
        assert "cosine" in text.lower()
        assert "Top-3" in text
        assert "embedding_id" in text
        assert "knowledge_item_id" in text
        assert "HNSW" in text
        assert "IVF" in text

    assert "rc_" in design and "fi_" in design and "manifest" in design.lower()
    assert "M9 = DONE / PASS" in design
    assert "M10" in design

    assert "M9 = DONE / PASS" in log
    assert "vector_count = 285" in log
    assert "dimension = 1024" in log
    assert "vector_exact_equal=True" in log
    assert "max_abs_diff=0" in log
    assert "cosine=1.000000000" in log
    assert "ranking_equal=True" in log
    assert "scores_exact_equal=True" in log
    assert "Top-3 noise" in log
    assert "delta-first" in decision.lower()


def test_m10_handoff_is_complete_and_static_html() -> None:
    path = Path("docs/status/M10_START_HERE.html")
    assert path.is_file()
    text = _read(path)
    lower = text.lower()
    for token in (
        "M0~M9 DONE",
        "M10 NEXT",
        "DESIGN NOT STARTED",
        "Evidence Package",
        "Resolver Contract",
        "MCP Tool Surface",
        "knowledge_attempt",
        "ka_",
        "attempt_no",
        "IndexFlatIP",
        "delta-first",
        "DESIGN → IMPLEMENTATION → VALIDATION → DOCUMENTATION SYNC",
    ):
        assert token in text
    assert "<!doctype html>" in lower
    assert "<main" in lower
    assert "fetch(" not in text


def test_m0_to_m9_visual_docs_exist_and_are_static() -> None:
    for path in MILESTONE_HTML_DOCS:
        assert path.is_file(), f"missing milestone HTML: {path}"
        text = _read(path)
        lower = text.lower()
        assert "<!doctype html>" in lower
        assert "<main" in lower
        assert "fetch(" not in text
        assert "DecompressionStream" not in text


def test_every_done_or_current_milestone_has_visual_html() -> None:
    milestones = _done_or_current_milestones()
    assert milestones
    status_dir = Path("docs/status")
    for milestone in sorted(milestones):
        assert list(status_dir.glob(f"{milestone}_*.html")), milestone


def test_documentation_hub_links_milestones_and_m10_handoff() -> None:
    index = _read(Path("docs/index.html"))
    for path in MILESTONE_HTML_DOCS:
        assert path.name in index
    assert "M10_START_HERE.html" in index


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
    )
    issue_key_pattern = re.compile(r"\b[A-Z][A-Z0-9_]{1,15}-[1-9]\d{3,}\b")
    for path in public_docs:
        matches = issue_key_pattern.findall(_read(path))
        assert not matches, f"{path} exposes Jira-like issue keys: {matches[:3]}"


def test_html_preservation_rules_require_user_approval_for_deletion() -> None:
    agents = _read(Path("AGENTS.md"))
    policy = _read(Path("docs/DOCUMENTATION_POLICY.md"))
    for text in (agents, policy):
        assert "Markdown" in text
        assert "대체" in text
        assert "HTML" in text
        assert "삭제" in text
        assert "사용자" in text
        assert "승인" in text
