from __future__ import annotations

import argparse
import os
from pathlib import Path

from jira_collector.knowledge_db import KnowledgeDbError
from jira_collector.publishing import (
    OperationalPublishWorker,
    active_retrieval_artifact_dir,
)
from jira_collector.stale_recovery import recover_stale_inflight
from jira_collector.state_schema import StateMigrationRequiredError, StateSchemaError
from jira_collector.state_store import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "G4 Atomic Publish를 실행합니다. Embedding 완료 latest Work 하나로 "
            "검증된 Retrieval bundle을 staging한 뒤 Knowledge active 전환과 "
            "State published checkpoint를 한 cross-DB SQLite transaction으로 commit합니다."
        ),
    )
    parser.add_argument(
        "--state-db",
        default="data/state/collector.db",
        help="Operational State DB 경로.",
    )
    parser.add_argument(
        "--knowledge-db",
        default=None,
        help="Knowledge DB 경로. 생략하면 JIRA_KNOWLEDGE_DB_PATH를 사용합니다.",
    )
    parser.add_argument(
        "--embedding-root",
        default="data/embedding/operational",
        help="Work별 corpus/embeddings root.",
    )
    parser.add_argument(
        "--retrieval-root",
        default="data/retrieval/operational",
        help="Processing Run별 immutable Retrieval bundle root.",
    )
    parser.add_argument(
        "--default-top-k",
        type=int,
        default=3,
        help="FAISS Retrieval 기본 Top-k. 기본 3.",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=3600,
        help="중단된 publish running Work 복구 기준. 기본 3600초.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.default_top_k < 1:
        print("PUBLISH_WORKER = FAIL")
        print("reason = --default-top-k는 1 이상이어야 합니다.")
        return 1
    if args.stale_after_seconds < 0:
        print("PUBLISH_WORKER = FAIL")
        print("reason = --stale-after-seconds는 0 이상이어야 합니다.")
        return 1

    try:
        knowledge_db_value = args.knowledge_db or os.environ.get("JIRA_KNOWLEDGE_DB_PATH")
        if not knowledge_db_value:
            raise ValueError(
                "Knowledge DB 경로가 필요합니다: --knowledge-db 또는 JIRA_KNOWLEDGE_DB_PATH"
            )
        state = StateStore(Path(args.state_db))
        recovery = recover_stale_inflight(
            state,
            stage="publish",
            stale_after_seconds=args.stale_after_seconds,
        )
        worker = OperationalPublishWorker(
            state,
            Path(knowledge_db_value),
            Path(args.embedding_root),
            Path(args.retrieval_root),
            default_top_k=args.default_top_k,
        )
        result = worker.run()
        active_dir = (
            active_retrieval_artifact_dir(state, Path(args.retrieval_root))
            if result.published_count
            else None
        )
    except StateMigrationRequiredError as exc:
        print("PUBLISH_WORKER = BLOCKED")
        print(f"reason = {exc}")
        print(f"next = python tools/migrate_state_v3.py --database {args.state_db}")
        return 3
    except (KnowledgeDbError, StateSchemaError, OSError, sqlite_error(), ValueError) as exc:
        print("PUBLISH_WORKER = FAIL")
        print(f"reason = {exc}")
        return 1

    outcome = "PUBLISHED" if result.published_count else result.status.upper()
    print(f"PUBLISH_WORKER = {outcome}")
    print(f"processing_run_id = {result.processing_run_id}")
    print(f"stale_after_seconds = {args.stale_after_seconds}")
    print(f"stale_recovered_work_count = {recovery.recovered_work_count}")
    print(
        "stale_recovered_processing_run_count = "
        f"{recovery.recovered_processing_run_count}"
    )
    print(f"selected_count = {result.selected_count}")
    print(f"published_count = {result.published_count}")
    print(f"failed_count = {result.failed_count}")
    print(f"superseded_count = {result.superseded_count}")
    print(f"publish_backlog_before = {result.publish_backlog_before}")
    print(f"publish_backlog_after = {result.publish_backlog_after}")
    if result.publish_result is not None:
        published = result.publish_result
        print(f"knowledge_generation_id = {published.knowledge_generation_id}")
        print(f"faiss_index_id = {published.faiss_index_id}")
        print(f"vector_count = {published.vector_count}")
        print(f"retrieval_dimension = {published.dimension}")
        print(f"generation_count = {published.generation_count}")
        print(f"active_retrieval_dir = {active_dir}")
    print("next_stage = G4 real retrieval validation")
    return 0 if result.failed_count == 0 else 2


def sqlite_error():
    """argparse CLI의 except tuple에서 sqlite3.Error를 늦게 import하기 위한 helper입니다."""

    import sqlite3

    return sqlite3.Error


if __name__ == "__main__":
    raise SystemExit(main())
