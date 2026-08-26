from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import faiss
import numpy as np

from jira_collector.knowledge_db import KnowledgeDbError

from .artifact import INDEX_FILENAME, RetrievalManifest, RetrievalMappingRow
from .validation import (
    load_retrieval_manifest,
    load_retrieval_mapping,
    validate_retrieval_artifact,
)


@dataclass(frozen=True)
class RetrievalCandidate:
    """M10이 Knowledge/Evidence를 resolve할 수 있는 M9 검색 후보입니다."""

    rank: int
    score: float
    faiss_position: int
    embedding_id: str
    knowledge_item_id: str
    category: str


class RetrievalSearcher:
    """검증된 M9 artifact를 메모리에 올려 exact cosine Top-k를 수행합니다."""

    def __init__(
        self,
        index,
        mappings: Sequence[RetrievalMappingRow],
        manifest: RetrievalManifest,
    ) -> None:
        self._index = index
        self._mappings = tuple(mappings)
        self.manifest = manifest

    def search_vector(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int | None = None,
    ) -> tuple[RetrievalCandidate, ...]:
        """Query vector를 L2 normalize한 뒤 IndexFlatIP에서 Top-k를 찾습니다."""

        requested_top_k = self.manifest.default_top_k if top_k is None else top_k
        if not isinstance(requested_top_k, int) or isinstance(requested_top_k, bool) or requested_top_k < 1:
            raise ValueError("top_k는 1 이상의 정수여야 합니다.")

        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim != 1 or query.shape[0] != self.manifest.dimension:
            raise KnowledgeDbError(
                "Query vector dimension 불일치: "
                f"expected={self.manifest.dimension}, actual={query.shape}"
            )
        if not np.isfinite(query).all():
            raise KnowledgeDbError("Query vector에 non-finite 값이 있습니다.")
        norm = float(np.linalg.norm(query))
        if not math.isfinite(norm) or norm == 0.0:
            raise KnowledgeDbError("Query vector가 zero vector입니다.")

        normalized = np.ascontiguousarray(query.reshape(1, -1).copy(), dtype=np.float32)
        faiss.normalize_L2(normalized)
        effective_top_k = min(requested_top_k, int(self._index.ntotal))
        scores, positions = self._index.search(normalized, effective_top_k)

        candidates: list[RetrievalCandidate] = []
        for rank, (score, position) in enumerate(
            zip(scores[0].tolist(), positions[0].tolist()), start=1
        ):
            if position < 0:
                continue
            mapping = self._mappings[position]
            candidates.append(
                RetrievalCandidate(
                    rank=rank,
                    score=float(score),
                    faiss_position=int(position),
                    embedding_id=mapping.embedding_id,
                    knowledge_item_id=mapping.knowledge_item_id,
                    category=mapping.category,
                )
            )
        return tuple(candidates)


def load_retrieval_searcher(artifact_dir: str | Path) -> RetrievalSearcher:
    """Manifest/hash/mapping Gate를 통과한 artifact만 검색기로 엽니다."""

    validation = validate_retrieval_artifact(artifact_dir)
    if not validation.passed:
        raise KnowledgeDbError("Retrieval artifact integrity Gate를 통과하지 못했습니다.")

    directory = Path(artifact_dir).resolve()
    index = faiss.read_index(str(directory / INDEX_FILENAME))
    mappings = load_retrieval_mapping(directory)
    manifest = load_retrieval_manifest(directory)
    return RetrievalSearcher(index, mappings, manifest)
