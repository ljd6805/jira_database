from __future__ import annotations

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

STALE_STATUS_MARKERS = (
    "M6 CURRENT",
    "M7 NEXT",
    "M7 PLAN",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
