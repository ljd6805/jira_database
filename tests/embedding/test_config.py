from pathlib import Path

import pytest

from jira_collector.embedding.config import (
    EmbeddingSettingsError,
    load_embedding_settings,
)


def _write_config(path: Path) -> None:
    path.write_text(
        """
embedding:
  provider: openai_compatible
  model: BAAI/bge-m3
  model_profile: test-profile
  text_profile: statement_v1
  dimension: 1024
  batch_size: 64
  tls:
    verify_ssl: false
  rate_limit:
    requests_per_minute: 200
  timeout:
    read_seconds: 30
  retry:
    max_attempts: 3
    backoff_initial_seconds: 1
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_load_embedding_settings_without_jira_credentials(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    _write_config(config)

    settings = load_embedding_settings(
        config,
        local_config_path=None,
        dotenv_path=None,
        env={
            "BGE_M3_ENDPOINT": "https://embedding.example/v1/embeddings",
            "BGE_M3_API_KEY": "secret",
        },
    )

    assert settings.endpoint.endswith("/v1/embeddings")
    assert settings.api_key == "secret"
    assert settings.model == "BAAI/bge-m3"
    assert settings.dimension == 1024
    assert settings.batch_size == 64
    assert settings.requests_per_minute == 200
    assert settings.verify_ssl is False
    assert settings.timeout_seconds == 30


def test_embedding_endpoint_is_required(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    _write_config(config)

    with pytest.raises(EmbeddingSettingsError, match="BGE_M3_ENDPOINT"):
        load_embedding_settings(
            config,
            local_config_path=None,
            dotenv_path=None,
            env={},
        )


def test_embedding_batch_cannot_exceed_64(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    _write_config(config)
    text = config.read_text(encoding="utf-8").replace("batch_size: 64", "batch_size: 65")
    config.write_text(text, encoding="utf-8")

    with pytest.raises(EmbeddingSettingsError, match="batch_size"):
        load_embedding_settings(
            config,
            local_config_path=None,
            dotenv_path=None,
            env={"BGE_M3_ENDPOINT": "https://embedding.example/v1/embeddings"},
        )
