from __future__ import annotations

import argparse
from pathlib import Path

from jira_collector.state_schema import (
    StateSchemaError,
    migrate_legacy_state_database,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="legacy collector.db를 Operational State Schema v3로 명시적으로 Migration합니다.",
    )
    parser.add_argument(
        "--database",
        default="data/state/collector.db",
        help="대상 collector.db 경로",
    )
    parser.add_argument(
        "--backup",
        help="선택 backup 파일 경로. 생략하면 timestamp가 포함된 .bak 파일을 생성합니다.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_path = Path(args.database)
    backup_path = Path(args.backup) if args.backup else None

    try:
        result = migrate_legacy_state_database(
            database_path,
            backup_path=backup_path,
        )
    except StateSchemaError as exc:
        print(f"STATE_MIGRATION = FAIL\nreason = {exc}")
        return 1

    print("STATE_MIGRATION = PASS")
    print(f"database = {result.database_path}")
    print(f"from_version = {result.from_version}")
    print(f"to_version = {result.to_version}")
    print(f"migrated = {str(result.migrated).lower()}")
    print(f"source_fingerprint = {result.source_fingerprint}")
    if result.backup_path is not None:
        print(f"backup = {result.backup_path}")
    else:
        print("backup = not_required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
