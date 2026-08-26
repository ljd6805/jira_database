import hashlib

from jira_collector.embedding.client import EmbeddingBatchResult
from jira_collector.embedding.config import EmbeddingRuntimeSettings
from jira_collector.embedding.corpus import EmbeddingCorpusRow
from jira_collector.embedding.runner import embed_corpus_rows


class FakeClient:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self.batch_sizes = []

    def embed(self, texts):
        self.batch_sizes.append(len(texts))
        vectors = tuple(
            tuple(float(index + 1) for _ in range(self.dimension))
            for index, _ in enumerate(texts)
        )
        return EmbeddingBatchResult(vectors)


class FakeLimiter:
    def __init__(self) -> None:
        self.wait_count = 0

    def wait(self) -> None:
        self.wait_count += 1


def _settings() -> EmbeddingRuntimeSettings:
    return EmbeddingRuntimeSettings(
        endpoint="https://embedding.example/v1/embeddings",
        api_key=None,
        custom_headers={},
        provider="openai_compatible",
        model="BAAI/bge-m3",
        model_profile="test-profile",
        text_profile="statement_v1",
        dimension=3,
        batch_size=64,
        requests_per_minute=200,
        verify_ssl=True,
        timeout_seconds=60,
        max_attempts=3,
        backoff_initial_seconds=1,
    )


def _row(index: int) -> EmbeddingCorpusRow:
    text = f"문장 {index}"
    return EmbeddingCorpusRow(
        corpus_schema_version="0.1",
        text_profile="statement_v1",
        knowledge_item_id=f"ki_{index}",
        knowledge_attempt_id="ka_a",
        knowledge_generation_id="kg_a",
        issue_version_id="iv_a",
        jira_id="10001",
        category="key_findings",
        ordinal=index,
        embedding_text=text,
        embedding_text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def test_runner_partitions_285_rows_and_preserves_mapping() -> None:
    rows = tuple(_row(index) for index in range(285))
    client = FakeClient(dimension=3)
    limiter = FakeLimiter()

    artifacts = embed_corpus_rows(
        rows,
        _settings(),
        client=client,
        rate_limiter=limiter,
    )

    assert len(artifacts) == 285
    assert client.batch_sizes == [64, 64, 64, 64, 29]
    assert limiter.wait_count == 5
    assert [row.knowledge_item_id for row in artifacts] == [f"ki_{i}" for i in range(285)]
    assert all(row.embedding_dimension == 3 for row in artifacts)
    assert len({row.embedding_id for row in artifacts}) == 285
