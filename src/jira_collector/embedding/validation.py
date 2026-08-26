from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from jira_collector.knowledge_db import KnowledgeDbError

from .contract import EmbeddingContract, embedding_id
from .corpus import load_embedding_corpus_file


_ARTIFACT_FIELDS = {
    "embedding_schema_version",
    "embedding_contract_version",
    "embedding_contract_hash",
    "embedding_id",
    "knowledge_item_id",
    "knowledge_attempt_id",
    "knowledge_generation_id",
    "issue_version_id",
    "jira_id",
    "category",
    "ordinal",
    "text_profile",
    "embedding_text_hash",
    "embedding_model",
    "embedding_model_profile",
    "embedding_dimension",
    "vector",
}


@dataclass(frozen=True)
class EmbeddingArtifactValidation:
    corpus_rows: int
    embedding_rows: int
    unique_knowledge_item_ids: int
    unique_embedding_ids: int
    contract_count: int
    mapping_failure_count: int
    identity_failure_count: int
    dimension_failure_count: int
    non_finite_vector_count: int
    zero_norm_vector_count: int
    temp_artifact_exists: bool

    @property
    def passed(self) -> bool:
        return (
            self.corpus_rows == self.embedding_rows
            and self.unique_knowledge_item_ids == self.embedding_rows
            and self.unique_embedding_ids == self.embedding_rows
            and self.contract_count == 1
            and self.mapping_failure_count == 0
            and self.identity_failure_count == 0
            and self.dimension_failure_count == 0
            and self.non_finite_vector_count == 0
            and self.zero_norm_vector_count == 0
            and not self.temp_artifact_exists
        )


def validate_embedding_artifact(
    corpus_path: str | Path,
    embedding_path: str | Path,
    *,
    expected_count: int | None = None,
    expected_dimension: int | None = None,
) -> EmbeddingArtifactValidation:
    """M8 corpus와 final embedding JSONL의 mapping/identity/vector 계약을 검증합니다."""

    corpus_rows = load_embedding_corpus_file(corpus_path)
    documents = _load_artifact_documents(embedding_path)

    if expected_count is not None:
        if len(corpus_rows) != expected_count:
            raise KnowledgeDbError(
                f"corpus row count 불일치: expected={expected_count}, actual={len(corpus_rows)}"
            )
        if len(documents) != expected_count:
            raise KnowledgeDbError(
                f"embedding row count 불일치: expected={expected_count}, actual={len(documents)}"
            )

    item_ids: list[str] = []
    embedding_ids: list[str] = []
    contract_hashes: set[str] = set()
    mapping_failures = 0
    identity_failures = 0
    dimension_failures = 0
    non_finite_vectors = 0
    zero_norm_vectors = 0

    for index, document in enumerate(documents):
        corpus = corpus_rows[index] if index < len(corpus_rows) else None
        item_id = _required_text(document, "knowledge_item_id", index)
        current_embedding_id = _required_text(document, "embedding_id", index)
        contract_hash = _required_text(document, "embedding_contract_hash", index)
        item_ids.append(item_id)
        embedding_ids.append(current_embedding_id)
        contract_hashes.add(contract_hash)

        contract = EmbeddingContract(
            text_profile=_required_text(document, "text_profile", index),
            embedding_model=_required_text(document, "embedding_model", index),
            embedding_model_profile=_required_text(
                document, "embedding_model_profile", index
            ),
            embedding_dimension=_required_int(
                document, "embedding_dimension", index, minimum=1
            ),
            embedding_contract_version=_required_text(
                document, "embedding_contract_version", index
            ),
        )
        if contract.logical_hash() != contract_hash:
            identity_failures += 1

        if expected_dimension is not None and contract.embedding_dimension != expected_dimension:
            dimension_failures += 1

        vector = document.get("vector")
        if not isinstance(vector, list) or len(vector) != contract.embedding_dimension:
            dimension_failures += 1
            vector_values: list[float] = []
        else:
            vector_values = []
            bad_number = False
            for value in vector:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    bad_number = True
                    break
                number = float(value)
                if not math.isfinite(number):
                    bad_number = True
                    break
                vector_values.append(number)
            if bad_number:
                non_finite_vectors += 1
                vector_values = []

        if vector_values and math.sqrt(sum(value * value for value in vector_values)) == 0.0:
            zero_norm_vectors += 1

        expected_id = embedding_id(
            item_id,
            _required_text(document, "embedding_text_hash", index),
            contract_hash,
        )
        if current_embedding_id != expected_id:
            identity_failures += 1

        if corpus is None or not _mapping_matches(document, corpus):
            mapping_failures += 1

    if len(corpus_rows) != len(documents):
        mapping_failures += abs(len(corpus_rows) - len(documents))

    temp_path = Path(embedding_path).resolve().with_name(
        Path(embedding_path).name + ".tmp"
    )
    return EmbeddingArtifactValidation(
        corpus_rows=len(corpus_rows),
        embedding_rows=len(documents),
        unique_knowledge_item_ids=len(set(item_ids)),
        unique_embedding_ids=len(set(embedding_ids)),
        contract_count=len(contract_hashes),
        mapping_failure_count=mapping_failures,
        identity_failure_count=identity_failures,
        dimension_failure_count=dimension_failures,
        non_finite_vector_count=non_finite_vectors,
        zero_norm_vector_count=zero_norm_vectors,
        temp_artifact_exists=temp_path.exists(),
    )


def _load_artifact_documents(path: str | Path) -> tuple[dict[str, object], ...]:
    source = Path(path).resolve()
    if not source.is_file():
        raise KnowledgeDbError(f"Embedding artifact 파일이 없습니다: {source}")
    result: list[dict[str, object]] = []
    for line_no, raw_line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            document = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise KnowledgeDbError(
                f"Embedding JSONL 파싱 실패: line={line_no}: {exc}"
            ) from exc
        if not isinstance(document, dict) or set(document) != _ARTIFACT_FIELDS:
            raise KnowledgeDbError(
                f"Embedding artifact 필드가 계약과 다릅니다: line={line_no}"
            )
        result.append(document)
    if not result:
        raise KnowledgeDbError(f"Embedding artifact가 비어 있습니다: {source}")
    return tuple(result)


def _mapping_matches(document: dict[str, object], corpus) -> bool:
    return all(
        document.get(field) == getattr(corpus, field)
        for field in (
            "knowledge_item_id",
            "knowledge_attempt_id",
            "knowledge_generation_id",
            "issue_version_id",
            "jira_id",
            "category",
            "ordinal",
            "text_profile",
            "embedding_text_hash",
        )
    )


def _required_text(document: dict[str, object], key: str, index: int) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeDbError(f"Embedding {key}가 비어 있습니다: row={index}")
    return value.strip()


def _required_int(
    document: dict[str, object],
    key: str,
    index: int,
    *,
    minimum: int,
) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise KnowledgeDbError(f"Embedding {key}가 잘못됐습니다: row={index}")
    return value
