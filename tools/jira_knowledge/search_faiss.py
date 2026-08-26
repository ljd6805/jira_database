#!/usr/bin/env python3
"""실제 BGE-M3 query embedding으로 M9 FAISS Top-k Knowledge 후보를 검색합니다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_collector.embedding import EmbeddingApiError, load_embedding_corpus_file
from jira_collector.embedding.config import EmbeddingSettingsError, load_embedding_settings
from jira_collector.knowledge_db import KnowledgeDbError
from jira_collector.retrieval import (
    embed_query_text,
    load_retrieval_searcher,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, help="M9 index artifact 디렉터리")
    parser.add_argument("--query", required=True, help="검색할 질문 문자열")
    parser.add_argument("--top-k", type=int, help="기본값은 manifest의 Top-k")
    parser.add_argument("--corpus", help="지정하면 결과 Knowledge text를 로컬 화면에 함께 표시")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--local-config", default="config/settings.local.yaml")
    parser.add_argument("--dotenv", default=".env")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        searcher = load_retrieval_searcher(args.artifact_dir)
        settings = load_embedding_settings(
            args.config,
            local_config_path=args.local_config or None,
            dotenv_path=args.dotenv or None,
        )
        query_vector = embed_query_text(args.query, searcher.manifest, settings)
        candidates = searcher.search_vector(query_vector, top_k=args.top_k)
        text_by_item = _load_text_lookup(args.corpus) if args.corpus else {}
    except (
        EmbeddingApiError,
        EmbeddingSettingsError,
        KnowledgeDbError,
        ValueError,
        OSError,
    ) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(f"top_k: {len(candidates)}")
    print(f"query_text_profile: {searcher.manifest.query_text_profile}")
    print(f"retrieval_contract_hash: {searcher.manifest.retrieval_contract_hash}")
    for candidate in candidates:
        print(
            f"rank={candidate.rank} score={candidate.score:.6f} "
            f"category={candidate.category} knowledge_item_id={candidate.knowledge_item_id}"
        )
        text = text_by_item.get(candidate.knowledge_item_id)
        if text is not None:
            print(f"  text: {text}")
    return 0


def _load_text_lookup(corpus_path: str) -> dict[str, str]:
    rows = load_embedding_corpus_file(corpus_path)
    return {row.knowledge_item_id: row.embedding_text for row in rows}


if __name__ == "__main__":
    raise SystemExit(main())
