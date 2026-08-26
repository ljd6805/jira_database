from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import faiss
import numpy as np

from jira_collector.embedding.artifact import EmbeddingArtifactRow
from jira_collector.embedding.validation import validate_embedding_artifact
from jira_collector.knowledge_db import KnowledgeDbError

from .contract import (
    CANONICAL_ORDER,
    RETRIEVAL_SCHEMA_VERSION,
    RetrievalContract,
    faiss_index_id,
)
from .source import load_embedding_artifact, sha256_file


INDEX_FILENAME = "index.faiss"
MAPPING_FILENAME = "index.mapping.jsonl"
MANIFEST_FILENAME = "index.manifest.json"


@dataclass(frozen=True)
class RetrievalMappingRow:
    """FAISS 내부 position을 stable Knowledge identity로 되돌리는 sidecar 행입니다."""

    faiss_position: int
    embedding_id: str
    knowledge_item_id: str
    knowledge_attempt_id: str
    knowledge_generation_id: str
    issue_version_id: str
    category: str
    ordinal: int
    embedding_text_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalManifest:
    """M9 index set의 계약, 입력 snapshot, 파일 무결성을 기록합니다."""

    retrieval_schema_version: str
    retrieval_contract_version: str
    retrieval_contract_hash: str
    faiss_index_id: str
    index_type: str
    metric: str
    normalization: str
    canonical_order: str
    vector_count: int
    dimension: int
    source_embedding_contract_hash: str
    source_embedding_artifact_sha256: str
    mapping_sha256: str
    faiss_binary_sha256: str
    faiss_version: str
    embedding_model: str
    embedding_model_profile: str
    query_text_profile: str
    default_top_k: int
    score_threshold_policy: str
    rerank_policy: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalBuildResult:
    """M9 index build 결과를 secret/raw text 없이 요약합니다."""

    vector_count: int
    dimension: int
    retrieval_contract_hash: str
    faiss_index_id: str
    index_path: Path
    mapping_path: Path
    manifest_path: Path


def build_retrieval_artifacts(
    corpus_path: str | Path,
    embedding_path: str | Path,
    output_dir: str | Path,
    *,
    expected_count: int | None = None,
    expected_dimension: int | None = None,
    default_top_k: int = 3,
) -> RetrievalBuildResult:
    """Validated M8 embedding snapshot에서 exact cosine FAISS artifact를 만듭니다."""

    validation = validate_embedding_artifact(
        corpus_path,
        embedding_path,
        expected_count=expected_count,
        expected_dimension=expected_dimension,
    )
    if not validation.passed:
        raise KnowledgeDbError("M8 embedding artifact integrity Gate를 통과하지 못했습니다.")

    rows = load_embedding_artifact(embedding_path)
    ordered_rows = tuple(sorted(rows, key=lambda row: row.embedding_id))
    contract = _retrieval_contract_from_source(ordered_rows, default_top_k)
    source_sha256 = sha256_file(embedding_path)
    contract_hash = contract.logical_hash()
    index_id = faiss_index_id(source_sha256, contract)

    vectors = _normalized_vectors(ordered_rows, contract.dimension)
    index = faiss.IndexFlatIP(contract.dimension)
    index.add(vectors)

    mappings = tuple(
        _mapping_row(position, row)
        for position, row in enumerate(ordered_rows)
    )

    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    index_path = destination / INDEX_FILENAME
    mapping_path = destination / MAPPING_FILENAME
    manifest_path = destination / MANIFEST_FILENAME
    index_tmp = destination / f"{INDEX_FILENAME}.tmp"
    mapping_tmp = destination / f"{MAPPING_FILENAME}.tmp"
    manifest_tmp = destination / f"{MANIFEST_FILENAME}.tmp"

    try:
        faiss.write_index(index, str(index_tmp))
        mapping_tmp.write_text(
            "".join(_mapping_json_line(row) for row in mappings),
            encoding="utf-8",
        )
        _validate_temp_artifacts(index_tmp, mappings, contract.dimension)

        manifest = RetrievalManifest(
            retrieval_schema_version=RETRIEVAL_SCHEMA_VERSION,
            retrieval_contract_version=contract.retrieval_contract_version,
            retrieval_contract_hash=contract_hash,
            faiss_index_id=index_id,
            index_type=contract.index_type,
            metric=contract.metric,
            normalization=contract.index_normalization,
            canonical_order=CANONICAL_ORDER,
            vector_count=len(ordered_rows),
            dimension=contract.dimension,
            source_embedding_contract_hash=ordered_rows[0].embedding_contract_hash,
            source_embedding_artifact_sha256=source_sha256,
            mapping_sha256=sha256_file(mapping_tmp),
            faiss_binary_sha256=sha256_file(index_tmp),
            faiss_version=str(getattr(faiss, "__version__", "unknown")),
            embedding_model=contract.embedding_model,
            embedding_model_profile=contract.embedding_model_profile,
            query_text_profile=contract.query_text_profile,
            default_top_k=contract.default_top_k,
            score_threshold_policy=contract.score_threshold_policy,
            rerank_policy=contract.rerank_policy,
        )
        manifest_tmp.write_text(_manifest_json(manifest), encoding="utf-8")

        # manifest를 마지막에 교체합니다. 중간 crash가 나면 기존 manifest의 hash와
        # 새 index/mapping이 맞지 않아 loader가 해당 artifact를 거부합니다.
        os.replace(index_tmp, index_path)
        os.replace(mapping_tmp, mapping_path)
        os.replace(manifest_tmp, manifest_path)
    finally:
        for temporary in (index_tmp, mapping_tmp, manifest_tmp):
            if temporary.exists():
                temporary.unlink()

    return RetrievalBuildResult(
        vector_count=len(ordered_rows),
        dimension=contract.dimension,
        retrieval_contract_hash=contract_hash,
        faiss_index_id=index_id,
        index_path=index_path,
        mapping_path=mapping_path,
        manifest_path=manifest_path,
    )


