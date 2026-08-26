from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from jira_collector.rate_limiter import IntervalRateLimiter

from .artifact import (
    EmbeddingArtifactRow,
    build_embedding_artifact_rows,
    export_embedding_artifact_atomic,
)
from .client import OpenAICompatibleEmbeddingClient, partition_batches
from .config import EmbeddingRuntimeSettings
from .contract import EmbeddingContract
from .corpus import EmbeddingCorpusRow, load_embedding_corpus_file


class _RateLimiter(Protocol):
    def wait(self) -> None: ...


@dataclass(frozen=True)
class EmbeddingRunResult:
    """M8 real embedding 실행 결과의 안전한 aggregate summary입니다."""

    corpus_rows: int
    embedding_rows: int
    batch_count: int
    embedding_dimension: int
    embedding_contract_hash: str
    output_path: Path


def embed_corpus_rows(
    corpus_rows: Sequence[EmbeddingCorpusRow],
    settings: EmbeddingRuntimeSettings,
    *,
    client: OpenAICompatibleEmbeddingClient | None = None,
    rate_limiter: _RateLimiter | None = None,
) -> tuple[EmbeddingArtifactRow, ...]:
    """Corpus 전체가 성공했을 때만 validated artifact rows를 반환합니다."""

    contract = _contract(settings)
    if any(row.text_profile != contract.text_profile for row in corpus_rows):
        raise ValueError("Corpus text_profile과 runtime embedding contract가 다릅니다.")
    active_client = client or OpenAICompatibleEmbeddingClient(
        settings.endpoint,
        model=settings.model,
        dimension=settings.dimension,
        api_key=settings.api_key,
        max_batch_size=settings.batch_size,
        max_attempts=settings.max_attempts,
        timeout_seconds=settings.timeout_seconds,
        backoff_initial_seconds=settings.backoff_initial_seconds,
        verify_ssl=settings.verify_ssl,
    )
    limiter = rate_limiter or IntervalRateLimiter(settings.requests_per_minute)

    vectors: list[tuple[float, ...]] = []
    for batch in partition_batches(corpus_rows, settings.batch_size):
        limiter.wait()
        result = active_client.embed([row.embedding_text for row in batch])
        vectors.extend(result.vectors)
    return build_embedding_artifact_rows(corpus_rows, vectors, contract)


def embed_corpus_file(
    corpus_path: str | Path,
    output_path: str | Path,
    settings: EmbeddingRuntimeSettings,
    *,
    expected_count: int | None = None,
    client: OpenAICompatibleEmbeddingClient | None = None,
    rate_limiter: _RateLimiter | None = None,
) -> EmbeddingRunResult:
    """M8 corpus JSONL을 embedding하고 성공한 전체 결과만 final JSONL로 publish합니다."""

    corpus_rows = load_embedding_corpus_file(corpus_path)
    if expected_count is not None and len(corpus_rows) != expected_count:
        raise ValueError(
            f"corpus row count 불일치: expected={expected_count}, actual={len(corpus_rows)}"
        )
    artifact_rows = embed_corpus_rows(
        corpus_rows,
        settings,
        client=client,
        rate_limiter=rate_limiter,
    )
    destination = export_embedding_artifact_atomic(artifact_rows, output_path)
    contract_hash = _contract(settings).logical_hash()
    batch_count = len(partition_batches(corpus_rows, settings.batch_size))
    return EmbeddingRunResult(
        corpus_rows=len(corpus_rows),
        embedding_rows=len(artifact_rows),
        batch_count=batch_count,
        embedding_dimension=settings.dimension,
        embedding_contract_hash=contract_hash,
        output_path=destination,
    )


def _contract(settings: EmbeddingRuntimeSettings) -> EmbeddingContract:
    return EmbeddingContract(
        text_profile=settings.text_profile,
        embedding_model=settings.model,
        embedding_model_profile=settings.model_profile,
        embedding_dimension=settings.dimension,
    )
