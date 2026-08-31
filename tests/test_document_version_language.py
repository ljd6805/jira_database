from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def read_doc(relative_path: str) -> str:
    return (DOCS / relative_path).read_text(encoding="utf-8")


def test_version_guide_is_linked_from_hub() -> None:
    hub = read_doc("index.html")
    assert (DOCS / "VERSION_TERMINOLOGY_GUIDE.html").exists()
    assert 'href="VERSION_TERMINOLOGY_GUIDE.html"' in hub
    assert "현재 Sync 규칙 · 개정 3" in hub
    assert "현재 State 설계 · 개정 3" in hub


def test_shared_shell_explains_independent_version_tracks() -> None:
    script = read_doc("assets/document-navigation.js")
    required = (
        "숫자가 더 크다고 다른 종류의 문서보다 더 최신이라는 뜻이 아닙니다",
        "현재 운영 Sync Contract · 개정 3",
        "현재 Operational State Schema · 개정 3",
        "Knowledge DB Schema · 개정 1",
        "semantic_v2",
        "과거 설계 보관본 · 현재 구현 기준 아님",
    )
    for phrase in required:
        assert phrase in script


def test_current_two_loop_docs_do_not_claim_old_state_revision() -> None:
    paths = (
        "architecture/jira_operational_two_loop_architecture.html",
        "architecture/jira_sync_contract_easy_guide.html",
        "architecture/jira_sync_contract_explained.html",
        "architecture/jira_sync_state_schema_decision1_storage_location.html",
        "architecture/jira_sync_state_schema_decision2_entity_layout.html",
        "architecture/jira_sync_state_schema_decision3_columns_status.html",
        "architecture/jira_sync_state_schema_decision4_transaction_boundary.html",
    )
    stale_phrases = (
        "현재 Schema v2",
        "공식 Contract v2",
        "Sync Contract v2 Easy Guide",
        "Intermediate Version supersede",
        "STATE_SCHEMA_VERSION = 2",
    )
    for path in paths:
        text = read_doc(path)
        for phrase in stale_phrases:
            assert phrase not in text, f"{path}: stale phrase {phrase!r}"


def test_current_claim_gate_contains_latest_only_conditions() -> None:
    text = read_doc("architecture/jira_sync_state_schema_contract.html")
    required = (
        "last_source_committed_run_id = last_observed_source_run_id",
        "work_status IN ('pending','failed')",
        "superseded_by_work_item_id IS NULL",
    )
    for phrase in required:
        assert phrase in text


def test_historical_baselines_are_explicitly_not_current() -> None:
    paths = (
        "architecture/jira_sync_contract_v2_baseline.html",
        "architecture/jira_sync_state_schema_contract_v1_baseline.html",
        "architecture/jira_sync_state_schema_contract_v2_baseline.html",
    )
    for path in paths:
        text = read_doc(path)
        assert "현재 구현 기준" in text
        assert "과거" in text


def test_internal_version_names_are_explained() -> None:
    id_doc = read_doc("architecture/jira_sync_state_schema_decision6_id_key_strategy.html")
    sync_doc = read_doc("architecture/jira_sync_contract.html")
    assert "ID 생성 알고리즘의 기술 버전" in id_doc
    assert "Source 변경 판별 hash profile 이름" in sync_doc
