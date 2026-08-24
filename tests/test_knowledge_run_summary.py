from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "jira_knowledge" / "summarize_knowledge_run.py"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_review(
    review_dir: Path,
    issue_key: str,
    attempt: int,
    *,
    score: float,
    verdict: str,
    critical: bool = False,
    major_count: int = 0,
) -> None:
    write_json(
        review_dir / f"{issue_key}.review.attempt{attempt}.json",
        {
            "issue_key": issue_key,
            "score": score,
            "verdict": verdict,
            "critical_error": critical,
            "major_issue_count": major_count,
            "critical_issues": ["critical"] if critical else [],
            "major_issues": [
                {"type": "major", "location": "x", "message": "major"}
                for _ in range(major_count)
            ],
        },
    )


def test_summarizer_counts_attempts_and_historical_defects(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    knowledge_dir = tmp_path / "knowledge"
    review_dir = tmp_path / "reviews"

    issue_keys = ["ISSUE-1", "ISSUE-2", "ISSUE-3", "ISSUE-4", "ISSUE-5", "ISSUE-6"]
    for issue_key in issue_keys:
        write_json(input_dir / f"{issue_key}.json", {"issue_key": issue_key})
        write_json(knowledge_dir / f"{issue_key}.json", {"issue_key": issue_key})

    for issue_key in ("ISSUE-1", "ISSUE-2", "ISSUE-3", "ISSUE-4"):
        write_review(review_dir, issue_key, 1, score=9.0, verdict="PASS")

    write_review(
        review_dir,
        "ISSUE-5",
        1,
        score=8.2,
        verdict="REGENERATE",
        major_count=1,
    )
    write_review(review_dir, "ISSUE-5", 2, score=9.1, verdict="PASS")

    write_review(
        review_dir,
        "ISSUE-6",
        1,
        score=7.8,
        verdict="REGENERATE",
        critical=True,
    )
    write_review(review_dir, "ISSUE-6", 2, score=8.0, verdict="REGENERATE")
    write_review(review_dir, "ISSUE-6", 3, score=8.8, verdict="PASS")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(input_dir),
            str(knowledge_dir),
            str(review_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(completed.stdout)

    assert summary["target_issue_count"] == 6
    assert summary["first_pass_count"] == 4
    assert summary["second_pass_count"] == 1
    assert summary["third_pass_count"] == 1
    assert summary["regenerated_issue_count"] == 2
    assert summary["regenerated_issues"] == ["ISSUE-5", "ISSUE-6"]
    assert summary["major_issue_count"] == 1
    assert summary["major_issues"] == ["ISSUE-5"]
    assert summary["critical_issue_count"] == 1
    assert summary["critical_issues"] == ["ISSUE-6"]
    assert summary["review_required_count"] == 0
    assert summary["incomplete_count"] == 0
    assert summary["accounted_issue_count"] == 6
    assert summary["accounting_consistent"] is True
