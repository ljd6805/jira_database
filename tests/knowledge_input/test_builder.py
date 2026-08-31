from __future__ import annotations

import json
from pathlib import Path

import pytest

from jira_collector.knowledge_input import (
    IssueKnowledgeInputBuilder,
    KnowledgeInputBuildError,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """테스트용 JSONL을 UTF-8 한 줄 객체 형식으로 저장합니다."""

    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _analysis_fixture(data_root: Path, *, completed: bool = True) -> Path:
    """민감정보가 없는 가짜 ANALYSIS run 전체를 생성합니다."""

    run = data_root / "analysis" / "run1"
    run.mkdir(parents=True)
    status = "completed" if completed else "partial"
    (run / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "run1",
                "issues": {"status": status},
                "comments": {"status": "completed"},
                "attachments": {"status": "completed"},
                "relationships": {"status": "completed"},
                "custom_fields": {"status": "completed"},
            }
        ),
        encoding="utf-8",
    )

    raw = data_root / "raw" / "runs" / "run1"
    issue_path = str(raw / "ABC-1" / "issue.json")
    _write_jsonl(
        run / "issues.jsonl",
        [
            {
                "run_id": "run1",
                "project_key": "ABC",
                "issue_key": "ABC-1",
                "jira_id": "1",
                "summary": "summary",
                "description_text": "description",
                "description_format": "html",
                "issue_type": "Bug",
                "status": "Open",
                "priority": "Major",
                "created_at": "c",
                "updated_at": "u",
                "source_path": issue_path,
            }
        ],
    )
    _write_jsonl(
        run / "comments.jsonl",
        [
            {
                "run_id": "run1",
                "project_key": "ABC",
                "issue_key": "ABC-1",
                "comment_id": "10",
                "sequence": 1,
                "author_name": "Tester",
                "author_key": "tester",
                "created_at": "c",
                "updated_at": "u",
                "body_text": "comment",
                "body_format": "html",
                "source_path": str(
                    raw / "ABC-1" / "comments" / "page_0001.json"
                ),
                "source_page": "page_0001.json",
                "emailAddress": "must-not-copy@example.com",
            }
        ],
    )
    _write_jsonl(run / "attachments.jsonl", [])
    _write_jsonl(
        run / "issue_relationships.jsonl",
        [
            {
                "run_id": "run1",
                "relationship_id": "30",
                "relationship_category": "issue_link",
                "relationship_type": "Blocks",
                "relationship_text": "blocks",
                "source_issue_key": "ABC-9",
                "target_issue_key": "ABC-1",
                "source_summary": "other",
                "source_status": "Open",
                "target_summary": "summary",
                "target_status": "Open",
                "derived": False,
                "source_path": issue_path,
            }
        ],
    )
    _write_jsonl(
        run / "custom_field_catalog.jsonl",
        [
            {
                "run_id": "run1",
                "field_id": "customfield_1",
                "field_name": "Revision",
                "schema_type": "option",
                "schema_items": None,
                "schema_custom": "select",
                "schema_custom_id": None,
                "source_path": issue_path,
            }
        ],
    )
    _write_jsonl(
        run / "custom_field_values.jsonl",
        [
            {
                "run_id": "run1",
                "project_key": "ABC",
                "issue_key": "ABC-1",
                "field_id": "customfield_1",
                "field_name": "Revision",
                "schema_type": "option",
                "schema_items": None,
                "schema_custom": "select",
                "actual_type": "object",
                "value_kind": "option",
                "display_value": "EVT",
                "display_values": [],
                "value_id": "1",
                "value_ids": [],
                "user_keys": [],
                "value_shape": ["id", "value"],
                "source_path": issue_path,
                "emailAddress": "must-not-copy@example.com",
            }
        ],
    )
    return run


def _package(result: object) -> dict[str, object]:
    issues_directory = getattr(result, "issues_directory")
    return json.loads((issues_directory / "ABC-1.json").read_text(encoding="utf-8"))


def test_builds_one_issue_package_and_manifest(tmp_path: Path) -> None:
    """ANALYSIS의 여러 파일이 이슈 하나의 계층형 JSON으로 조립되는지 확인합니다."""

    data_root = tmp_path / "data"
    _analysis_fixture(data_root)

    result = IssueKnowledgeInputBuilder(data_root).build_run("run1")
    package = _package(result)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.package_count == 1
    assert package["source_hash_profile"] == "semantic_v2"
    assert package["comments"][0]["body"] == "comment"
    assert package["relationships"][0]["current_issue_direction"] == "incoming"
    assert package["relationships"][0]["other_package_available"] is False
    assert package["custom_fields"][0]["field_name"] == "Revision"
    assert package["issue"]["source_path"].startswith("raw/")
    assert "must-not-copy@example.com" not in json.dumps(package)
    assert manifest["source_hash_profile"] == "semantic_v2"
    assert manifest["packages"][0]["source_hash_profile"] == "semantic_v2"
    assert manifest["status"] == "completed"
    assert manifest["package_count"] == 1


