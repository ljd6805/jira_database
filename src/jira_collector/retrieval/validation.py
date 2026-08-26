from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from jira_collector.knowledge_db import KnowledgeDbError

from .artifact import (
    INDEX_FILENAME,
    MANIFEST_FILENAME,
    MAPPING_FILENAME,
    RetrievalManifest,
    RetrievalMappingRow,
)
from .contract import CANONICAL_ORDER, RetrievalContract, faiss_index_id
from .source import load_embedding_artifact, sha256_file


_MAPPING_FIELDS = {
    "faiss_position",
    "embedding_id",
    "knowledge_item_id",
    "knowledge_attempt_id",
    "knowledge_generation_id",
    "issue_version_id",
    "category",
    "ordinal",
    "embedding_text_hash",
}
_MANIFEST_FIELDS = set(RetrievalManifest.__dataclass_fields__)


@dataclass(frozen=True)
class RetrievalArtifactValidation:
    """M9 final artifact가 검색에 안전한지 aggregate 수치로 표현합니다."""

    vector_count: int
    mapping_rows: int
    unique_embedding_ids: int
    unique_knowledge_item_ids: int
    contract_failure_count: int
    hash_failure_count: int
    mapping_failure_count: int
    dimension_failure_count: int
    normalization_failure_count: int
    temp_artifact_exists: bool

    @property
    def passed(self) -> bool:
        return (
            self.vector_count == self.mapping_rows
            and self.unique_embedding_ids == self.mapping_rows
            and self.unique_knowledge_item_ids == self.mapping_rows
            and self.contract_failure_count == 0
            and self.hash_failure_count == 0
            and self.mapping_failure_count == 0
            and self.dimension_failure_count == 0
            and self.normalization_failure_count == 0
            and not self.temp_artifact_exists
        )


def validate_retrieval_artifact(
    artifact_dir: str | Path,
    *,
    embedding_path: str | Path | None = None,
    expected_count: int | None = None,
    expected_dimension: int | None = None,
) -> RetrievalArtifactValidation:
    """FAISS binary, mapping, manifest와 선택적으로 M8 source까지 교차 검증합니다."""

    directory = Path(artifact_dir).resolve()
    manifest = load_retrieval_manifest(directory)
    mappings = load_retrieval_mapping(directory)
    index_path = directory / INDEX_FILENAME
    if not index_path.is_file():
        raise KnowledgeDbError(f"FAISS index 파일이 없습니다: {index_path}")
    index = faiss.read_index(str(index_path))

    contract_failures = _contract_failures(manifest, index)
    hash_failures = _hash_failures(directory, manifest)
    mapping_failures = _mapping_failures(mappings, manifest)
    dimension_failures = 0
    normalization_failures = 0

    if expected_count is not None:
        if manifest.vector_count != expected_count or index.ntotal != expected_count:
            mapping_failures += 1
    if expected_dimension is not None:
        if manifest.dimension != expected_dimension or index.d != expected_dimension:
            dimension_failures += 1

    if index.d != manifest.dimension:
        dimension_failures += 1
    if index.ntotal != manifest.vector_count:
        mapping_failures += 1

    normalization_failures += _normalization_failures(index)

    if embedding_path is not None:
        source_hash = sha256_file(embedding_path)
        if source_hash != manifest.source_embedding_artifact_sha256:
            hash_failures += 1
        source_rows = tuple(
            sorted(load_embedding_artifact(embedding_path), key=lambda row: row.embedding_id)
        )
        mapping_failures += _source_mapping_failures(mappings, source_rows)
        if source_rows and source_rows[0].embedding_contract_hash != manifest.source_embedding_contract_hash:
            contract_failures += 1

    temp_exists = any(
        (directory / f"{filename}.tmp").exists()
        for filename in (INDEX_FILENAME, MAPPING_FILENAME, MANIFEST_FILENAME)
    )
    return RetrievalArtifactValidation(
        vector_count=int(index.ntotal),
        mapping_rows=len(mappings),
        unique_embedding_ids=len({row.embedding_id for row in mappings}),
        unique_knowledge_item_ids=len({row.knowledge_item_id for row in mappings}),
        contract_failure_count=contract_failures,
        hash_failure_count=hash_failures,
        mapping_failure_count=mapping_failures,
        dimension_failure_count=dimension_failures,
        normalization_failure_count=normalization_failures,
        temp_artifact_exists=temp_exists,
    )


