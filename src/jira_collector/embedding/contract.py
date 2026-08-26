from __future__ import annotations

import hashlib
from dataclasses import dataclass

from jira_collector.knowledge_db.ids import ID_SCHEMA_VERSION, canonical_json


EMBEDDING_CONTRACT_VERSION = "0.1"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_EMBEDDING_DIMENSION = 1024
DEFAULT_MODEL_PROFILE = "internal-bge-m3-unversioned"


@dataclass(frozen=True)
class EmbeddingContract:
    """Embedding artifact identity에 포함되는 재현성 계약입니다."""

    text_profile: str
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_model_profile: str = DEFAULT_MODEL_PROFILE
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION
    embedding_contract_version: str = EMBEDDING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        """빈 metadata와 잘못된 dimension을 identity material에 넣지 않습니다."""

        for label, value in (
            ("text_profile", self.text_profile),
            ("embedding_model", self.embedding_model),
            ("embedding_model_profile", self.embedding_model_profile),
            ("embedding_contract_version", self.embedding_contract_version),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{label}은 비어 있지 않은 문자열이어야 합니다.")
        if self.embedding_dimension < 1:
            raise ValueError("embedding_dimension은 1 이상이어야 합니다.")

    def logical_hash(self) -> str:
        """같은 embedding contract에 항상 같은 ec_ ID를 부여합니다."""

        return _logical_id(
            "ec_",
            "embedding_contract",
            {
                "embedding_contract_version": self.embedding_contract_version,
                "text_profile": self.text_profile,
                "embedding_model": self.embedding_model,
                "embedding_model_profile": self.embedding_model_profile,
                "embedding_dimension": self.embedding_dimension,
            },
        )


def embedding_id(
    knowledge_item_id: str,
    embedding_text_hash: str,
    contract_hash: str,
) -> str:
    """Knowledge Item + text + contract에서 deterministic embedding artifact ID를 만듭니다."""

    for label, value in (
        ("knowledge_item_id", knowledge_item_id),
        ("embedding_text_hash", embedding_text_hash),
        ("embedding_contract_hash", contract_hash),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label}은 비어 있지 않은 문자열이어야 합니다.")
    return _logical_id(
        "emb_",
        "embedding",
        {
            "knowledge_item_id": knowledge_item_id,
            "embedding_text_hash": embedding_text_hash,
            "embedding_contract_hash": contract_hash,
        },
    )


def _logical_id(prefix: str, kind: str, material: dict[str, object]) -> str:
    """M6 logical ID와 동일한 canonical JSON + full SHA-256 규칙을 사용합니다."""

    value = {
        "id_schema_version": ID_SCHEMA_VERSION,
        "kind": kind,
        **material,
    }
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return prefix + digest
