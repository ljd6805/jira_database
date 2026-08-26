from __future__ import annotations

import hashlib
from dataclasses import dataclass

from jira_collector.embedding.contract import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MODEL_PROFILE,
)
from jira_collector.knowledge_db.ids import ID_SCHEMA_VERSION, canonical_json


RETRIEVAL_CONTRACT_VERSION = "0.1"
RETRIEVAL_SCHEMA_VERSION = "0.1"
DEFAULT_INDEX_TYPE = "IndexFlatIP"
DEFAULT_METRIC = "cosine"
DEFAULT_NORMALIZATION = "l2"
DEFAULT_QUERY_TEXT_PROFILE = "raw_query_v1"
DEFAULT_TOP_K = 3
DEFAULT_SCORE_THRESHOLD_POLICY = "none"
DEFAULT_RERANK_POLICY = "none"
CANONICAL_ORDER = "embedding_id_asc"


@dataclass(frozen=True)
class RetrievalContract:
    """M9 검색 동작을 재현하기 위한 logical contract입니다."""

    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_model_profile: str = DEFAULT_MODEL_PROFILE
    dimension: int = DEFAULT_EMBEDDING_DIMENSION
    index_type: str = DEFAULT_INDEX_TYPE
    metric: str = DEFAULT_METRIC
    index_normalization: str = DEFAULT_NORMALIZATION
    query_normalization: str = DEFAULT_NORMALIZATION
    query_text_profile: str = DEFAULT_QUERY_TEXT_PROFILE
    default_top_k: int = DEFAULT_TOP_K
    score_threshold_policy: str = DEFAULT_SCORE_THRESHOLD_POLICY
    rerank_policy: str = DEFAULT_RERANK_POLICY
    retrieval_contract_version: str = RETRIEVAL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        """Pilot baseline에서 허용하는 명시적 검색 계약만 받습니다."""

        for label, value in (
            ("embedding_model", self.embedding_model),
            ("embedding_model_profile", self.embedding_model_profile),
            ("index_type", self.index_type),
            ("metric", self.metric),
            ("index_normalization", self.index_normalization),
            ("query_normalization", self.query_normalization),
            ("query_text_profile", self.query_text_profile),
            ("score_threshold_policy", self.score_threshold_policy),
            ("rerank_policy", self.rerank_policy),
            ("retrieval_contract_version", self.retrieval_contract_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label}은 비어 있지 않은 문자열이어야 합니다.")

        if self.dimension < 1:
            raise ValueError("dimension은 1 이상이어야 합니다.")
        if self.default_top_k < 1:
            raise ValueError("default_top_k는 1 이상이어야 합니다.")

        # M9 Pilot에서 검증할 exact cosine baseline을 의도치 않게 바꾸지 않습니다.
        if self.index_type != DEFAULT_INDEX_TYPE:
            raise ValueError(f"M9 baseline index_type은 {DEFAULT_INDEX_TYPE}이어야 합니다.")
        if self.metric != DEFAULT_METRIC:
            raise ValueError(f"M9 baseline metric은 {DEFAULT_METRIC}이어야 합니다.")
        if self.index_normalization != DEFAULT_NORMALIZATION:
            raise ValueError("M9 baseline index_normalization은 l2여야 합니다.")
        if self.query_normalization != DEFAULT_NORMALIZATION:
            raise ValueError("M9 baseline query_normalization은 l2여야 합니다.")
        if self.score_threshold_policy != DEFAULT_SCORE_THRESHOLD_POLICY:
            raise ValueError("M9 baseline score threshold는 none이어야 합니다.")
        if self.rerank_policy != DEFAULT_RERANK_POLICY:
            raise ValueError("M9 baseline rerank policy는 none이어야 합니다.")

    def logical_hash(self) -> str:
        """같은 검색 동작 계약에 항상 같은 rc_ ID를 부여합니다."""

        return _logical_id(
            "rc_",
            "retrieval_contract",
            {
                "retrieval_contract_version": self.retrieval_contract_version,
                "index_type": self.index_type,
                "metric": self.metric,
                "index_normalization": self.index_normalization,
                "query_normalization": self.query_normalization,
                "query_text_profile": self.query_text_profile,
                "default_top_k": self.default_top_k,
                "score_threshold_policy": self.score_threshold_policy,
                "rerank_policy": self.rerank_policy,
                "embedding_model": self.embedding_model,
                "embedding_model_profile": self.embedding_model_profile,
                "dimension": self.dimension,
            },
        )


def faiss_index_id(
    source_embedding_artifact_sha256: str,
    contract: RetrievalContract,
) -> str:
    """Source embedding snapshot + index build profile에서 fi_ ID를 만듭니다."""

    if not isinstance(source_embedding_artifact_sha256, str) or not source_embedding_artifact_sha256.strip():
        raise ValueError("source_embedding_artifact_sha256은 비어 있지 않아야 합니다.")
    return _logical_id(
        "fi_",
        "faiss_index",
        {
            "source_embedding_artifact_sha256": source_embedding_artifact_sha256.strip(),
            "index_type": contract.index_type,
            "metric": contract.metric,
            "normalization": contract.index_normalization,
            "dimension": contract.dimension,
        },
    )


def _logical_id(prefix: str, kind: str, material: dict[str, object]) -> str:
    """기존 logical ID와 동일한 canonical JSON + full SHA-256 규칙을 사용합니다."""

    value = {
        "id_schema_version": ID_SCHEMA_VERSION,
        "kind": kind,
        **material,
    }
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return prefix + digest
