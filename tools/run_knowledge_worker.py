from __future__ import annotations

import argparse
import logging
from pathlib import Path

from jira_collector.knowledge_db.ids import KnowledgeContract
from jira_collector.knowledge_processing import (
    KnowledgeProcessingError,
    LoopBKnowledgeWorker,
    OpenCodeKnowledgeProcessor,
)
from jira_collector.settings import SettingsError, load_settings
from jira_collector.stale_recovery import recover_stale_inflight
from jira_collector.state_schema import StateMigrationRequiredError, StateSchemaError
from jira_collector.state_store import StateStore


DEFAULT_OPENCODE_MODEL = "codemate/CodeLLMPro"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Loop B의 latest-only Knowledge stage를 Single Worker로 실행합니다. "
            "Source-ready 최신 Work만 OpenCode Orchestrator로 처리하며, "
            "Embedding/Publish는 아직 다음 stage입니다."
        ),
    )
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--local-config", default="config/settings.local.yaml")
    parser.add_argument("--dotenv", default=".env")
    parser.add_argument(
        "--model-profile",
        required=True,
        help=(
            "Knowledge Generation identity에 기록하는 논리적 모델/Worker/Reviewer 구성 프로필. "
            "실제 opencode run 모델은 --opencode-model로 별도 지정합니다. "
            "예: internal-opencode-knowledge-v1"
        ),
    )
    parser.add_argument("--skill-version", default="0.9")
    parser.add_argument("--runtime-version", default="0.9")
    parser.add_argument("--knowledge-schema-version", default="0.1")
    parser.add_argument("--opencode-binary", default="opencode")
    parser.add_argument("--opencode-agent", default="jira-knowledge-orchestrator")
    parser.add_argument(
        "--opencode-model",
        default=DEFAULT_OPENCODE_MODEL,
        help=(
            "실제 opencode run --model에 전달할 provider/model. "
            f"기본: {DEFAULT_OPENCODE_MODEL}"
        ),
    )
    parser.add_argument(
        "--opencode-attach",
        help="선택: 이미 실행 중인 opencode serve 주소. 예: http://localhost:4096",
    )
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=None,
        help=(
            "이 시간보다 오래 running인 Knowledge Work를 중단된 in-flight로 보고 failed로 복구합니다. "
            "생략 시 --timeout-seconds + 300초. Smoke에서 확실히 중단된 Work를 즉시 복구할 때는 0."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="한 Processing Run에서 순차 처리할 latest Knowledge Work 수. 기본 1.",
    )
    return parser


def _configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit <= 0:
        print("KNOWLEDGE_WORKER = FAIL")
        print("reason = --limit은 1 이상이어야 합니다.")
        return 1
    if args.timeout_seconds <= 0:
        print("KNOWLEDGE_WORKER = FAIL")
        print("reason = --timeout-seconds는 1 이상이어야 합니다.")
        return 1
    if args.stale_after_seconds is not None and args.stale_after_seconds < 0:
        print("KNOWLEDGE_WORKER = FAIL")
        print("reason = --stale-after-seconds는 0 이상이어야 합니다.")
        return 1
    if not args.opencode_model.strip() or "/" not in args.opencode_model:
        print("KNOWLEDGE_WORKER = FAIL")
        print("reason = --opencode-model은 provider/model 형식이어야 합니다.")
        return 1

    try:
        settings = load_settings(
            args.config,
            local_config_path=args.local_config,
            dotenv_path=args.dotenv,
        )
        _configure_logging(settings.logging.level)
        state = StateStore(settings.storage.state_root / "collector.db")
        stale_after_seconds = (
            args.stale_after_seconds
            if args.stale_after_seconds is not None
            else args.timeout_seconds + 300
        )
        recovery = recover_stale_inflight(
            state,
            stage="knowledge",
            stale_after_seconds=stale_after_seconds,
        )
        contract = KnowledgeContract(
            knowledge_schema_version=args.knowledge_schema_version,
            skill_version=args.skill_version,
            runtime_version=args.runtime_version,
            model_profile=args.model_profile,
        )
        processor = OpenCodeKnowledgeProcessor(
            Path.cwd(),
            binary=args.opencode_binary,
            agent=args.opencode_agent,
            model=args.opencode_model,
            attach_url=args.opencode_attach,
            timeout_seconds=args.timeout_seconds,
        )
        worker = LoopBKnowledgeWorker(
            state,
            settings.storage.data_root,
            processor,
            knowledge_contract=contract,
        )
        result = worker.run(limit=args.limit)
    except StateMigrationRequiredError as exc:
        print("KNOWLEDGE_WORKER = BLOCKED")
        print(f"reason = {exc}")
        print("next = python tools/migrate_state_v3.py --database data/state/collector.db")
        return 3
    except (SettingsError, StateSchemaError, KnowledgeProcessingError, OSError, ValueError) as exc:
        print("KNOWLEDGE_WORKER = FAIL")
        print(f"reason = {exc}")
        return 1

    outcome = "CHECKPOINTED" if result.knowledge_completed_count else result.status.upper()
    print(f"KNOWLEDGE_WORKER = {outcome}")
    print(f"processing_run_id = {result.processing_run_id}")
    print(f"stale_after_seconds = {stale_after_seconds}")
    print(f"stale_recovered_work_count = {recovery.recovered_work_count}")
    print(
        "stale_recovered_processing_run_count = "
        f"{recovery.recovered_processing_run_count}"
    )
    print(f"selected_count = {result.selected_count}")
    print(f"knowledge_completed_count = {result.knowledge_completed_count}")
    print(f"failed_count = {result.failed_count}")
    print(f"superseded_count = {result.superseded_count}")
    print(f"knowledge_backlog_before = {result.knowledge_backlog_before}")
    print(f"knowledge_backlog_after = {result.knowledge_backlog_after}")
    print(f"model_profile = {args.model_profile}")
    print(f"opencode_model = {args.opencode_model}")
    print("next_stage = Embedding / Publish")
    return 0 if result.failed_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
