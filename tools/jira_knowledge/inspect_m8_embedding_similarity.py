#!/usr/bin/env python3
"""M8 embedding artifact의 작은 cosine similarity sanity check를 로컬에서 출력합니다."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--embeddings", required=True)
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=3)
    return parser


def _load_jsonl(path: str) -> list[dict[str, object]]:
    source = Path(path)
    rows = [
        json.loads(line)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ValueError(f"JSONL이 비어 있습니다: {source}")
    return rows


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("zero-norm vector는 cosine similarity를 계산할 수 없습니다.")
    return dot / (left_norm * right_norm)


def _sample_indices(size: int, count: int) -> list[int]:
    if count < 1:
        raise ValueError("sample-count는 1 이상이어야 합니다.")
    count = min(count, size)
    if count == 1:
        return [0]
    return sorted({round(index * (size - 1) / (count - 1)) for index in range(count)})


def main() -> int:
    args = build_parser().parse_args()
    corpus = _load_jsonl(args.corpus)
    embeddings = _load_jsonl(args.embeddings)
    if len(corpus) != len(embeddings):
        raise ValueError(
            f"corpus/embedding row count 불일치: {len(corpus)} != {len(embeddings)}"
        )
    if args.top_k < 1:
        raise ValueError("top-k는 1 이상이어야 합니다.")

    vectors: list[list[float]] = []
    for index, row in enumerate(embeddings):
        vector = row.get("vector")
        if not isinstance(vector, list):
            raise ValueError(f"vector가 배열이 아닙니다: row={index}")
        vectors.append([float(value) for value in vector])

    for sample_no, seed_index in enumerate(
        _sample_indices(len(corpus), args.sample_count), start=1
    ):
        seed = corpus[seed_index]
        print(f"\n=== SAMPLE {sample_no} / row {seed_index} ===")
        print(f"seed_category: {seed.get('category')}")
        print(f"seed_text: {seed.get('embedding_text')}")

        scored = []
        for candidate_index, candidate_vector in enumerate(vectors):
            if candidate_index == seed_index:
                continue
            scored.append(
                (
                    _cosine(vectors[seed_index], candidate_vector),
                    candidate_index,
                )
            )
        scored.sort(reverse=True)
        for rank, (score, candidate_index) in enumerate(scored[: args.top_k], start=1):
            candidate = corpus[candidate_index]
            print(
                f"top{rank}: score={score:.4f} "
                f"category={candidate.get('category')} "
                f"text={candidate.get('embedding_text')}"
            )

    print("\n판정 방법: 각 seed와 top-k 문장이 의미상 관련 있어 보이는지 사람이 확인합니다.")
    print("이 도구는 FAISS를 만들지 않으며 M8의 소규모 quality sanity check 전용입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
