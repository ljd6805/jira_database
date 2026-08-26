#!/usr/bin/env python3
"""M7 SQLite에서 M8 active accepted embedding corpus JSONL을 생성합니다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_collector.embedding import TEXT_PROFILE_STATEMENT_V1, export_embedding_corpus
from jira_collector.knowledge_db import KnowledgeDbError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="M7 SQLite DB 경로")
    parser.add_argument("--output", required=True, help="M8 corpus JSONL 출력 경로")
    parser.add_argument("--text-profile", default=TEXT_PROFILE_STATEMENT_V1)
    parser.add_argument("--expected-count", type=int, help="Pilot 등에서 기대 corpus row 수")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rows = export_embedding_corpus(
            args.database,
            args.output,
            text_profile=args.text_profile,
        )
    except (KnowledgeDbError, ValueError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    if args.expected_count is not None and len(rows) != args.expected_count:
        print(
            f"오류: corpus row count 불일치: expected={args.expected_count}, actual={len(rows)}",
            file=sys.stderr,
        )
        return 1

    print(f"corpus_schema_version: {rows[0].corpus_schema_version if rows else '0.1'}")
    print(f"text_profile: {args.text_profile}")
    print(f"corpus_rows: {len(rows)}")
    print(f"output: {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
