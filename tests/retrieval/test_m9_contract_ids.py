from jira_collector.retrieval.contract import RetrievalContract, faiss_index_id


def test_retrieval_contract_and_index_ids_are_deterministic() -> None:
    contract = RetrievalContract(
        embedding_model="BAAI/bge-m3",
        embedding_model_profile="test-profile",
        dimension=3,
        default_top_k=3,
    )

    first_contract_id = contract.logical_hash()
    second_contract_id = contract.logical_hash()
    first_index_id = faiss_index_id("abc123", contract)
    second_index_id = faiss_index_id("abc123", contract)

    assert first_contract_id == second_contract_id
    assert first_contract_id.startswith("rc_")
    assert first_index_id == second_index_id
    assert first_index_id.startswith("fi_")


def test_index_identity_changes_when_source_embedding_snapshot_changes() -> None:
    contract = RetrievalContract(
        embedding_model_profile="test-profile",
        dimension=3,
    )

    assert faiss_index_id("source-a", contract) != faiss_index_id("source-b", contract)


def test_baseline_rejects_unapproved_index_type() -> None:
    try:
        RetrievalContract(index_type="IndexHNSWFlat")
    except ValueError as exc:
        assert "IndexFlatIP" in str(exc)
    else:
        raise AssertionError("M9 baseline should reject unapproved index types")
