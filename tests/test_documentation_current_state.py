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

MILESTONE_HTML_DOCS = (
    Path("docs/status/M0_JIRA_COLLECTION_ANALYSIS_COMPLETION.html"),
    Path("docs/status/M1_KNOWLEDGE_INPUT_COMPLETION.html"),
    Path("docs/status/M2_KNOWLEDGE_SCHEMA_SKILL_COMPLETION.html"),
    Path("docs/status/M3_KNOWLEDGE_QUALITY_LOOP_COMPLETION.html"),
    Path("docs/status/M4_KNOWLEDGE_EXTRACTION_COMPLETION.html"),
    Path("docs/status/M5_KNOWLEDGE_PROFILING_COMPLETION.html"),
    Path("docs/status/M6_DB_LOGICAL_SCHEMA_COMPLETION.html"),
    Path("docs/status/M7_SQLITE_MATERIALIZATION.html"),
    Path("docs/status/M8_EMBEDDING_CHUNK_BGE_M3.html"),
)

STALE_STATUS_MARKERS = (
    "M6 CURRENT",
    "M7 NEXT",
    "M7 PLAN",
    "M7 CURRENT",
    "M8 BLOCKED",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _done_or_current_milestones() -> set[str]:
    """README의 표/코드 상태에서 HTML이 필요한 Milestone을 찾습니다."""

    text = _read(Path("README.md"))
    milestones: set[str] = set()

    for line in text.splitlines():
        table_match = re.match(r"^\|\s*(M\d+)\s*\|\s*([^|]+)\|", line)
        if table_match:
            milestone = table_match.group(1)
            state = table_match.group(2).replace("*", "").replace("`", "").strip().upper()
            if "DONE" in state or "CURRENT" in state:
                milestones.add(milestone)
            continue

        code_match = re.match(r"^\s*(M\d+)(?:~M(\d+))?\s+(.+)$", line)
        if not code_match:
            continue
        start = int(code_match.group(1)[1:])
        end = int(code_match.group(2)) if code_match.group(2) else start
        state = code_match.group(3).upper()
        if "DONE" not in state and "CURRENT" not in state:
            continue
        milestones.update(f"M{number}" for number in range(start, end + 1))

    return milestones


def test_current_docs_do_not_regress_to_old_milestone_status() -> None:
    """Current Source of Truth가 M7 CURRENT/M8 BLOCKED 상태로 퇴행하지 않게 합니다."""

    for path in CURRENT_DOCS:
        text = _read(path)
        for marker in STALE_STATUS_MARKERS:
            assert marker not in text, f"{path} contains stale marker: {marker}"


def test_current_docs_point_to_m8_after_m7_pass() -> None:
    """전역 Current 문서가 M7 PASS와 M8 CURRENT를 함께 나타내는지 확인합니다."""

    required = (
        Path("README.md"),
        Path("docs/PIPELINE_OVERVIEW.md"),
        Path("docs/index.html"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
    )
    for path in required:
        text = _read(path)
        assert "M7" in text
        assert "PASS" in text.upper()
        assert "M8" in text
        assert "CURRENT" in text.upper()


def test_authoritative_docs_keep_generation_attempt_identity() -> None:
    """Generation→Attempt와 ka_ 회차 ID가 문서에서 유실되지 않게 합니다."""

    required = (
        Path("README.md"),
        Path("docs/PIPELINE_OVERVIEW.md"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
        Path("docs/M6_DECISION_LOG.md"),
        Path("docs/M7_SQLITE_MATERIALIZATION.md"),
    )
    for path in required:
        text = _read(path)
        assert "knowledge_attempt" in text or "Knowledge Attempt" in text
        assert "ka_" in text
        assert "attempt_no" in text


def test_architecture_map_uses_attempt_as_item_and_review_parent() -> None:
    """시각화가 Generation→Item/Review 구조로 퇴행하지 않게 합니다."""

    entity_map = _read(Path("docs/architecture/jira_data_relationship_map.data_a.js"))
    schema_map = _read(Path("docs/architecture/jira_data_relationship_map.data_b.js"))

    for text in (entity_map, schema_map):
        compact = text.replace(" ", "").replace("\n", "")
        assert '"from":"generation","to":"attempt"' in compact
        assert '"from":"attempt","to":"item"' in compact
        assert '"from":"attempt","to":"review"' in compact
        assert '"from":"generation","to":"item"' not in compact
        assert '"from":"generation","to":"review"' not in compact


def test_m7_completion_doc_records_real_run_gate() -> None:
    """M7 완료 문서가 raw/canonical Evidence와 최종 integrity Gate를 보존합니다."""

    text = _read(Path("docs/M7_SQLITE_MATERIALIZATION.md"))

    assert "M7_REAL_RUN = PASS" in text
    assert "Evidence raw      503" in text
    assert "Evidence           502" in text
    assert "idempotent         true" in text
    assert "Evidence Failure     0" in text
    assert "FK Failure           0" in text
    assert "Integrity          true" in text


def test_m8_current_design_keeps_m9_boundary() -> None:
    """M8에서 FAISS를 미리 구현하는 경계 회귀를 막습니다."""

    text = _read(Path("docs/M8_EMBEDDING_CHUNK_BGE_M3.md"))
    assert "CURRENT" in text
    assert "BGE-M3" in text
    assert "1024" in text
    assert "64" in text
    assert "FAISS" in text
    assert "M9" in text
    assert "M8에서는 FAISS" in text


def test_m0_to_m8_visual_docs_exist_and_are_static() -> None:
    """M0~M8 HTML이 삭제되거나 fragment loader로 퇴행하지 않게 합니다."""

    for path in MILESTONE_HTML_DOCS:
        assert path.is_file(), f"missing milestone HTML: {path}"
        text = _read(path)
        lower = text.lower()
        assert "<!doctype html>" in lower
        assert "<main" in lower
        assert "fetch(" not in text
        assert "DecompressionStream" not in text


def test_every_done_or_current_milestone_has_visual_html() -> None:
    """새 Milestone을 CURRENT/DONE으로 바꾸면서 HTML 작성을 빼먹지 않게 합니다."""

    milestones = _done_or_current_milestones()
    assert milestones, "README milestone state could not be parsed"

    status_dir = Path("docs/status")
    for milestone in sorted(milestones):
        matches = list(status_dir.glob(f"{milestone}_*.html"))
        assert matches, f"{milestone} is DONE/CURRENT but has no docs/status/{milestone}_*.html"


def test_documentation_hub_links_all_milestone_visual_docs() -> None:
    """docs/index.html에서 M0~M8 시각 문서가 모두 발견되게 합니다."""

    index = _read(Path("docs/index.html"))
    for path in MILESTONE_HTML_DOCS:
        assert path.name in index, f"docs/index.html does not link {path.name}"


def test_public_docs_do_not_expose_pilot_issue_keys() -> None:
    """Current/Completion 문서에는 실제 Jira Issue Key를 남기지 않습니다."""

    public_docs = CURRENT_DOCS + (
        Path("docs/M7_REAL_RUN_LOG.md"),
        Path("docs/M7_SQLITE_MATERIALIZATION.md"),
        Path("docs/status/M7_SQLITE_MATERIALIZATION_COMPLETION.md"),
        Path("docs/status/M7_SQLITE_MATERIALIZATION.html"),
    )
    # Jira-like PROJECT-123은 잡되 M6-01/M6-02 같은 Milestone decision label은 제외합니다.
    issue_key_pattern = re.compile(r"\b(?!M\d+-\d+\b)[A-Z][A-Z0-9_]{1,15}-\d+\b")
    for path in public_docs:
        text = _read(path)
        matches = issue_key_pattern.findall(text)
        assert not matches, f"{path} exposes Jira-like issue keys: {matches[:3]}"


def test_html_preservation_rules_require_user_approval_for_deletion() -> None:
    """HTML을 Markdown으로 대체하거나 승인 없이 삭제하는 규칙 회귀를 막습니다."""

    agents = _read(Path("AGENTS.md"))
    policy = _read(Path("docs/DOCUMENTATION_POLICY.md"))

    for text in (agents, policy):
        assert "Markdown" in text
        assert "대체" in text
        assert "HTML" in text
        assert "삭제" in text
        assert "사용자" in text
        assert "승인" in text

    assert "삭제하기 전에" in agents
    assert "같은 작업 단위" in agents
