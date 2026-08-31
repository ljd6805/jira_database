from __future__ import annotations

import argparse
import os
from pathlib import Path

from jira_collector.embedding import (
    EmbeddingSettingsError,
    OperationalEmbeddingWorker,
    load_embedding_settings,
)
from jira_collector.knowledge_db import KnowledgeDbError
from jira_collector.state_schema import StateMigrationRequiredError, StateSchemaError
from jira_collector.state_store import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Loop B의 latest-only Incremental Embedding stage를 실행합니다. "
            "Knowledge 완료 + Source-ready 최신 Work만 BGE-M3로 처리하고, "
            "FAISS/Atomic Publish는 다음 stage가 담당합니다."
        ),
    )
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--local-config", default="config/settings.local.yaml")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument(
        "--state-db",
        default="data/state/collector.db",
        help="Operational State DB 경로. 기본: data/state/collector.db",
    )
    parser.add_argument(
        "--knowledge-db",
        default=None,
        help=(
            "Knowledge DB 경로. 생략하면 JIRA_KNOWLEDGE_DB_PATH 환경 변수를 사용합니다."
        ),
    )
    parser.add_argument(
        "--artifact-root",
        default="data/embedding/operational",
        help="Work별 corpus/embedding staging root.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="한 Processing Run에서 순차 처리할 latest Embedding Work 수. 기본 1.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit <= 0:
        print("EMBEDDING_WORKER = FAIL")
        print("reason = --limit은 1 이상이어야 합니다.")
        return 1

    try:
        embedding_settings = load_embedding_settings(
            args.config,
            local_config_path=args.local_config,
            dotenv_path=args.dotenv,
        )
        knowledge_db_value = args.knowledge_db or os.environ.get("JIRA_KNOWLEDGE_DB_PATH")
        if not knowledge_db_value:
            raise ValueError(
                "Knowledge DB 경로가 필요합니다: --knowledge-db 또는 JIRA_KNOWLEDGE_DB_PATH"
            )
        state = StateStore(Path(args.state_db))
        worker = OperationalEmbeddingWorker(
            state,
            Path(knowledge_db_value),
            Path(args.artifact_root),
            embedding_settings,
        )
        result = worker.run(limit=args.limit)
    except StateMigrationRequiredError as exc:
        print("EMBEDDING_WORKER = BLOCKED")
        print(f"reason = {exc}")
        print(f"next = python tools/migrate_state_v3.py --database {args.state_db}")
        return 3
    except (
        EmbeddingSettingsError,
        KnowledgeDbError,
        StateSchemaError,
        OSError,
        ValueError,
    ) as exc:
        print("EMBEDDING_WORKER = FAIL")
        print(f"reason = {exc}")
        return 1

    outcome = "CHECKPOINTED" if result.embedding_completed_count else result.status.upper()
    print(f"EMBEDDING_WORKER = {outcome}")
    print(f"processing_run_id = {result.processing_run_id}")
    print(f"selected_count = {result.selected_count}")
    print(f"embedding_completed_count = {result.embedding_completed_count}")
    print(f"failed_count = {result.failed_count}")
    print(f"superseded_count = {result.superseded_count}")
    print(f"embedding_backlog_before = {result.embedding_backlog_before}")
    print(f"embedding_backlog_after = {result.embedding_backlog_after}")
    print(f"embedding_model = {embedding_settings.model}")
    print(f"embedding_dimension = {embedding_settings.dimension}")
    print("next_stage = Retrieval staging / Atomic Publish")
    return 0 if result.failed_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
