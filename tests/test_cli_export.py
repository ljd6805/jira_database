from __future__ import annotations

from jira_collector.cli import build_parser


def test_export_issues_command_requires_run_id() -> None:
    """export-issues 명령이 run_id 인자를 정상적으로 해석하는지 확인합니다."""

    args = build_parser().parse_args(["export-issues", "--run-id", "run1"])

    assert args.command == "export-issues"
    assert args.run_id == "run1"
