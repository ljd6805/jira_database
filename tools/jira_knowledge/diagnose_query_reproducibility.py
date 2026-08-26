#!/usr/bin/env python3
"""같은 query를 반복 embedding/search하여 M9 query 재현성 문제를 진단합니다.

실제 query text나 Jira-derived Knowledge text는 출력하지 않고 hash/score/ID만 출력합니다.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_collector.embedding import EmbeddingApiError
from jira_collector.embedding.config import EmbeddingSettingsError, load_embedding_settings
from jira_collector.knowledge_db import KnowledgeDbError
from jira_collector.retrieval import embed_query_text, load_retrieval_searcher


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, help="M9 index artifact 디렉터리")
    parser.add_argument("--query", required=True, help="동일성 검증할 질문 문자열")
    parser.add_argument("--repeat", type=int, default=2, help="동일 query 반복 API 호출 수")
    parser.add_argument("--top-k", type=int, default=3, help="각 호출의 비교할 Top-k")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--local-config", default="config/settings.local.yaml")
    parser.add_argument("--dotenv", default=".env")
    return parser


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.repeat < 2:
        print("오류: --repeat는 2 이상이어야 합니다.", file=sys.stderr)
        return 1
    if args.top_k < 1:
        print("오류: --top-k는 1 이상이어야 합니다.", file=sys.stderr)
        return 1

    query = args.query.strip()
    if not query:
        print("오류: --query가 비어 있습니다.", file=sys.stderr)
        return 1

    try:
        searcher = load_retrieval_searcher(args.artifact_dir)
        settings = load_embedding_settings(
            args.config,
            local_config_path=args.local_config or None,
            dotenv_path=args.dotenv or None,
        )

        vectors: list[np.ndarray] = []
        rankings: list[tuple[str, ...]] = []
        scores_list: list[tuple[float, ...]] = []

        print(f"query_text_sha256: {_sha256_bytes(query.encode('utf-8'))}")
        print(f"repeat: {args.repeat}")

        for iteration in range(1, args.repeat + 1):
            vector = np.asarray(
                embed_query_text(query, searcher.manifest, settings),
                dtype=np.float32,
            )
            vector_hash = _sha256_bytes(vector.tobytes(order="C"))
            norm = float(np.linalg.norm(vector))
            candidates = searcher.search_vector(vector, top_k=args.top_k)
            ranking = tuple(candidate.knowledge_item_id for candidate in candidates)
            scores = tuple(candidate.score for candidate in candidates)
            vectors.append(vector)
            rankings.append(ranking)
            scores_list.append(scores)

            print(f"run={iteration} vector_sha256={vector_hash} norm={norm:.9f}")
            for candidate in candidates:
                print(
                    f"  rank={candidate.rank} score={candidate.score:.6f} "
                    f"faiss_position={candidate.faiss_position} "
                    f"embedding_id={candidate.embedding_id} "
                    f"knowledge_item_id={candidate.knowledge_item_id}"
                )

        baseline = vectors[0]
        for iteration, vector in enumerate(vectors[1:], start=2):
            max_abs_diff = float(np.max(np.abs(baseline - vector)))
            baseline_norm = float(np.linalg.norm(baseline))
            current_norm = float(np.linalg.norm(vector))
            cosine = float(
                np.dot(baseline, vector) / (baseline_norm * current_norm)
            )
            print(
                f"compare=1_vs_{iteration} "
                f"vector_exact_equal={bool(np.array_equal(baseline, vector))} "
                f"max_abs_diff={max_abs_diff:.9g} "
                f"cosine={cosine:.9f} "
                f"ranking_equal={rankings[0] == rankings[iteration - 1]} "
                f"scores_exact_equal={scores_list[0] == scores_list[iteration - 1]}"
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
