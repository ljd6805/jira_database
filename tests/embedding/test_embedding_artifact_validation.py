import hashlib
import json
from pathlib import Path

from jira_collector.embedding.contract import EmbeddingContract, embedding_id
from jira_collector.embedding.validation import validate_embedding_artifact


def _write_corpus(path: Path) -> None:
    rows = []
    for index, text in enumerate(("alpha", "beta")):
        rows.append(
            {
                "corpus_schema_version": "0.1",
                "text_profile": "statement_v1",
                "knowledge_item_id": f"ki_{index}",
                "knowledge_attempt_id": "ka_1",
                "knowledge_generation_id": "kg_1",
                "issue_version_id": "iv_1",
                "jira_id": "10001",
                "category": "key_findings",
                "ordinal": index,
                "embedding_text": text,
                "embedding_text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_embeddings(path: Path) -> None:
    contract = EmbeddingContract(
        text_profile="statement_v1",
        embedding_model="BAAI/bge-m3",
        embedding_model_profile="test-profile",
        embedding_dimension=3,
    )
    contract_hash = contract.logical_hash()
    rows = []
    for index, text in enumerate(("alpha", "beta")):
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rows.append(
            {
                "embedding_schema_version": "0.1",
                "embedding_contract_version": "0.1",
                "embedding_contract_hash": contract_hash,
                "embedding_id": embedding_id(f"ki_{index}", text_hash, contract_hash),
                "knowledge_item_id": f"ki_{index}",
                "knowledge_attempt_id": "ka_1",
                "knowledge_generation_id": "kg_1",
                "issue_version_id": "iv_1",
                "jira_id": "10001",
                "category": "key_findings",
                "ordinal": index,
                "text_profile": "statement_v1",
                "embedding_text_hash": text_hash,
                "embedding_model": "BAAI/bge-m3",
                "embedding_model_profile": "test-profile",
                "embedding_dimension": 3,
                "vector": [1.0, 2.0, float(index + 1)],
            }
        )
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_valid_embedding_artifact_passes(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    embeddings = tmp_path / "embeddings.jsonl"
    _write_corpus(corpus)
    _write_embeddings(embeddings)

    result = validate_embedding_artifact(
        corpus,
        embeddings,
        expected_count=2,
        expected_dimension=3,
    )

    assert result.passed is True
    assert result.mapping_failure_count == 0
    assert result.identity_failure_count == 0
    assert result.dimension_failure_count == 0
    assert result.unique_knowledge_item_ids == 2
    assert result.unique_embedding_ids == 2
    assert result.contract_count == 1


def test_mapping_and_identity_corruption_fail(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    embeddings = tmp_path / "embeddings.jsonl"
    _write_corpus(corpus)
    _write_embeddings(embeddings)

    docs = [json.loads(line) for line in embeddings.read_text(encoding="utf-8").splitlines()]
    docs[0]["knowledge_item_id"] = "ki_wrong"
    embeddings.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in docs),
        encoding="utf-8",
    )

    result = validate_embedding_artifact(
        corpus,
        embeddings,
        expected_count=2,
        expected_dimension=3,
    )

    assert result.passed is False
    assert result.mapping_failure_count > 0
    assert result.identity_failure_count > 0
