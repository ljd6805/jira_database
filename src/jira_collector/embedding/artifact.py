from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .contract import EmbeddingContract, embedding_id
from .corpus import EmbeddingCorpusRow


EMBEDDING_SCHEMA_VERSION = "0.1"


@dataclass(frozen=True)
class EmbeddingArtifactRow:
    """M9 FAISS 입력이 되는 Knowledge ↔ dense vector mapping 한 행입니다."""

    embedding_schema_version: str
    embedding_contract_version: str
    embedding_contract_hash: str
    embedding_id: str
    knowledge_item_id: str
    knowledge_attempt_id: str
    knowledge_generation_id: str
    issue_version_id: str
    jira_id: str
    category: str
    ordinal: int
    text_profile: str
    embedding_text_hash: str
    embedding_model: str
    embedding_model_profile: str
    embedding_dimension: int
    vector: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_embedding_artifact_rows(
    corpus_rows: Sequence[EmbeddingCorpusRow],
    vectors: Sequence[Sequence[float]],
    contract: EmbeddingContract,
) -> tuple[EmbeddingArtifactRow, ...]:
    """Corpus 순서를 보존하며 validated vector를 deterministic identity에 연결합니다."""

    if len(corpus_rows) != len(vectors):
        raise ValueError(
            f"corpus/vector count 불일치: corpus={len(corpus_rows)}, vectors={len(vectors)}"
        )
    contract_hash = contract.logical_hash()
    result: list[EmbeddingArtifactRow] = []
    for corpus, raw_vector in zip(corpus_rows, vectors):
        if corpus.text_profile != contract.text_profile:
            raise ValueError(
                "Corpus text_profile과 Embedding Contract가 다릅니다: "
                f"{corpus.text_profile} != {contract.text_profile}"
            )
        vector = tuple(float(value) for value in raw_vector)
        if len(vector) != contract.embedding_dimension:
            raise ValueError(
                "Embedding dimension 불일치: "
                f"expected={contract.embedding_dimension}, actual={len(vector)}"
            )
        result.append(
            EmbeddingArtifactRow(
                embedding_schema_version=EMBEDDING_SCHEMA_VERSION,
                embedding_contract_version=contract.embedding_contract_version,
                embedding_contract_hash=contract_hash,
                embedding_id=embedding_id(
                    corpus.knowledge_item_id,
                    corpus.embedding_text_hash,
                    contract_hash,
                ),
                knowledge_item_id=corpus.knowledge_item_id,
                knowledge_attempt_id=corpus.knowledge_attempt_id,
                knowledge_generation_id=corpus.knowledge_generation_id,
                issue_version_id=corpus.issue_version_id,
                jira_id=corpus.jira_id,
                category=corpus.category,
                ordinal=corpus.ordinal,
                text_profile=corpus.text_profile,
                embedding_text_hash=corpus.embedding_text_hash,
                embedding_model=contract.embedding_model,
                embedding_model_profile=contract.embedding_model_profile,
                embedding_dimension=contract.embedding_dimension,
                vector=vector,
            )
        )
    return tuple(result)


def export_embedding_artifact_atomic(
    rows: Sequence[EmbeddingArtifactRow],
    output_path: str | Path,
) -> Path:
    """전체 JSONL 작성이 성공했을 때만 final artifact로 atomic replace합니다."""

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    payload = "".join(_json_line(row) for row in rows)
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def _json_line(row: EmbeddingArtifactRow) -> str:
    return json.dumps(
        row.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
