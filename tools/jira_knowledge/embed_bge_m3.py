#!/usr/bin/env python3
"""M8-01 corpus를 사내 BGE-M3 API로 embedding하고 validated JSONL을 생성합니다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_collector.embedding import EmbeddingApiError
from jira_collector.embedding.config import EmbeddingSettingsError, load_embedding_settings
from jira_collector.embedding.runner import embed_corpus_file
from jira_collector.knowledge_db import KnowledgeDbError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, help="M8-01 corpus.statement_v1.jsonl")
    parser.add_argument("--output", required=True, help="validated embedding JSONL 출력 경로")
    parser.add_argument("--expected-count", type=int, help="Pilot expected corpus row 수")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--local-config", default="config/settings.local.yaml")
    parser.add_argument("--dotenv", default=".env")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    local_config = args.local_config if args.local_config else None
    dotenv = args.dotenv if args.dotenv else None
    try:
        settings = load_embedding_settings(
            args.config,
            local_config_path=local_config,
            dotenv_path=dotenv,
        )
        result = embed_corpus_file(
            args.corpus,
            args.output,
            settings,
            expected_count=args.expected_count,
        )
    except (
        EmbeddingApiError,
        EmbeddingSettingsError,
        KnowledgeDbError,
        ValueError,
        OSError,
    ) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(f"embedding_contract_hash: {result.embedding_contract_hash}")
    print(f"corpus_rows: {result.corpus_rows}")
    print(f"embedding_rows: {result.embedding_rows}")
    print(f"batch_count: {result.batch_count}")
    print(f"embedding_dimension: {result.embedding_dimension}")
    print(f"output: {result.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
