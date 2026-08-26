from jira_collector.embedding.contract import EmbeddingContract, embedding_id


def test_embedding_contract_and_id_are_deterministic() -> None:
    contract = EmbeddingContract(
        text_profile="statement_v1",
        embedding_model_profile="internal-bge-m3-unversioned",
    )

    first_contract = contract.logical_hash()
    second_contract = contract.logical_hash()
    first_embedding = embedding_id("ki_a", "abc123", first_contract)
    second_embedding = embedding_id("ki_a", "abc123", second_contract)

    assert first_contract == second_contract
    assert first_contract.startswith("ec_")
    assert first_embedding == second_embedding
    assert first_embedding.startswith("emb_")


def test_embedding_identity_changes_when_contract_or_text_changes() -> None:
    base = EmbeddingContract(
        text_profile="statement_v1",
        embedding_model_profile="profile-a",
    ).logical_hash()
    changed_profile = EmbeddingContract(
        text_profile="statement_v1",
        embedding_model_profile="profile-b",
    ).logical_hash()

    assert base != changed_profile
    assert embedding_id("ki_a", "hash-a", base) != embedding_id("ki_a", "hash-b", base)
    assert embedding_id("ki_a", "hash-a", base) != embedding_id(
        "ki_a", "hash-a", changed_profile
    )
