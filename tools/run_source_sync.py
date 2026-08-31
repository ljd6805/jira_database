from __future__ import annotations

import argparse
import logging
from pathlib import Path

from jira_collector.jira_client import JiraClient, JiraClientError
from jira_collector.raw_store import RawStore
from jira_collector.settings import SettingsError, load_settings
from jira_collector.source_sync import OperationalSourceSync, SourceSyncError
from jira_collector.source_sync_smoke import SmokeProjectSourceSync
from jira_collector.state_schema import StateMigrationRequiredError, StateSchemaError
from jira_collector.state_store import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Continuous Jira Knowledge Service의 Loop A(Source Sync)를 실행합니다. "
            "새/빈 DB는 현재 State Schema로 바로 초기화되며, 기존 legacy collector.db를 "
            "재사용하는 경우에만 명시적 Migration이 필요합니다."
        ),
    )
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--local-config", default="config/settings.local.yaml")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument(
        "--resume-source-run-id",
        help="실패/중단된 동일 Source Run을 fixed upper와 cursor 그대로 재개합니다.",
    )
    parser.add_argument(
        "--max-issues-per-project",
        type=int,
        help=(
            "테스트/파일럿 전용 Project별 candidate 상한. "
            "운영 Continuous Sync에서는 생략하여 전체 Delta window를 처리합니다."
        ),
    )
    parser.add_argument(
        "--project-key",
        help=(
            "Smoke 전용 Project key 필터. config/settings.smoke.yaml의 "
            "data_smoke root에서만 허용하며 지정 Project 하나만 Source Sync합니다."
        ),
    )
    return parser


def _configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _validate_smoke_project_options(args: argparse.Namespace, data_root: Path) -> None:
    if not args.project_key:
        return
    if args.resume_source_run_id:
        raise ValueError(
            "--project-key Smoke Run은 --resume-source-run-id와 함께 사용할 수 없습니다. "
            "실패하면 data_smoke를 비우고 새 Smoke Run으로 다시 실행하십시오."
        )
    if data_root.resolve().name != "data_smoke":
        raise ValueError(
            "--project-key는 격리된 Smoke 전용입니다. "
            "--local-config config/settings.smoke.yaml을 사용하십시오."
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(
            args.config,
            local_config_path=args.local_config,
            dotenv_path=args.dotenv,
        )
        _configure_logging(settings.logging.level)
        _validate_smoke_project_options(args, settings.storage.data_root)

        state_path = settings.storage.state_root / "collector.db"
        raw_store = RawStore(
            settings.storage.data_root,
            settings.storage.raw_directory,
        )
        state = StateStore(state_path)

        with JiraClient(settings.jira) as client:
            if args.project_key:
                source_sync = SmokeProjectSourceSync(
                    client,
                    raw_store,
                    state,
                    project_key=args.project_key,
                    data_root=settings.storage.data_root,
                )
            else:
                source_sync = OperationalSourceSync(
                    client,
                    raw_store,
                    state,
                    data_root=settings.storage.data_root,
                )

            if args.resume_source_run_id:
                result = source_sync.resume(
                    args.resume_source_run_id,
                    max_issues_per_project=args.max_issues_per_project,
                )
            else:
                result = source_sync.run(
                    max_issues_per_project=args.max_issues_per_project,
                )
    except StateMigrationRequiredError as exc:
        print("SOURCE_SYNC = BLOCKED")
        print(f"reason = {exc}")
        print(
            "next = legacy DB를 재사용하려는 경우에만 "
            "python tools/migrate_state_v3.py --database <collector.db>"
        )
        return 3
    except (SettingsError, JiraClientError, StateSchemaError, SourceSyncError, OSError, ValueError, KeyError) as exc:
        print("SOURCE_SYNC = FAIL")
        print(f"reason = {exc}")
        return 1

    print(f"SOURCE_SYNC = {result.status.upper()}")
    print(f"source_run_id = {result.source_run_id}")
    if args.project_key:
        print(f"smoke_project_key = {args.project_key}")
    print(f"visible_project_count = {result.visible_project_count}")
    print(
        "source_committed_project_count = "
        f"{result.source_committed_project_count}"
    )
    print(f"failed_project_count = {result.failed_project_count}")
    print(f"state_db = {Path(settings.storage.state_root / 'collector.db')}")
    return 0 if result.status == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
