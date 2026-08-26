#!/usr/bin/env python3
"""M8 validated embedding artifact에서 M9 exact cosine FAISS index를 생성합니다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_collector.knowledge_db import KnowledgeDbError
from jira_collector.retrieval import (
    build_retrieval_artifacts,
    validate_retrieval_artifact,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, help="M8 corpus JSONL")
    parser.add_argument("--embeddings", required=True, help="M8 validated embedding JSONL")
    parser.add_argument("--output-dir", required=True, help="M9 index artifact 출력 디렉터리")
    parser.add_argument("--expected-count", type=int, help="예상 vector 수")
    parser.add_argument("--expected-dimension", type=int, help="예상 embedding dimension")
    parser.add_argument("--top-k", type=int, default=3, help="manifest 기본 Top-k")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_retrieval_artifacts(
            args.corpus,
            args.embeddings,
            args.output_dir,
            expected_count=args.expected_count,
            expected_dimension=args.expected_dimension,
            default_top_k=args.top_k,
        )
        validation = validate_retrieval_artifact(
            args.output_dir,
            embedding_path=args.embeddings,
            expected_count=args.expected_count,
            expected_dimension=args.expected_dimension,
        )
        if not validation.passed:
            raise KnowledgeDbError("최종 M9 retrieval artifact 검증이 실패했습니다.")
    except (KnowledgeDbError, ValueError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print("validation: PASS")
    print(f"vector_count: {result.vector_count}")
    print(f"dimension: {result.dimension}")
    print(f"retrieval_contract_hash: {result.retrieval_contract_hash}")
    print(f"faiss_index_id: {result.faiss_index_id}")
    print(f"mapping_failure_count: {validation.mapping_failure_count}")
    print(f"hash_failure_count: {validation.hash_failure_count}")
    print(f"normalization_failure_count: {validation.normalization_failure_count}")
    print(f"index: {result.index_path}")
    print(f"mapping: {result.mapping_path}")
    print(f"manifest: {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