def test_source_hash_ignores_source_path_changes(tmp_path: Path) -> None:
    """PC 경로만 달라진 경우 같은 의미 데이터가 같은 source_hash를 만드는지 확인합니다."""

    data_root = tmp_path / "data"
    run = _analysis_fixture(data_root)
    builder = IssueKnowledgeInputBuilder(data_root)

    first_package = _package(builder.build_run("run1"))

    rows = _read_jsonl(run / "issues.jsonl")
    rows[0]["source_path"] = str(tmp_path / "other-machine" / "issue.json")
    _write_jsonl(run / "issues.jsonl", rows)

    second_package = _package(builder.build_run("run1"))
    assert first_package["source_hash"] == second_package["source_hash"]


def test_semantic_v2_ignores_issue_and_comment_updated_at_only(tmp_path: Path) -> None:
    """updated_at은 package에 남지만 semantic_v2 hash를 바꾸지 않는지 확인합니다."""

    data_root = tmp_path / "data"
    run = _analysis_fixture(data_root)
    builder = IssueKnowledgeInputBuilder(data_root)

    first_package = _package(builder.build_run("run1"))

    issue_rows = _read_jsonl(run / "issues.jsonl")
    issue_rows[0]["updated_at"] = "issue-updated-later"
    _write_jsonl(run / "issues.jsonl", issue_rows)

    comment_rows = _read_jsonl(run / "comments.jsonl")
    comment_rows[0]["updated_at"] = "comment-updated-later"
    _write_jsonl(run / "comments.jsonl", comment_rows)

    second_package = _package(builder.build_run("run1"))

    assert first_package["source_hash"] == second_package["source_hash"]
    assert second_package["issue"]["updated_at"] == "issue-updated-later"
    assert second_package["comments"][0]["updated_at"] == "comment-updated-later"


def test_semantic_v2_changes_hash_for_meaningful_content(tmp_path: Path) -> None:
    """업무 의미가 바뀌면 semantic_v2 hash가 반드시 바뀌는지 확인합니다."""

    data_root = tmp_path / "data"
    run = _analysis_fixture(data_root)
    builder = IssueKnowledgeInputBuilder(data_root)

    first_package = _package(builder.build_run("run1"))

    comment_rows = _read_jsonl(run / "comments.jsonl")
    comment_rows[0]["body_text"] = "meaningfully changed comment"
    _write_jsonl(run / "comments.jsonl", comment_rows)

    second_package = _package(builder.build_run("run1"))
    assert first_package["source_hash"] != second_package["source_hash"]


def test_semantic_v2_keeps_created_at_in_hash(tmp_path: Path) -> None:
    """D4에서 보존하기로 한 created_at이 hash 재료에서 빠지지 않는지 확인합니다."""

    data_root = tmp_path / "data"
    run = _analysis_fixture(data_root)
    builder = IssueKnowledgeInputBuilder(data_root)

    first_package = _package(builder.build_run("run1"))

    issue_rows = _read_jsonl(run / "issues.jsonl")
    issue_rows[0]["created_at"] = "created-at-changed"
    _write_jsonl(run / "issues.jsonl", issue_rows)

    second_package = _package(builder.build_run("run1"))
    assert first_package["source_hash"] != second_package["source_hash"]


def test_rejects_incomplete_analysis_summary(tmp_path: Path) -> None:
    """ANALYSIS 중 하나라도 partial이면 최종 입력 패키지 생성을 시작하지 않는지 확인합니다."""

    data_root = tmp_path / "data"
    _analysis_fixture(data_root, completed=False)

    with pytest.raises(KnowledgeInputBuildError):
        IssueKnowledgeInputBuilder(data_root).build_run("run1")


def test_orphan_record_becomes_partial_warning(tmp_path: Path) -> None:
    """존재하지 않는 이슈를 가리키는 ANALYSIS 레코드는 격리하고 partial로 표시합니다."""

    data_root = tmp_path / "data"
    run = _analysis_fixture(data_root)
    _write_jsonl(
        run / "attachments.jsonl",
        [
            {
                "run_id": "run1",
                "project_key": "ABC",
                "issue_key": "ABC-404",
                "attachment_id": "1",
            }
        ],
    )

    result = IssueKnowledgeInputBuilder(data_root).build_run("run1")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    warnings = [
        json.loads(line)
        for line in result.warnings_path.read_text(encoding="utf-8").splitlines()
    ]

    assert manifest["status"] == "partial"
    assert warnings[0]["code"] == "orphan_analysis_record"
