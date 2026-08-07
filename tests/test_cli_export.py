from __future__ import annotations

from jira_collector.cli import build_parser


def test_export_issues_command_requires_run_id() -> None:
    """export-issues 명령이 run_id 인자를 정상적으로 해석하는지 확인합니다."""

    args = build_parser().parse_args(
        ["export-issues", "--run-id", "run1"]
    )

    assert args.command == "export-issues"
    assert args.run_id == "run1"


def test_export_comments_command_requires_run_id() -> None:
    """export-comments 명령이 run_id 인자를 정상적으로 해석하는지 확인합니다."""

    args = build_parser().parse_args(
        ["export-comments", "--run-id", "run1"]
    )

    assert args.command == "export-comments"
    assert args.run_id == "run1"


def test_export_structure_command_requires_run_id() -> None:
    """export-structure 명령이 4단계 구조 데이터용 run_id를 정상적으로 해석하는지 확인합니다."""

    args = build_parser().parse_args(
        ["export-structure", "--run-id", "run1"]
    )

    assert args.command == "export-structure"
    assert args.run_id == "run1"


def test_build_knowledge_input_command_requires_run_id() -> None:
    """build-knowledge-input 명령이 최종 분석 입력용 run_id를 정상적으로 해석하는지 확인합니다."""

    args = build_parser().parse_args(
        ["build-knowledge-input", "--run-id", "run1"]
    )

    assert args.command == "build-knowledge-input"
    assert args.run_id == "run1"
