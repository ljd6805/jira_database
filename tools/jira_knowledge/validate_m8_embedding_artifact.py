#!/usr/bin/env python3
"""M8 final embedding JSONL의 count/mapping/identity/vector 계약을 검증합니다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_collector.embedding.validation import validate_embedding_artifact
from jira_collector.knowledge_db import KnowledgeDbError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--embeddings", required=True)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--expected-dimension", type=int, default=1024)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = validate_embedding_artifact(
            args.corpus,
            args.embeddings,
            expected_count=args.expected_count,
            expected_dimension=args.expected_dimension,
        )
    except (KnowledgeDbError, ValueError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(f"validation: {'PASS' if result.passed else 'FAIL'}")
    print(f"corpus_rows: {result.corpus_rows}")
    print(f"embedding_rows: {result.embedding_rows}")
    print(f"unique_knowledge_item_ids: {result.unique_knowledge_item_ids}")
    print(f"unique_embedding_ids: {result.unique_embedding_ids}")
    print(f"contract_count: {result.contract_count}")
    print(f"mapping_failure_count: {result.mapping_failure_count}")
    print(f"identity_failure_count: {result.identity_failure_count}")
    print(f"dimension_failure_count: {result.dimension_failure_count}")
    print(f"non_finite_vector_count: {result.non_finite_vector_count}")
    print(f"zero_norm_vector_count: {result.zero_norm_vector_count}")
    print(f"temp_artifact_exists: {str(result.temp_artifact_exists).lower()}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
