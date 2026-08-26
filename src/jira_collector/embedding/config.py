from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv

from .client import DEFAULT_MAX_BATCH_SIZE
from .contract import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_MODEL_PROFILE,
)
from .corpus import TEXT_PROFILE_STATEMENT_V1


class EmbeddingSettingsError(ValueError):
    """Embedding runtime 설정이 누락되거나 잘못됐을 때 발생합니다."""


@dataclass(frozen=True)
class EmbeddingRuntimeSettings:
    endpoint: str
    api_key: str | None
    provider: str
    model: str
    model_profile: str
    text_profile: str
    dimension: int
    batch_size: int
    requests_per_minute: int
    verify_ssl: bool
    timeout_seconds: float
    max_attempts: int
    backoff_initial_seconds: float


def load_embedding_settings(
    config_path: str | Path = "config/settings.yaml",
    *,
    local_config_path: str | Path | None = "config/settings.local.yaml",
    dotenv_path: str | Path | None = ".env",
    env: Mapping[str, str] | None = None,
) -> EmbeddingRuntimeSettings:
    """Jira 인증과 독립적으로 BGE-M3 runtime 설정만 읽습니다."""

    if dotenv_path is not None:
        load_dotenv(Path(dotenv_path), override=False)
    environment: Mapping[str, str] = os.environ if env is None else env

    raw = _load_yaml(Path(config_path))
    if local_config_path is not None:
        local_path = Path(local_config_path)
        if local_path.exists():
            raw = _deep_merge(raw, _load_yaml(local_path))
    embedding = raw.get("embedding", {})
    if not isinstance(embedding, dict):
        raise EmbeddingSettingsError("embedding 설정은 object여야 합니다.")

    endpoint = str(environment.get("BGE_M3_ENDPOINT", "")).strip()
    if not endpoint:
        raise EmbeddingSettingsError("필수 환경 변수 BGE_M3_ENDPOINT가 비어 있습니다.")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EmbeddingSettingsError("BGE_M3_ENDPOINT는 http:// 또는 https:// URL이어야 합니다.")

    provider = str(embedding.get("provider", "openai_compatible")).strip()
    if provider != "openai_compatible":
        raise EmbeddingSettingsError(f"지원하지 않는 embedding.provider입니다: {provider}")

    batch_size = int(embedding.get("batch_size", DEFAULT_MAX_BATCH_SIZE))
    if not 1 <= batch_size <= DEFAULT_MAX_BATCH_SIZE:
        raise EmbeddingSettingsError(
            f"embedding.batch_size는 1~{DEFAULT_MAX_BATCH_SIZE}여야 합니다."
        )
    dimension = int(embedding.get("dimension", DEFAULT_EMBEDDING_DIMENSION))
    if dimension < 1:
        raise EmbeddingSettingsError("embedding.dimension은 1 이상이어야 합니다.")

    rate = embedding.get("rate_limit", {})
    timeout = embedding.get("timeout", {})
    retry = embedding.get("retry", {})
    tls = embedding.get("tls", {})
    for label, value in (
        ("embedding.rate_limit", rate),
        ("embedding.timeout", timeout),
        ("embedding.retry", retry),
        ("embedding.tls", tls),
    ):
        if not isinstance(value, dict):
            raise EmbeddingSettingsError(f"{label}은 object여야 합니다.")

    requests_per_minute = int(rate.get("requests_per_minute", 200))
    if requests_per_minute < 1:
        raise EmbeddingSettingsError("embedding.rate_limit.requests_per_minute는 1 이상이어야 합니다.")
    max_attempts = int(retry.get("max_attempts", 3))
    if max_attempts < 1:
        raise EmbeddingSettingsError("embedding.retry.max_attempts는 1 이상이어야 합니다.")
    verify_ssl = tls.get("verify_ssl", True)
    if not isinstance(verify_ssl, bool):
        raise EmbeddingSettingsError("embedding.tls.verify_ssl은 bool이어야 합니다.")

    api_key = str(environment.get("BGE_M3_API_KEY", "")).strip() or None
    return EmbeddingRuntimeSettings(
        endpoint=endpoint,
        api_key=api_key,
        provider=provider,
        model=_required_text(embedding.get("model", DEFAULT_EMBEDDING_MODEL), "embedding.model"),
        model_profile=_required_text(
            embedding.get("model_profile", DEFAULT_MODEL_PROFILE),
            "embedding.model_profile",
        ),
        text_profile=_required_text(
            embedding.get("text_profile", TEXT_PROFILE_STATEMENT_V1),
            "embedding.text_profile",
        ),
        dimension=dimension,
        batch_size=batch_size,
        requests_per_minute=requests_per_minute,
        verify_ssl=verify_ssl,
        timeout_seconds=float(timeout.get("read_seconds", 60)),
        max_attempts=max_attempts,
        backoff_initial_seconds=float(retry.get("backoff_initial_seconds", 1)),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise EmbeddingSettingsError(f"설정 파일을 찾을 수 없습니다: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EmbeddingSettingsError(f"YAML 설정을 읽을 수 없습니다: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise EmbeddingSettingsError(f"설정 최상위 값은 object여야 합니다: {path}")
    return loaded


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingSettingsError(f"{label}은 비어 있지 않은 문자열이어야 합니다.")
    return value.strip()
