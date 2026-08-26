from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

import requests


DEFAULT_MAX_BATCH_SIZE = 64
DEFAULT_MAX_ATTEMPTS = 3
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_T = TypeVar("_T")


class EmbeddingApiError(RuntimeError):
    """Embedding API 계약 또는 호출이 깨졌을 때 발생합니다."""


@dataclass(frozen=True)
class EmbeddingBatchResult:
    """한 HTTP batch의 input 순서로 정렬된 dense vector 결과입니다."""

    vectors: tuple[tuple[float, ...], ...]


class OpenAICompatibleEmbeddingClient:
    """OpenAI-compatible embeddings endpoint를 BGE-M3 계약으로 호출합니다."""

    def __init__(
        self,
        endpoint: str,
        *,
        model: str,
        dimension: int,
        api_key: str | None = None,
        headers: Mapping[str, str] | None = None,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        timeout_seconds: float = 60.0,
        backoff_initial_seconds: float = 1.0,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.endpoint = _required_text(endpoint, "endpoint")
        self.model = _required_text(model, "model")
        if dimension < 1:
            raise ValueError("dimension은 1 이상이어야 합니다.")
        if max_batch_size < 1 or max_batch_size > DEFAULT_MAX_BATCH_SIZE:
            raise ValueError(f"max_batch_size는 1~{DEFAULT_MAX_BATCH_SIZE}여야 합니다.")
        if max_attempts < 1:
            raise ValueError("max_attempts는 1 이상이어야 합니다.")
        self.dimension = dimension
        self.max_batch_size = max_batch_size
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.backoff_initial_seconds = backoff_initial_seconds
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        if headers:
            self.headers.update(headers)

    def embed(self, texts: Sequence[str]) -> EmbeddingBatchResult:
        """최대 64개 text를 호출하고 response index/dimension을 검증합니다."""

        inputs = tuple(_required_text(text, "embedding_text") for text in texts)
        if not inputs:
            raise ValueError("embedding input은 1개 이상이어야 합니다.")
        if len(inputs) > self.max_batch_size:
            raise ValueError(
                f"embedding batch가 너무 큽니다: {len(inputs)} > {self.max_batch_size}"
            )

        payload = {"model": self.model, "input": list(inputs)}
        response = self._post_with_retry(payload)
        return EmbeddingBatchResult(self._parse_vectors(response, len(inputs)))

    def _post_with_retry(self, payload: dict[str, Any]):
        delay = self.backoff_initial_seconds
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.post(
                    self.endpoint,
                    headers=self.headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
                self.sleeper(delay)
                delay *= 2
                continue

            if response.status_code in _RETRYABLE_STATUS:
                last_error = EmbeddingApiError(
                    f"Embedding API transient HTTP {response.status_code}"
                )
                if attempt == self.max_attempts:
                    break
                self.sleeper(delay)
                delay *= 2
                continue

            if not 200 <= response.status_code < 300:
                raise EmbeddingApiError(
                    f"Embedding API HTTP {response.status_code}; retry하지 않습니다."
                )
            return response

        raise EmbeddingApiError(
            f"Embedding API 호출이 {self.max_attempts}회 안에 성공하지 못했습니다."
        ) from last_error

    def _parse_vectors(self, response, input_count: int) -> tuple[tuple[float, ...], ...]:
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise EmbeddingApiError("Embedding API 응답이 JSON이 아닙니다.") from exc
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise EmbeddingApiError("Embedding API 응답에 data 배열이 없습니다.")

        mapped: dict[int, tuple[float, ...]] = {}
        for raw in body["data"]:
            if not isinstance(raw, dict):
                raise EmbeddingApiError("Embedding data item이 object가 아닙니다.")
            index = raw.get("index")
            if not isinstance(index, int) or isinstance(index, bool):
                raise EmbeddingApiError("Embedding data.index가 정수가 아닙니다.")
            if index < 0 or index >= input_count:
                raise EmbeddingApiError(f"Embedding response index 범위 오류: {index}")
            if index in mapped:
                raise EmbeddingApiError(f"Embedding response index 중복: {index}")
            mapped[index] = self._validate_vector(raw.get("embedding"), index)

        expected = set(range(input_count))
        actual = set(mapped)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise EmbeddingApiError(
                f"Embedding response index 불일치: missing={missing}, extra={extra}"
            )
        return tuple(mapped[index] for index in range(input_count))

    def _validate_vector(self, raw: Any, index: int) -> tuple[float, ...]:
        if not isinstance(raw, list):
            raise EmbeddingApiError(f"Embedding vector가 배열이 아닙니다: index={index}")
        if len(raw) != self.dimension:
            raise EmbeddingApiError(
                f"Embedding dimension 불일치: index={index}, "
                f"expected={self.dimension}, actual={len(raw)}"
            )
        values: list[float] = []
        for value in raw:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise EmbeddingApiError(
                    f"Embedding vector에 숫자가 아닌 값이 있습니다: index={index}"
                )
            values.append(float(value))
        return tuple(values)


def partition_batches(items: Sequence[_T], batch_size: int) -> tuple[tuple[_T, ...], ...]:
    """입력 순서를 유지하면서 지정 크기로 deterministic batch를 만듭니다."""

    if batch_size < 1 or batch_size > DEFAULT_MAX_BATCH_SIZE:
        raise ValueError(f"batch_size는 1~{DEFAULT_MAX_BATCH_SIZE}여야 합니다.")
    return tuple(
        tuple(items[start : start + batch_size])
        for start in range(0, len(items), batch_size)
    )


def _required_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}은 비어 있지 않은 문자열이어야 합니다.")
    return value.strip()
