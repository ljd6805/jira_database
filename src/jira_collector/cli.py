from __future__ import annotations

import argparse
import json
import logging
import sys

from .collector import JiraCollector, new_run_id
from .exporter import CommentJsonlExporter, IssueJsonlExporter
from .jira_client import JiraClient, JiraClientError
from .parser import CommentParser, IssueParser, RunReader
from .project_discovery import ProjectDiscovery
from .raw_store import RawStore
from .report import ReportWriter
from .settings import AppSettings, SettingsError, load_settings
from .state_store import StateStore

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """지원하는 CLI 명령과 공통 설정 인자를 구성합니다."""

    parser = argparse.ArgumentParser(
        prog="jira-collector",
        description="Jira 원본 JSON 수집·검증·로컬 파싱 도구",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="기본 YAML 설정 파일",
    )
    parser.add_argument(
        "--local-config",
        default="config/settings.local.yaml",
        help="선택 로컬 YAML 설정 파일",
    )
    parser.add_argument(
        "--dotenv",
        default=".env",
        help="Jira URL/계정/비밀번호 .env 파일",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check-connection", help="Jira 인증과 REST 연결 확인")
    subparsers.add_parser("discover-projects", help="접근 가능한 프로젝트 목록 확인")

    collect = subparsers.add_parser("collect", help="새 수집 실행")
    collect.add_argument("--project", help="특정 프로젝트 키만 수집")
    collect.add_argument(
        "--issues-per-project",
        type=int,
        help="프로젝트별 최대 이슈 수",
    )

    resume = subparsers.add_parser("resume", help="중단되거나 실패한 실행 재개")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--include-failed", action="store_true")

    verify = subparsers.add_parser("verify", help="저장 파일 SHA-256 검증")
    verify.add_argument("--run-id", required=True)

    export_issues = subparsers.add_parser(
        "export-issues",
        help="수집된 issue.json을 분석용 JSONL로 변환",
    )
    export_issues.add_argument("--run-id", required=True)

    export_comments = subparsers.add_parser(
        "export-comments",
        help="수집된 댓글 페이지를 병합해 분석용 JSONL로 변환",
    )
    export_comments.add_argument("--run-id", required=True)

    return parser


def configure_logging(settings: AppSettings) -> None:
    """YAML 설정의 로그 레벨을 Python logging에 적용합니다."""

    level = getattr(logging, settings.logging.level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _build_components(
    settings: AppSettings,
) -> tuple[RawStore, StateStore, ReportWriter]:
    """수집과 검증 명령에서 공통으로 사용하는 저장 구성요소를 생성합니다."""

    settings.storage.data_root.mkdir(parents=True, exist_ok=True)
    raw_store = RawStore(
        settings.storage.data_root,
        settings.storage.raw_directory,
    )
    state = StateStore(settings.storage.state_root / "collector.db")
    report_writer = ReportWriter(settings.storage.report_root)
    return raw_store, state, report_writer


def command_check_connection(settings: AppSettings) -> int:
    """Jira 인증과 기본 REST 연결을 확인합니다."""

    with JiraClient(settings.jira) as client:
        result = client.check_connection()
    payload = result.payload if isinstance(result.payload, dict) else {}
    identity = (
        payload.get("displayName")
        or payload.get("name")
        or payload.get("key")
        or "unknown"
    )
    print(f"연결 성공: HTTP {result.status_code}, 사용자={identity}")
    return 0


def command_discover_projects(settings: AppSettings) -> int:
    """현재 계정이 조회 가능한 프로젝트를 발견하고 원본으로 저장합니다."""

    raw_store, state, report_writer = _build_components(settings)
    run_id = f"discover-{new_run_id()}"
    state.create_run(run_id, settings.jira.collection.issues_per_project)
    with JiraClient(settings.jira) as client:
        projects = ProjectDiscovery(
            client,
            raw_store,
            state,
        ).discover(run_id)
    state.finish_run(run_id)
    report_writer.write(state, run_id)

    print(f"접근 가능한 프로젝트: {len(projects)}개")
    for project in projects:
        print(f"- {project.key}: {project.name}")
    print(f"실행 ID: {run_id}")
    return 0


def command_collect(
    settings: AppSettings,
    args: argparse.Namespace,
) -> int:
    """새 run_id를 만들고 Jira 원본 수집을 실행합니다."""

    raw_store, state, report_writer = _build_components(settings)
    limit = (
        args.issues_per_project
        or settings.jira.collection.issues_per_project
    )
    if limit <= 0:
        raise ValueError("--issues-per-project는 1 이상이어야 합니다.")

    with JiraClient(settings.jira) as client:
        collector = JiraCollector(client, raw_store, state)
        result = collector.collect_new_run(
            issues_per_project=limit,
            project_filter=args.project,
        )
    report_path = report_writer.write(state, result.run_id)
    print(f"수집 완료: run_id={result.run_id}, status={result.status}")
    print(f"보고서: {report_path}")
    return 0 if result.status == "completed" else 2


def command_resume(
    settings: AppSettings,
    args: argparse.Namespace,
) -> int:
    """기존 run_id의 미완료 또는 실패 수집 작업을 재개합니다."""

    raw_store, state, report_writer = _build_components(settings)
    with JiraClient(settings.jira) as client:
        collector = JiraCollector(client, raw_store, state)
        result = collector.resume_run(
            args.run_id,
            include_failed=args.include_failed,
        )
    report_path = report_writer.write(state, result.run_id)
    print(f"재개 완료: run_id={result.run_id}, status={result.status}")
    print(f"보고서: {report_path}")
    return 0 if result.status == "completed" else 2


def command_verify(
    settings: AppSettings,
    args: argparse.Namespace,
) -> int:
    """SQLite에 기록된 SHA-256과 실제 원본 파일의 해시를 비교합니다."""

    raw_store, state, _ = _build_components(settings)
    if not state.run_exists(args.run_id):
        raise KeyError(f"run_id를 찾을 수 없습니다: {args.run_id}")

    failures: list[dict[str, str]] = []
    artifacts = state.list_artifacts(args.run_id)
    for artifact in artifacts:
        if not raw_store.verify(
            artifact.relative_path,
            artifact.content_hash,
        ):
            failures.append(
                {
                    "artifact_type": artifact.artifact_type,
                    "relative_path": artifact.relative_path,
                }
            )

    print(f"검증 대상: {len(artifacts)}개")
    if failures:
        print(
            json.dumps(
                {"failures": failures},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 3
    print("모든 파일의 SHA-256이 일치합니다.")
    return 0


def command_export_issues(
    settings: AppSettings,
    args: argparse.Namespace,
) -> int:
    """수집된 이슈 원본을 파싱해 JSONL·경고·공통 요약 파일로 저장합니다."""

    reader = RunReader(
        settings.storage.data_root,
        settings.storage.raw_directory,
    )
    exporter = IssueJsonlExporter(settings.storage.data_root)
    result = exporter.export_run(
        args.run_id,
        reader,
        IssueParser(),
    )

    print(f"발견 이슈: {result.discovered_issue_count}개")
    print(f"저장 성공: {result.exported_issue_count}개")
    print(f"저장 실패: {result.failed_issue_count}개")
    print(f"경고 및 오류: {result.warning_count}개")
    print(f"이슈 JSONL: {result.issues_path}")
    print(f"경고 JSONL: {result.warnings_path}")
    print(f"요약 JSON: {result.summary_path}")
    return 0 if result.failed_issue_count == 0 else 2


def command_export_comments(
    settings: AppSettings,
    args: argparse.Namespace,
) -> int:
    """댓글 전용 API 파일을 병합·중복 제거해 JSONL과 공통 요약으로 저장합니다."""

    reader = RunReader(
        settings.storage.data_root,
        settings.storage.raw_directory,
    )
    exporter = CommentJsonlExporter(settings.storage.data_root)
    result = exporter.export_run(
        args.run_id,
        reader,
        CommentParser(),
    )

    print(f"대상 이슈: {result.issue_count}개")
    print(f"댓글 페이지: {result.page_count}개")
    print(f"발견 댓글: {result.discovered_comment_count}개")
    print(f"저장 댓글: {result.exported_comment_count}개")
    print(f"중복 댓글: {result.duplicate_comment_count}개")
    print(f"실패 페이지: {result.failed_page_count}개")
    print(f"실패 댓글: {result.failed_comment_count}개")
    print(
        f"댓글 원본 누락 이슈: "
        f"{result.missing_comment_source_count}개"
    )
    print(f"경고 및 오류: {result.warning_count}개")
    print(f"댓글 JSONL: {result.comments_path}")
    print(f"경고 JSONL: {result.warnings_path}")
    print(f"요약 JSON: {result.summary_path}")
    has_failure = (
        result.failed_page_count > 0
        or result.failed_comment_count > 0
        or result.missing_comment_source_count > 0
    )
    return 2 if has_failure else 0


def main(argv: list[str] | None = None) -> int:
    """명령행 인자를 해석하고 해당 기능을 실행한 뒤 종료 코드를 반환합니다."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(
            args.config,
            local_config_path=args.local_config,
            dotenv_path=args.dotenv,
        )
        configure_logging(settings)

        if args.command == "check-connection":
            return command_check_connection(settings)
        if args.command == "discover-projects":
            return command_discover_projects(settings)
        if args.command == "collect":
            return command_collect(settings, args)
        if args.command == "resume":
            return command_resume(settings, args)
        if args.command == "verify":
            return command_verify(settings, args)
        if args.command == "export-issues":
            return command_export_issues(settings, args)
        if args.command == "export-comments":
            return command_export_comments(settings, args)
        parser.error(f"지원하지 않는 명령입니다: {args.command}")
    except (
        SettingsError,
        JiraClientError,
        KeyError,
        ValueError,
        OSError,
    ) as exc:
        LOGGER.error("%s", exc)
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
