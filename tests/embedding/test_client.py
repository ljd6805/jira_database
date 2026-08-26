import pytest

from jira_collector.embedding.client import (
    EmbeddingApiError,
    OpenAICompatibleEmbeddingClient,
    partition_batches,
)


class FakeResponse:
    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls = []

    def post(self, endpoint, *, headers, json, timeout, verify):
        self.calls.append((endpoint, headers, json, timeout, verify))
        return self.responses.pop(0)


def _client(session, *, dimension: int = 3, max_attempts: int = 3, sleeper=lambda _: None):
    return OpenAICompatibleEmbeddingClient(
        "https://example.invalid/v1/embeddings",
        model="BAAI/bge-m3",
        dimension=dimension,
        session=session,
        max_attempts=max_attempts,
        sleeper=sleeper,
    )


def test_partition_285_rows_into_five_batches() -> None:
    batches = partition_batches(tuple(range(285)), 64)

    assert [len(batch) for batch in batches] == [64, 64, 64, 64, 29]
    assert tuple(value for batch in batches for value in batch) == tuple(range(285))


def test_response_index_restores_input_order() -> None:
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "data": [
                        {"index": 1, "embedding": [2, 2, 2]},
                        {"index": 0, "embedding": [1, 1, 1]},
                    ]
                },
            )
        ]
    )

    result = _client(session).embed(["first", "second"])

    assert result.vectors == ((1.0, 1.0, 1.0), (2.0, 2.0, 2.0))
    assert session.calls[0][2] == {
        "model": "BAAI/bge-m3",
        "input": ["first", "second"],
    }
    assert session.calls[0][4] is True


def test_dimension_mismatch_is_rejected() -> None:
    session = FakeSession(
        [FakeResponse(200, {"data": [{"index": 0, "embedding": [1, 2]}]})]
    )

    with pytest.raises(EmbeddingApiError, match="dimension 불일치"):
        _client(session, dimension=3).embed(["text"])


def test_missing_or_duplicate_response_index_is_rejected() -> None:
    duplicate = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "data": [
                        {"index": 0, "embedding": [1, 1, 1]},
                        {"index": 0, "embedding": [2, 2, 2]},
                    ]
                },
            )
        ]
    )

    with pytest.raises(EmbeddingApiError, match="index 중복"):
        _client(duplicate).embed(["first", "second"])


def test_retryable_http_status_retries_then_succeeds() -> None:
    delays = []
    session = FakeSession(
        [
            FakeResponse(429, {}),
            FakeResponse(503, {}),
            FakeResponse(200, {"data": [{"index": 0, "embedding": [1, 2, 3]}]}),
        ]
    )

    result = _client(session, sleeper=delays.append).embed(["text"])

    assert result.vectors == ((1.0, 2.0, 3.0),)
    assert len(session.calls) == 3
    assert delays == [1.0, 2.0]


def test_non_retryable_http_status_fails_immediately() -> None:
    session = FakeSession([FakeResponse(400, {})])

    with pytest.raises(EmbeddingApiError, match="HTTP 400"):
        _client(session).embed(["text"])

    assert len(session.calls) == 1


def test_batch_larger_than_64_is_rejected_before_http() -> None:
    session = FakeSession([])

    with pytest.raises(ValueError, match="batch가 너무 큽니다"):
        _client(session).embed(["x"] * 65)

    assert session.calls == []
