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
)

STALE_STATUS_MARKERS = (
    "M6 CURRENT",
    "M7 NEXT",
    "M7 PLAN",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _done_or_current_milestones() -> set[str]:
    """README 상태표에서 HTML이 반드시 존재해야 하는 Milestone을 찾습니다."""

    milestones: set[str] = set()
    for line in _read(Path("README.md")).splitlines():
        match = re.match(r"^\|\s*(M\d+)\s*\|\s*([^|]+)\|", line)
        if not match:
            continue
        milestone = match.group(1)
        state = match.group(2).replace("*", "").replace("`", "").strip().upper()
        if "DONE" in state or "CURRENT" in state:
            milestones.add(milestone)
    return milestones


def test_current_docs_do_not_regress_to_old_milestone_status() -> None:
    """Current Source of Truth가 이미 끝난 M6를 다시 CURRENT로 표시하지 않게 합니다."""

    for path in CURRENT_DOCS:
        text = _read(path)
        for marker in STALE_STATUS_MARKERS:
            assert marker not in text, f"{path} contains stale marker: {marker}"


def test_current_docs_point_to_m7_real_run_validation() -> None:
    """전역 Current 문서가 M7 실데이터 검증을 현재 Gate로 가리키는지 확인합니다."""

    required = (
        Path("README.md"),
        Path("docs/PIPELINE_OVERVIEW.md"),
        Path("docs/status/jira_knowledge_db_current_status.html"),
    )
    for path in required:
        text = _read(path)
        assert "M7" in text
        assert "REAL-RUN" in text.upper() or "real-run" in text.lower()


def test_authoritative_docs_keep_generation_attempt_identity() -> None:
    """M6-02의 Generation→Attempt와 ka_ 회차 ID가 문서에서 유실되지 않게 합니다."""

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
    """시각화가 M6-01의 옛 Generation→Item/Review 구조로 퇴행하지 않게 합니다."""

    entity_map = _read(Path("docs/architecture/jira_data_relationship_map.data_a.js"))
    schema_map = _read(Path("docs/architecture/jira_data_relationship_map.data_b.js"))

    for text in (entity_map, schema_map):
        compact = text.replace(" ", "").replace("\n", "")
        assert '"from":"generation","to":"attempt"' in compact
        assert '"from":"attempt","to":"item"' in compact
        assert '"from":"attempt","to":"review"' in compact
        assert '"from":"generation","to":"item"' not in compact
        assert '"from":"generation","to":"review"' not in compact


def test_m7_execution_doc_uses_profile_backed_one_command_gate() -> None:
    """M7 완료 절차가 수동 숫자 비교로 되돌아가지 않게 합니다."""

    text = _read(Path("docs/M7_SQLITE_MATERIALIZATION.md"))

    assert "validate_m7_real_run.py" in text
    assert "profile.json" in text
    assert "same-run" in text
    assert ".gate.json" in text
    assert "foreign_key_check" in text
    assert "integrity_check" in text


def test_m0_to_m7_visual_docs_exist_and_are_static() -> None:
    """복구한 M0~M7 HTML이 삭제되거나 fragment loader로 퇴행하지 않게 합니다."""

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
    assert milestones, "README milestone table could not be parsed"

    status_dir = Path("docs/status")
    for milestone in sorted(milestones):
        matches = list(status_dir.glob(f"{milestone}_*.html"))
        assert matches, f"{milestone} is DONE/CURRENT but has no docs/status/{milestone}_*.html"


def test_documentation_hub_links_all_milestone_visual_docs() -> None:
    """docs/index.html에서 복구한 M0~M7 시각 문서가 모두 발견되게 합니다."""

    index = _read(Path("docs/index.html"))
    for path in MILESTONE_HTML_DOCS:
        assert path.name in index, f"docs/index.html does not link {path.name}"


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
