from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "jira_knowledge" / "profile_knowledge_run.py"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def item(statement: str, *evidence_refs: str) -> dict:
    return {"statement": statement, "evidence_refs": list(evidence_refs)}


def write_knowledge(
    knowledge_dir: Path,
    issue_key: str,
    *,
    problem_or_goal: list[dict] | None = None,
    key_findings: list[dict] | None = None,
    actions_and_decisions: list[dict] | None = None,
    outcomes: list[dict] | None = None,
    open_items: list[dict] | None = None,
) -> None:
    write_json(
        knowledge_dir / f"{issue_key}.json",
        {
            "knowledge_schema_version": "0.1",
            "issue_key": issue_key,
            "issue_summary": item(f"{issue_key} summary", "summary"),
            "problem_or_goal": problem_or_goal or [],
            "key_findings": key_findings or [],
            "actions_and_decisions": actions_and_decisions or [],
            "outcomes": outcomes or [],
            "open_items": open_items or [],
        },
    )


def write_review(
    review_dir: Path,
    issue_key: str,
    attempt: int,
    *,
    score: float,
    verdict: str,
    critical: bool = False,
    major_count: int = 0,
    audit_category: str | None = None,
) -> None:
    audits = {
        "fact_audit": [],
        "causal_claim_audit": [],
        "evidence_audit": [],
        "classification_audit": [],
        "missing_knowledge_audit": [],
        "duplication_audit": [],
    }
    if audit_category:
        audits[audit_category] = [{"location": "x", "message": "finding"}]
    write_json(
        review_dir / f"{issue_key}.review.attempt{attempt}.json",
        {
            "issue_key": issue_key,
            "score": score,
            "verdict": verdict,
            "critical_error": critical,
            "major_issue_count": major_count,
            "category_scores": {
                "factual_fidelity": 2.8,
                "evidence_coverage": 1.8,
                "certainty_preservation": 1.4,
                "classification": 1.4,
                "retrieval_value": 0.9,
                "language_quality": 0.9,
            },
            "audit_findings": audits,
            "critical_issues": ["critical"] if critical else [],
            "major_issues": [
                {"type": "major", "location": "x", "message": "major"}
                for _ in range(major_count)
            ],
            "improvement_points": [],
        },
    )


def run_profile(
    knowledge_dir: Path,
    review_dir: Path,
    *,
    expected_count: int,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(knowledge_dir),
            str(review_dir),
            "--expected-issue-count",
            str(expected_count),
        ],
        check=check,
        capture_output=True,
        text=True,
    )


def test_profiler_measures_knowledge_review_and_outliers(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    review_dir = tmp_path / "reviews"

    write_knowledge(
        knowledge_dir,
        "ISSUE-1",
        problem_or_goal=[item("goal", "description")],
        key_findings=[item("finding one", "comment:1", "custom_field:10")],
    )
    write_knowledge(
        knowledge_dir,
        "ISSUE-2",
        key_findings=[item("long finding statement", "comment:2")],
        outcomes=[item("done", "comment:3")],
    )
    write_knowledge(knowledge_dir, "ISSUE-3")

    write_review(review_dir, "ISSUE-1", 1, score=9.1, verdict="PASS")
    write_review(
        review_dir,
        "ISSUE-2",
        1,
        score=8.2,
        verdict="REGENERATE",
        major_count=1,
        audit_category="classification_audit",
    )
    write_review(review_dir, "ISSUE-2", 2, score=9.0, verdict="PASS")
    write_review(
        review_dir,
        "ISSUE-3",
        1,
        score=7.8,
        verdict="REGENERATE",
        critical=True,
        audit_category="causal_claim_audit",
    )
    write_review(review_dir, "ISSUE-3", 2, score=8.0, verdict="REGENERATE")
    write_review(review_dir, "ISSUE-3", 3, score=8.8, verdict="PASS")

    completed = run_profile(knowledge_dir, review_dir, expected_count=3)
    profile = json.loads(completed.stdout)

    assert profile["integrity"]["ok"] is True
    assert profile["knowledge"]["issue_count"] == 3
    assert profile["knowledge"]["total_statement_item_count"] == 7
    assert profile["knowledge"]["array_item_count"] == 4
    assert profile["knowledge"]["category_item_counts"]["issue_summary"] == 3
    assert profile["knowledge"]["category_item_counts"]["key_findings"] == 2
    assert profile["knowledge"]["empty_arrays"]["problem_or_goal"] == {
        "empty_issue_count": 2,
        "empty_ratio": 0.6667,
    }
    assert profile["knowledge"]["evidence"]["type_counts"] == {
        "comment": 3,
        "custom_field": 1,
        "description": 1,
        "summary": 3,
    }

    review = profile["review"]
    assert review["final_attempt_distribution"] == {"1": 1, "2": 1, "3": 1}
    assert review["regenerated_issue_count"] == 2
    assert review["historical_critical_issue_count"] == 1
    assert review["historical_major_issue_count"] == 1
    assert review["audit_finding_counts"]["classification_audit"] == 1
    assert review["audit_finding_counts"]["causal_claim_audit"] == 1

    assert profile["outliers"]["largest_issues_by_item_count"][0]["issue_key"] == "ISSUE-1"
    assert "statement" not in profile["outliers"]["longest_statements"][0]
    assert profile["outliers"]["highest_attempt_issues"][0]["issue_key"] == "ISSUE-3"


def test_profiler_fails_when_expected_issue_count_mismatches(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    review_dir = tmp_path / "reviews"
    write_knowledge(knowledge_dir, "ISSUE-1")
    write_review(review_dir, "ISSUE-1", 1, score=9.0, verdict="PASS")

    completed = run_profile(knowledge_dir, review_dir, expected_count=2, check=False)
    profile = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert profile["integrity"]["ok"] is False
    assert profile["integrity"]["expected_issue_count_match"] is False


def test_profiler_fails_when_review_is_missing(tmp_path: Path) -> None:
    knowledge_dir = tmp_path / "knowledge"
    review_dir = tmp_path / "reviews"
    write_knowledge(knowledge_dir, "ISSUE-1")
    review_dir.mkdir(parents=True, exist_ok=True)

    completed = run_profile(knowledge_dir, review_dir, expected_count=1, check=False)
    profile = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert profile["integrity"]["missing_review_issue_keys"] == ["ISSUE-1"]