def load_retrieval_manifest(artifact_dir: str | Path) -> RetrievalManifest:
    """Manifest schema를 엄격히 확인하고 typed object로 변환합니다."""

    path = Path(artifact_dir).resolve() / MANIFEST_FILENAME
    if not path.is_file():
        raise KnowledgeDbError(f"Retrieval manifest가 없습니다: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KnowledgeDbError(f"Retrieval manifest JSON 파싱 실패: {exc}") from exc
    if not isinstance(document, dict) or set(document) != _MANIFEST_FIELDS:
        raise KnowledgeDbError("Retrieval manifest 필드가 계약과 다릅니다.")
    try:
        return RetrievalManifest(**document)
    except TypeError as exc:
        raise KnowledgeDbError(f"Retrieval manifest type 변환 실패: {exc}") from exc


def load_retrieval_mapping(artifact_dir: str | Path) -> tuple[RetrievalMappingRow, ...]:
    """Mapping JSONL을 읽고 position/ID 필드 타입을 검증합니다."""

    path = Path(artifact_dir).resolve() / MAPPING_FILENAME
    if not path.is_file():
        raise KnowledgeDbError(f"Retrieval mapping이 없습니다: {path}")

    rows: list[RetrievalMappingRow] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            document = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise KnowledgeDbError(f"Retrieval mapping JSONL 파싱 실패: line={line_no}: {exc}") from exc
        if not isinstance(document, dict) or set(document) != _MAPPING_FIELDS:
            raise KnowledgeDbError(f"Retrieval mapping 필드가 계약과 다릅니다: line={line_no}")
        rows.append(_mapping_from_document(document, line_no))

    if not rows:
        raise KnowledgeDbError(f"Retrieval mapping이 비어 있습니다: {path}")
    return tuple(rows)


def _contract_failures(manifest: RetrievalManifest, index) -> int:
    failures = 0
    try:
        contract = RetrievalContract(
            embedding_model=manifest.embedding_model,
            embedding_model_profile=manifest.embedding_model_profile,
            dimension=manifest.dimension,
            index_type=manifest.index_type,
            metric=manifest.metric,
            index_normalization=manifest.normalization,
            query_normalization=manifest.normalization,
            query_text_profile=manifest.query_text_profile,
            default_top_k=manifest.default_top_k,
            score_threshold_policy=manifest.score_threshold_policy,
            rerank_policy=manifest.rerank_policy,
            retrieval_contract_version=manifest.retrieval_contract_version,
        )
    except (TypeError, ValueError):
        return 1

    if contract.logical_hash() != manifest.retrieval_contract_hash:
        failures += 1
    if faiss_index_id(manifest.source_embedding_artifact_sha256, contract) != manifest.faiss_index_id:
        failures += 1
    if manifest.canonical_order != CANONICAL_ORDER:
        failures += 1
    if type(index).__name__ != manifest.index_type:
        failures += 1
    if getattr(index, "metric_type", None) != faiss.METRIC_INNER_PRODUCT:
        failures += 1
    return failures


def _hash_failures(directory: Path, manifest: RetrievalManifest) -> int:
    failures = 0
    if sha256_file(directory / INDEX_FILENAME) != manifest.faiss_binary_sha256:
        failures += 1
    if sha256_file(directory / MAPPING_FILENAME) != manifest.mapping_sha256:
        failures += 1
    return failures


def _mapping_failures(
    mappings: tuple[RetrievalMappingRow, ...],
    manifest: RetrievalManifest,
) -> int:
    failures = 0
    if len(mappings) != manifest.vector_count:
        failures += 1
    expected_positions = list(range(len(mappings)))
    if [row.faiss_position for row in mappings] != expected_positions:
        failures += 1
    embedding_ids = [row.embedding_id for row in mappings]
    if embedding_ids != sorted(embedding_ids):
        failures += 1
    if len(set(embedding_ids)) != len(embedding_ids):
        failures += 1
    if len({row.knowledge_item_id for row in mappings}) != len(mappings):
        failures += 1
    return failures


def _source_mapping_failures(mappings, source_rows) -> int:
    if len(mappings) != len(source_rows):
        return abs(len(mappings) - len(source_rows)) + 1

    failures = 0
    for mapping, source in zip(mappings, source_rows):
        expected = (
            source.embedding_id,
            source.knowledge_item_id,
            source.knowledge_attempt_id,
            source.knowledge_generation_id,
            source.issue_version_id,
            source.category,
            source.ordinal,
            source.embedding_text_hash,
        )
        actual = (
            mapping.embedding_id,
            mapping.knowledge_item_id,
            mapping.knowledge_attempt_id,
            mapping.knowledge_generation_id,
            mapping.issue_version_id,
            mapping.category,
            mapping.ordinal,
            mapping.embedding_text_hash,
        )
        if actual != expected:
            failures += 1
    return failures


def _normalization_failures(index) -> int:
    failures = 0
    for position in range(index.ntotal):
        vector = np.asarray(index.reconstruct(position), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if not math.isfinite(norm) or not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            failures += 1
    return failures


def _mapping_from_document(document: dict[str, object], line_no: int) -> RetrievalMappingRow:
    position = _required_int(document, "faiss_position", line_no, minimum=0)
    ordinal = _required_int(document, "ordinal", line_no, minimum=0)
    return RetrievalMappingRow(
        faiss_position=position,
        embedding_id=_required_text(document, "embedding_id", line_no),
        knowledge_item_id=_required_text(document, "knowledge_item_id", line_no),
        knowledge_attempt_id=_required_text(document, "knowledge_attempt_id", line_no),
        knowledge_generation_id=_required_text(document, "knowledge_generation_id", line_no),
        issue_version_id=_required_text(document, "issue_version_id", line_no),
        category=_required_text(document, "category", line_no),
        ordinal=ordinal,
        embedding_text_hash=_required_text(document, "embedding_text_hash", line_no),
    )


def _required_text(document: dict[str, object], key: str, line_no: int) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeDbError(f"Retrieval {key}가 비어 있습니다: line={line_no}")
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
        raise KnowledgeDbError(f"Retrieval {key}가 잘못됐습니다: line={line_no}")
    return value
