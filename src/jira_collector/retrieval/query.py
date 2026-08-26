from __future__ import annotations

from typing import Sequence

from jira_collector.embedding.client import OpenAICompatibleEmbeddingClient
from jira_collector.embedding.config import EmbeddingRuntimeSettings
from jira_collector.knowledge_db import KnowledgeDbError

from .artifact import RetrievalManifest


def embed_query_text(
    query_text: str,
    manifest: RetrievalManifest,
    settings: EmbeddingRuntimeSettings,
) -> tuple[float, ...]:
    """M9 query를 M8과 같은 BGE-M3 공간의 vector로 변환합니다."""

    query = query_text.strip()
    if not query:
        raise ValueError("query_text는 비어 있을 수 없습니다.")
    if manifest.query_text_profile != "raw_query_v1":
        raise KnowledgeDbError(
            f"지원하지 않는 query_text_profile입니다: {manifest.query_text_profile}"
        )

    _validate_runtime_contract(manifest, settings)
    client = OpenAICompatibleEmbeddingClient(
        settings.endpoint,
        model=settings.model,
        dimension=settings.dimension,
        api_key=settings.api_key,
        headers=settings.custom_headers,
        max_batch_size=settings.batch_size,
        max_attempts=settings.max_attempts,
        timeout_seconds=settings.timeout_seconds,
        backoff_initial_seconds=settings.backoff_initial_seconds,
        verify_ssl=settings.verify_ssl,
    )
    result = client.embed([query])
    if len(result.vectors) != 1:
        raise KnowledgeDbError(
            f"Query embedding 응답 개수가 1이 아닙니다: {len(result.vectors)}"
        )
    return tuple(float(value) for value in result.vectors[0])


def _validate_runtime_contract(
    manifest: RetrievalManifest,
    settings: EmbeddingRuntimeSettings,
) -> None:
    expected = (
        manifest.embedding_model,
        manifest.embedding_model_profile,
        manifest.dimension,
    )
    actual = (
        settings.model,
        settings.model_profile,
        settings.dimension,
    )
    if actual != expected:
        raise KnowledgeDbError(
            "Query embedding runtime contract가 M9 index source와 다릅니다: "
            f"expected={expected}, actual={actual}"
        )
