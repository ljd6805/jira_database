import hashlib
import json
from pathlib import Path

from jira_collector.embedding.contract import EmbeddingContract, embedding_id
from jira_collector.retrieval import (
    build_retrieval_artifacts,
    load_retrieval_manifest,
    load_retrieval_mapping,
    load_retrieval_searcher,
    validate_retrieval_artifact,
)


def _write_source_files(tmp_path: Path) -> tuple[Path, Path]:
    corpus_path = tmp_path / "corpus.jsonl"
    embedding_path = tmp_path / "embeddings.jsonl"
    contract = EmbeddingContract(
        text_profile="statement_v1",
        embedding_model="BAAI/bge-m3",
        embedding_model_profile="test-profile",
        embedding_dimension=3,
    )
    contract_hash = contract.logical_hash()

    samples = (
        ("ki_b", "beta", [0.8, 0.2, 0.0]),
        ("ki_c", "gamma", [0.0, 1.0, 0.0]),
        ("ki_a", "alpha", [1.0, 0.0, 0.0]),
    )
    corpus_rows = []
    embedding_rows = []
    for ordinal, (item_id, text, vector) in enumerate(samples):
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        common = {
            "knowledge_item_id": item_id,
            "knowledge_attempt_id": "ka_1",
            "knowledge_generation_id": "kg_1",
            "issue_version_id": "iv_1",
            "jira_id": "10001",
            "category": "key_findings",
            "ordinal": ordinal,
            "embedding_text_hash": text_hash,
        }
        corpus_rows.append(
            {
                "corpus_schema_version": "0.1",
                "text_profile": "statement_v1",
                "embedding_text": text,
                **common,
            }
        )
        embedding_rows.append(
            {
                "embedding_schema_version": "0.1",
                "embedding_contract_version": "0.1",
                "embedding_contract_hash": contract_hash,
                "embedding_id": embedding_id(item_id, text_hash, contract_hash),
                "text_profile": "statement_v1",
                "embedding_model": "BAAI/bge-m3",
                "embedding_model_profile": "test-profile",
                "embedding_dimension": 3,
                "vector": vector,
                **common,
            }
        )

    corpus_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in corpus_rows),
        encoding="utf-8",
    )
    embedding_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in embedding_rows),
        encoding="utf-8",
    )
    return corpus_path, embedding_path


def test_build_validate_and_exact_cosine_search(tmp_path: Path) -> None:
    corpus, embeddings = _write_source_files(tmp_path)
    output_dir = tmp_path / "index"

    result = build_retrieval_artifacts(
        corpus,
        embeddings,
        output_dir,
        expected_count=3,
        expected_dimension=3,
    )
    validation = validate_retrieval_artifact(
        output_dir,
        embedding_path=embeddings,
        expected_count=3,
        expected_dimension=3,
    )

    assert result.vector_count == 3
    assert validation.passed is True
    assert validation.mapping_failure_count == 0
    assert validation.hash_failure_count == 0
    assert validation.normalization_failure_count == 0

    mappings = load_retrieval_mapping(output_dir)
    embedding_ids = [row.embedding_id for row in mappings]
    assert embedding_ids == sorted(embedding_ids)
    assert [row.faiss_position for row in mappings] == [0, 1, 2]

    searcher = load_retrieval_searcher(output_dir)
    candidates = searcher.search_vector([1.0, 0.0, 0.0], top_k=3)
    assert [candidate.knowledge_item_id for candidate in candidates] == ["ki_a", "ki_b", "ki_c"]
    assert candidates[0].score > candidates[1].score > candidates[2].score


def test_rebuild_keeps_logical_ids_and_mapping_bytes(tmp_path: Path) -> None:
    corpus, embeddings = _write_source_files(tmp_path)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = build_retrieval_artifacts(corpus, embeddings, first_dir, expected_count=3, expected_dimension=3)
    second = build_retrieval_artifacts(corpus, embeddings, second_dir, expected_count=3, expected_dimension=3)
    first_manifest = load_retrieval_manifest(first_dir)
    second_manifest = load_retrieval_manifest(second_dir)

    assert first.retrieval_contract_hash == second.retrieval_contract_hash
    assert first.faiss_index_id == second.faiss_index_id
    assert first_manifest.retrieval_contract_hash == second_manifest.retrieval_contract_hash
    assert first_manifest.faiss_index_id == second_manifest.faiss_index_id
    assert (first_dir / "index.mapping.jsonl").read_bytes() == (second_dir / "index.mapping.jsonl").read_bytes()


def test_mapping_corruption_is_rejected(tmp_path: Path) -> None:
    corpus, embeddings = _write_source_files(tmp_path)
    output_dir = tmp_path / "index"
    build_retrieval_artifacts(corpus, embeddings, output_dir, expected_count=3, expected_dimension=3)

    mapping_path = output_dir / "index.mapping.jsonl"
    documents = [json.loads(line) for line in mapping_path.read_text(encoding="utf-8").splitlines()]
    documents[0]["knowledge_item_id"] = "ki_corrupted"
    mapping_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in documents),
        encoding="utf-8",
    )

    validation = validate_retrieval_artifact(
        output_dir,
        embedding_path=embeddings,
        expected_count=3,
        expected_dimension=3,
    )
    assert validation.passed is False
    assert validation.hash_failure_count > 0
    assert validation.mapping_failure_count > 0
