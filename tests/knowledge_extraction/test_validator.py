from __future__ import annotations

from copy import deepcopy

from jira_collector.knowledge_extraction import KnowledgeExtractionValidator


def _package() -> dict[str, object]:
    """실제 업무 내용이 없는 Knowledge Input 가짜 패키지를 생성합니다."""

    return {
        "package_schema_version": "1.0",
        "run_id": "run1",
        "project_key": "ABC",
        "issue_key": "ABC-1",
        "generated_at": "2026-08-07T00:00:00Z",
        "source_hash": "sha256:" + "a" * 64,
        "issue": {
            "summary": "Example issue",
            "description": "Example description",
            "status": "Open",
        },
        "comments": [
            {
                "comment_id": "5001",
                "sequence": 1,
                "body": "Example observation",
            }
        ],
        "attachments": [
            {
                "attachment_id": "8001",
                "filename": "example.log",
                "content_available": False,
            }
        ],
        "relationships": [
            {
                "relationship_id": "9001",
                "relationship_text": "blocks",
                "source_issue_key": "ABC-1",
                "target_issue_key": "ABC-2",
            }
        ],
        "custom_fields": [
            {
                "field_id": "customfield_10000",
                "display_value": "Example",
            }
        ],
        "counts": {
            "comment_count": 1,
            "attachment_count": 1,
            "relationship_count": 1,
            "custom_field_count": 1,
        },
    }


def _statement(
    text: str,
    *,
    state: str = "observed",
    source_type: str = "comment",
    source_id: str = "5001",
) -> dict[str, object]:
    """검증 테스트에서 재사용할 Knowledge statement를 만듭니다."""

    return {
        "text": text,
        "state": state,
        "evidence_refs": [
            {
                "source_type": source_type,
                "source_id": source_id,
            }
        ],
    }


def _extraction() -> dict[str, object]:
    """v1 출력 계약을 만족하는 기본 Knowledge 결과를 만듭니다."""

    return {
        "knowledge_schema_version": "1.0",
        "run_id": "run1",
        "project_key": "ABC",
        "issue_key": "ABC-1",
        "source_hash": "sha256:" + "a" * 64,
        "prompt_version": "knowledge-extraction-v1",
        "extractor_model": "company-model",
        "extracted_at": "2026-08-07T01:00:00Z",
        "issue_summary": {
            "text": "Example summary",
            "evidence_refs": [
                {
                    "source_type": "issue_description",
                    "source_id": "ABC-1",
                }
            ],
        },
        "problem_or_goal": [_statement("Example problem")],
        "context": [],
        "observations": [_statement("Observed fact")],
        "hypotheses": [],
        "confirmed_causes": [],
        "actions_taken": [],
        "plans": [],
        "decisions": [],
        "results": [],
        "conclusions": [],
        "open_questions": [],
        "blockers": [],
    }


def test_valid_extraction_passes() -> None:
    """올바른 metadata와 실제 evidence ID를 사용한 출력은 통과하는지 확인합니다."""

    result = KnowledgeExtractionValidator().validate(_package(), _extraction())

    assert result.valid is True
    assert result.error_count == 0


def test_rejects_source_hash_and_unknown_comment() -> None:
    """다른 snapshot hash와 존재하지 않는 comment evidence를 동시에 검출하는지 확인합니다."""

    extraction = _extraction()
    extraction["source_hash"] = "sha256:" + "b" * 64
    extraction["observations"] = [
        _statement("Unknown evidence", source_id="9999")
    ]

    result = KnowledgeExtractionValidator().validate(_package(), extraction)
    codes = {item.code for item in result.errors}

    assert result.valid is False
    assert "input_identity_mismatch" in codes
    assert "evidence_not_found" in codes


def test_confirmed_cause_requires_text_evidence() -> None:
    """Attachment metadata만으로 confirmed cause를 확정하는 출력을 거부하는지 확인합니다."""

    extraction = _extraction()
    extraction["confirmed_causes"] = [
        _statement(
            "Attachment content caused the issue",
            state="confirmed",
            source_type="attachment_metadata",
            source_id="8001",
        )
    ]

    result = KnowledgeExtractionValidator().validate(_package(), extraction)

    assert result.valid is False
    assert "text_evidence_required" in {
        item.code for item in result.errors
    }


def test_reports_suspicious_confirmed_cause_state_as_warning() -> None:
    """confirmed_causes에 confirmed가 아닌 상태가 오면 구조는 유지하되 경고하는지 확인합니다."""

    extraction = _extraction()
    extraction["confirmed_causes"] = [
        _statement("Confirmed cause", state="stated")
    ]

    result = KnowledgeExtractionValidator().validate(_package(), extraction)

    assert result.valid is True
    assert "confirmed_cause_state_suspicious" in {
        item.code for item in result.warnings
    }


def test_rejects_unexpected_top_level_key() -> None:
    """Agent가 스키마 밖의 임의 top-level key를 추가하면 실패하는지 확인합니다."""

    extraction = deepcopy(_extraction())
    extraction["extra_analysis"] = "not allowed"

    result = KnowledgeExtractionValidator().validate(_package(), extraction)

    assert result.valid is False
    assert "unexpected_top_level_key" in {
        item.code for item in result.errors
    }
