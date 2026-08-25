from __future__ import annotations

from jira_collector.knowledge_db import (
    KnowledgeContract,
    canonical_json,
    issue_version_id,
    knowledge_attempt_id,
    knowledge_generation_id,
    knowledge_item_id,
)


def test_canonical_json_is_order_independent() -> None:
    """Object key 입력 순서가 달라도 ID material 문자열은 같아야 합니다."""

    assert canonical_json({"b": 2, "a": 1}) == canonical_json({"a": 1, "b": 2})


def test_logical_ids_are_deterministic_and_full_sha256() -> None:
    """동일 Version/Contract/Attempt 위치가 매번 같은 full hash ID를 만드는지 확인합니다."""

    version_id = issue_version_id("10001", "sha256:abc")
    contract = KnowledgeContract("0.1", "0.9", "0.9", "test-profile")
    generation_id = knowledge_generation_id(version_id, contract.logical_hash())
    attempt_id = knowledge_attempt_id(generation_id, 2)
    item_id = knowledge_item_id(attempt_id, "key_findings", 0)

    assert version_id == issue_version_id("10001", "sha256:abc")
    assert contract.logical_hash() == KnowledgeContract(
        "0.1", "0.9", "0.9", "test-profile"
    ).logical_hash()
    assert version_id.startswith("iv_") and len(version_id) == 67
    assert generation_id.startswith("kg_") and len(generation_id) == 67
    assert attempt_id.startswith("ka_") and len(attempt_id) == 67
    assert item_id.startswith("ki_") and len(item_id) == 67


def test_attempt_number_changes_item_lineage() -> None:
    """Statement 수정은 새 Attempt로 표현되므로 같은 category 위치도 다른 Item ID가 됩니다."""

    version_id = issue_version_id("10001", "sha256:abc")
    contract = KnowledgeContract("0.1", "0.9", "0.9", "test-profile")
    generation_id = knowledge_generation_id(version_id, contract.logical_hash())

    first = knowledge_item_id(
        knowledge_attempt_id(generation_id, 1),
        "issue_summary",
        0,
    )
    second = knowledge_item_id(
        knowledge_attempt_id(generation_id, 2),
        "issue_summary",
        0,
    )

    assert first != second
