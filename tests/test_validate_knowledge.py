from __future__ import annotations

import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "jira_knowledge" / "validate_knowledge.py"
_SPEC = importlib.util.spec_from_file_location("validate_knowledge_tool", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_VALIDATOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VALIDATOR)


def _input_document() -> dict[str, object]:
    return {
        "issue_key": "ABC-1",
        "comments": [{"comment_id": "10"}],
        "attachments": [],
        "relationships": [],
        "custom_fields": [],
    }


def _knowledge_document(refs: list[str]) -> dict[str, object]:
    return {
        "knowledge_schema_version": "0.1",
        "issue_key": "ABC-1",
        "issue_summary": {
            "statement": "테스트 요약",
            "evidence_refs": refs,
        },
        "problem_or_goal": [],
        "key_findings": [],
        "actions_and_decisions": [],
        "outcomes": [],
        "open_items": [],
    }


def test_duplicate_evidence_refs_are_rejected() -> None:
    errors = _VALIDATOR.validate(
        _knowledge_document(["comment:10", "comment:10"]),
        _input_document(),
    )

    assert any("중복 Evidence 금지" in error for error in errors)


def test_unique_evidence_refs_still_pass() -> None:
    errors = _VALIDATOR.validate(
        _knowledge_document(["summary", "comment:10"]),
        _input_document(),
    )

    assert errors == []
