from jira_collector.embedding.client import EmbeddingBatchResult
from jira_collector.embedding.config import EmbeddingRuntimeSettings
from jira_collector.knowledge_db import KnowledgeDbError
from jira_collector.retrieval.artifact import RetrievalManifest
from jira_collector.retrieval.query import embed_query_text


def _manifest() -> RetrievalManifest:
    return RetrievalManifest(
        retrieval_schema_version="0.1",
        retrieval_contract_version="0.1",
        retrieval_contract_hash="rc_test",
        faiss_index_id="fi_test",
        index_type="IndexFlatIP",
        metric="cosine",
        normalization="l2",
        canonical_order="embedding_id_asc",
        vector_count=3,
        dimension=3,
        source_embedding_contract_hash="ec_test",
        source_embedding_artifact_sha256="source",
        mapping_sha256="mapping",
        faiss_binary_sha256="index",
        faiss_version="test",
        embedding_model="BAAI/bge-m3",
        embedding_model_profile="test-profile",
        query_text_profile="raw_query_v1",
        default_top_k=3,
        score_threshold_policy="none",
        rerank_policy="none",
    )


def _settings(*, profile: str = "test-profile") -> EmbeddingRuntimeSettings:
    return EmbeddingRuntimeSettings(
        endpoint="https://example.invalid/v1/embeddings",
        api_key=None,
        custom_headers={},
        provider="openai_compatible",
        model="BAAI/bge-m3",
        model_profile=profile,
        text_profile="statement_v1",
        dimension=3,
        batch_size=64,
        requests_per_minute=200,
        verify_ssl=True,
        timeout_seconds=60.0,
        max_attempts=3,
        backoff_initial_seconds=1.0,
    )


def test_query_embedding_uses_raw_query_and_matching_runtime(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class FakeClient:
        def __init__(self, endpoint, **kwargs):
            observed["endpoint"] = endpoint
            observed["kwargs"] = kwargs

        def embed(self, texts):
            observed["texts"] = tuple(texts)
            return EmbeddingBatchResult(vectors=((1.0, 2.0, 3.0),))

    monkeypatch.setattr(
        "jira_collector.retrieval.query.OpenAICompatibleEmbeddingClient",
        FakeClient,
    )

    vector = embed_query_text("  테스트 질문  ", _manifest(), _settings())

    assert vector == (1.0, 2.0, 3.0)
    assert observed["texts"] == ("테스트 질문",)


def test_query_embedding_rejects_model_profile_mismatch() -> None:
    try:
        embed_query_text("질문", _manifest(), _settings(profile="other-profile"))
    except KnowledgeDbError as exc:
        assert "runtime contract" in str(exc)
    else:
        raise AssertionError("M9 query must reject a mismatched embedding profile")
