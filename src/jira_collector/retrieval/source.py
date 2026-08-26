from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from jira_collector.embedding.artifact import EmbeddingArtifactRow
from jira_collector.knowledge_db import KnowledgeDbError


_EMBEDDING_FIELDS = {
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


def load_embedding_artifact(path: str | Path) -> tuple[EmbeddingArtifactRow, ...]:
    """M8 final JSONL을 M9가 사용할 typed row로 읽습니다."""

    source = Path(path).resolve()
    if not source.is_file():
        raise KnowledgeDbError(f"Embedding artifact 파일이 없습니다: {source}")

    rows: list[EmbeddingArtifactRow] = []
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
        rows.append(_parse_row(document, line_no))

    if not rows:
        raise KnowledgeDbError(f"Embedding artifact가 비어 있습니다: {source}")
    return tuple(rows)


def sha256_file(path: str | Path) -> str:
    """큰 artifact도 메모리에 전부 올리지 않고 SHA-256을 계산합니다."""

    source = Path(path).resolve()
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_row(document: object, line_no: int) -> EmbeddingArtifactRow:
    if not isinstance(document, dict) or set(document) != _EMBEDDING_FIELDS:
        raise KnowledgeDbError(f"Embedding artifact 필드가 계약과 다릅니다: line={line_no}")

    dimension = _required_int(document, "embedding_dimension", line_no, minimum=1)
    vector_raw = document.get("vector")
    if not isinstance(vector_raw, list) or len(vector_raw) != dimension:
        raise KnowledgeDbError(f"Embedding vector dimension이 잘못됐습니다: line={line_no}")

    vector: list[float] = []
    for value in vector_raw:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise KnowledgeDbError(f"Embedding vector 값이 숫자가 아닙니다: line={line_no}")
        number = float(value)
        if not math.isfinite(number):
            raise KnowledgeDbError(f"Embedding vector에 non-finite 값이 있습니다: line={line_no}")
        vector.append(number)

    if not any(value != 0.0 for value in vector):
        raise KnowledgeDbError(f"Embedding vector가 zero vector입니다: line={line_no}")

    ordinal = _required_int(document, "ordinal", line_no, minimum=0)
    return EmbeddingArtifactRow(
        embedding_schema_version=_required_text(document, "embedding_schema_version", line_no),
        embedding_contract_version=_required_text(document, "embedding_contract_version", line_no),
        embedding_contract_hash=_required_text(document, "embedding_contract_hash", line_no),
        embedding_id=_required_text(document, "embedding_id", line_no),
        knowledge_item_id=_required_text(document, "knowledge_item_id", line_no),
        knowledge_attempt_id=_required_text(document, "knowledge_attempt_id", line_no),
        knowledge_generation_id=_required_text(document, "knowledge_generation_id", line_no),
        issue_version_id=_required_text(document, "issue_version_id", line_no),
        jira_id=_required_text(document, "jira_id", line_no),
        category=_required_text(document, "category", line_no),
        ordinal=ordinal,
        text_profile=_required_text(document, "text_profile", line_no),
        embedding_text_hash=_required_text(document, "embedding_text_hash", line_no),
        embedding_model=_required_text(document, "embedding_model", line_no),
        embedding_model_profile=_required_text(document, "embedding_model_profile", line_no),
        embedding_dimension=dimension,
        vector=tuple(vector),
    )


def _required_text(document: dict[str, object], key: str, line_no: int) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeDbError(f"Embedding {key}가 비어 있습니다: line={line_no}")
    return value.strip()


def _required_int(
    document: dict[str, object],
    key: str,
    line_no: int,
    *,
    minimum: int,
) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise KnowledgeDbError(f"Embedding {key}가 잘못됐습니다: line={line_no}")
    return value
