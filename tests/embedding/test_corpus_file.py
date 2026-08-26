import json
from pathlib import Path

import pytest

from jira_collector.embedding.corpus import (
    EmbeddingCorpusRow,
    load_embedding_corpus_file,
)
from jira_collector.knowledge_db import KnowledgeDbError


def _row() -> EmbeddingCorpusRow:
    return EmbeddingCorpusRow(
        corpus_schema_version="0.1",
        text_profile="statement_v1",
        knowledge_item_id="ki_a",
        knowledge_attempt_id="ka_a",
        knowledge_generation_id="kg_a",
        issue_version_id="iv_a",
        jira_id="10001",
        category="key_findings",
        ordinal=0,
        embedding_text="테스트 문장",
        embedding_text_hash="0c3a6ee3716a1c95ee37f7c04f3c7b03383fe8815a83e6ba6ab3df6d1a856608",
    )


def test_load_embedding_corpus_file_validates_hash(tmp_path: Path) -> None:
    row = _row().to_dict()
    import hashlib

    row["embedding_text_hash"] = hashlib.sha256(
        row["embedding_text"].encode("utf-8")
    ).hexdigest()
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    loaded = load_embedding_corpus_file(path)

    assert len(loaded) == 1
    assert loaded[0].knowledge_item_id == "ki_a"
    assert loaded[0].embedding_text == "테스트 문장"


def test_load_embedding_corpus_file_rejects_tampered_text(tmp_path: Path) -> None:
    row = _row().to_dict()
    path = tmp_path / "corpus.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(KnowledgeDbError, match="embedding_text_hash"):
        load_embedding_corpus_file(path)
