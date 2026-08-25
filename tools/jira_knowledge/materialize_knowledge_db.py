#!/usr/bin/env python3
"""완료된 Jira Knowledge Run 하나를 SQLite Knowledge DB로 materialize한다."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_collector.knowledge_db import KnowledgeDbError, KnowledgeDbMaterializer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ANALYSIS/KNOWLEDGE 산출물을 SQLite Knowledge DB로 적재"
    )
    parser.add_argument("--run-id", required=True, help="대상 Pipeline Run ID")
    parser.add_argument("--data-root", default="data", help="프로젝트 data 루트")
    parser.add_argument(
        "--database",
        default="data/knowledge_db/jira_knowledge.sqlite3",
        help="생성/갱신할 SQLite 파일",
    )
    parser.add_argument("--skill-version", default="0.9")
    parser.add_argument("--runtime-version", default="0.9")
    parser.add_argument(
        "--model-profile",
        required=True,
        help="Knowledge 생성에 사용한 모델 프로필 식별자",
    )
    parser.add_argument("--review-schema-version", default="0.3")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    materializer = KnowledgeDbMaterializer(
        Path(args.data_root),
        Path(args.database),
        skill_version=args.skill_version,
        runtime_version=args.runtime_version,
        model_profile=args.model_profile,
        review_schema_version=args.review_schema_version,
    )
    try:
        result = materializer.materialize_run(args.run_id)
    except (KnowledgeDbError, ValueError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "database": str(result.database_path),
                "issue_count": result.issue_count,
                "generation_count": result.generation_count,
                "attempt_count": result.attempt_count,
                "knowledge_item_count": result.knowledge_item_count,
                "evidence_count": result.evidence_count,
                "review_count": result.review_count,
                "status": "completed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
