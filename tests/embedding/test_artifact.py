import json
from pathlib import Path

from jira_collector.embedding.artifact import (
    build_embedding_artifact_rows,
    export_embedding_artifact_atomic,
)
from jira_collector.embedding.contract import EmbeddingContract
from jira_collector.embedding.corpus import EmbeddingCorpusRow


def _corpus_row(item_id: str, text_hash: str) -> EmbeddingCorpusRow:
    return EmbeddingCorpusRow(
        corpus_schema_version="0.1",
        text_profile="statement_v1",
        knowledge_item_id=item_id,
        knowledge_attempt_id="ka_a",
        knowledge_generation_id="kg_a",
        issue_version_id="iv_a",
        jira_id="10001",
        category="key_findings",
        ordinal=0,
        embedding_text="테스트 문장",
        embedding_text_hash=text_hash,
    )


def test_artifact_rows_keep_mapping_and_deterministic_ids() -> None:
    contract = EmbeddingContract(
        text_profile="statement_v1",
        embedding_model_profile="test-profile",
        embedding_dimension=3,
    )
    corpus = (_corpus_row("ki_a", "hash-a"), _corpus_row("ki_b", "hash-b"))
    vectors = ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))

    first = build_embedding_artifact_rows(corpus, vectors, contract)
    second = build_embedding_artifact_rows(corpus, vectors, contract)

    assert first == second
    assert [row.knowledge_item_id for row in first] == ["ki_a", "ki_b"]
    assert all(row.embedding_id.startswith("emb_") for row in first)
    assert all(row.embedding_contract_hash.startswith("ec_") for row in first)
    assert all(row.embedding_dimension == 3 for row in first)


def test_atomic_export_writes_only_final_jsonl(tmp_path: Path) -> None:
    contract = EmbeddingContract(
        text_profile="statement_v1",
        embedding_model_profile="test-profile",
        embedding_dimension=3,
    )
    rows = build_embedding_artifact_rows(
        (_corpus_row("ki_a", "hash-a"),),
        ((1.0, 2.0, 3.0),),
        contract,
    )
    output = tmp_path / "embedding.jsonl"

    export_embedding_artifact_atomic(rows, output)

    assert output.is_file()
    assert not (tmp_path / "embedding.jsonl.tmp").exists()
    payload = json.loads(output.read_text(encoding="utf-8").strip())
    assert payload["knowledge_item_id"] == "ki_a"
    assert payload["vector"] == [1.0, 2.0, 3.0]