def _retrieval_contract_from_source(
    rows: Sequence[EmbeddingArtifactRow],
    default_top_k: int,
) -> RetrievalContract:
    if not rows:
        raise KnowledgeDbError("Retrieval source embedding이 비어 있습니다.")

    first = rows[0]
    expected = (
        first.embedding_contract_hash,
        first.embedding_model,
        first.embedding_model_profile,
        first.embedding_dimension,
    )
    for row in rows[1:]:
        current = (
            row.embedding_contract_hash,
            row.embedding_model,
            row.embedding_model_profile,
            row.embedding_dimension,
        )
        if current != expected:
            raise KnowledgeDbError("M9 source에 서로 다른 embedding contract가 섞여 있습니다.")

    return RetrievalContract(
        embedding_model=first.embedding_model,
        embedding_model_profile=first.embedding_model_profile,
        dimension=first.embedding_dimension,
        default_top_k=default_top_k,
    )


def _normalized_vectors(
    rows: Sequence[EmbeddingArtifactRow],
    dimension: int,
) -> np.ndarray:
    vectors = np.asarray([row.vector for row in rows], dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape != (len(rows), dimension):
        raise KnowledgeDbError(
            f"Retrieval vector shape 불일치: expected=({len(rows)}, {dimension}), actual={vectors.shape}"
        )
    if not np.isfinite(vectors).all():
        raise KnowledgeDbError("Retrieval source vector에 non-finite 값이 있습니다.")

    normalized = np.ascontiguousarray(vectors.copy(), dtype=np.float32)
    norms = np.linalg.norm(normalized, axis=1)
    if np.any(norms == 0.0):
        raise KnowledgeDbError("Retrieval source에 zero vector가 있습니다.")
    faiss.normalize_L2(normalized)
    return normalized


def _mapping_row(position: int, row: EmbeddingArtifactRow) -> RetrievalMappingRow:
    return RetrievalMappingRow(
        faiss_position=position,
        embedding_id=row.embedding_id,
        knowledge_item_id=row.knowledge_item_id,
        knowledge_attempt_id=row.knowledge_attempt_id,
        knowledge_generation_id=row.knowledge_generation_id,
        issue_version_id=row.issue_version_id,
        category=row.category,
        ordinal=row.ordinal,
        embedding_text_hash=row.embedding_text_hash,
    )


def _validate_temp_artifacts(
    index_path: Path,
    mappings: Sequence[RetrievalMappingRow],
    dimension: int,
) -> None:
    index = faiss.read_index(str(index_path))
    if index.d != dimension:
        raise KnowledgeDbError(
            f"FAISS dimension 불일치: expected={dimension}, actual={index.d}"
        )
    if index.ntotal != len(mappings):
        raise KnowledgeDbError(
            f"FAISS/mapping count 불일치: index={index.ntotal}, mapping={len(mappings)}"
        )

    for position in range(index.ntotal):
        vector = np.asarray(index.reconstruct(position), dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if not math.isfinite(norm) or not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise KnowledgeDbError(
                f"FAISS vector L2 normalization 실패: position={position}, norm={norm}"
            )


def _mapping_json_line(row: RetrievalMappingRow) -> str:
    return json.dumps(
        row.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


def _manifest_json(manifest: RetrievalManifest) -> str:
    return json.dumps(
        manifest.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
