#!/usr/bin/env python3
"""Jira Knowledge Extraction run을 결정론적으로 집계한다.

LLM이 Attempt/PASS/Critical/Major 건수를 직접 세지 않도록 로컬 산출물만 읽어
최종 집계 JSON을 만든다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


REVIEW_RE = re.compile(r"^(?P<issue>.+)\.review\.attempt(?P<attempt>[1-9]\d*)\.json$")
PASS_THRESHOLD = 8.5
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class ReviewRecord:
    issue_key: str
    attempt: int
    score: float
    verdict: str
    critical_error: bool
    major_issue_count: int
    critical_issues: list[Any]
    major_issues: list[Any]

    @property
    def has_critical(self) -> bool:
        return self.critical_error or bool(self.critical_issues)

    @property
    def has_major(self) -> bool:
        return self.major_issue_count > 0 or bool(self.major_issues)

    @property
    def is_pass(self) -> bool:
        return (
            self.verdict == "PASS"
            and self.score >= PASS_THRESHOLD
            and not self.critical_error
            and self.major_issue_count == 0
        )


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def load_issue_keys(input_dir: Path) -> tuple[list[str], list[str]]:
    issue_keys: list[str] = []
    input_errors: list[str] = []

    for path in sorted(input_dir.glob("*.json")):
        try:
            data = read_json(path)
            issue_key = data.get("issue_key") or path.stem
            if not isinstance(issue_key, str) or not issue_key.strip():
                raise ValueError("issue_key missing")
            issue_keys.append(issue_key.strip())
        except (OSError, ValueError, json.JSONDecodeError):
            input_errors.append(path.name)

    return issue_keys, input_errors


def load_reviews(review_dir: Path) -> tuple[dict[str, list[ReviewRecord]], list[str]]:
    grouped: dict[str, list[ReviewRecord]] = {}
    errors: list[str] = []

    for path in sorted(review_dir.glob("*.review.attempt*.json")):
        match = REVIEW_RE.match(path.name)
        if not match:
            continue
        try:
            data = read_json(path)
            issue_key = str(data["issue_key"])
            record = ReviewRecord(
                issue_key=issue_key,
                attempt=int(match.group("attempt")),
                score=float(data["score"]),
                verdict=str(data["verdict"]),
                critical_error=bool(data["critical_error"]),
                major_issue_count=int(data["major_issue_count"]),
                critical_issues=list(data.get("critical_issues", [])),
                major_issues=list(data.get("major_issues", [])),
            )
            if issue_key != match.group("issue"):
                raise ValueError("filename issue_key mismatch")
            grouped.setdefault(issue_key, []).append(record)
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            errors.append(path.name)

    for records in grouped.values():
        records.sort(key=lambda item: item.attempt)
    return grouped, errors


def summarize_issue(
    issue_key: str,
    reviews: list[ReviewRecord],
    knowledge_dir: Path,
) -> dict[str, Any]:
    knowledge_exists = (knowledge_dir / f"{issue_key}.json").is_file()
    if not reviews:
        return {
            "issue_key": issue_key,
            "status": "INCOMPLETE",
            "attempt": 0,
            "score": None,
            "had_critical": False,
            "had_major": False,
            "knowledge_exists": knowledge_exists,
        }

    final = reviews[-1]
    if final.is_pass and knowledge_exists:
        status = "PASS"
    elif final.attempt >= MAX_ATTEMPTS and final.verdict == "REGENERATE":
        status = "REVIEW_REQUIRED"
    else:
        status = "INCOMPLETE"

    return {
        "issue_key": issue_key,
        "status": status,
        "attempt": final.attempt,
        "score": final.score,
        "had_critical": any(item.has_critical for item in reviews),
        "had_major": any(item.has_major for item in reviews),
        "knowledge_exists": knowledge_exists,
    }


def find_duplicate_keys(issue_keys: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for key in issue_keys:
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return sorted(duplicates)


def build_summary(input_dir: Path, knowledge_dir: Path, review_dir: Path) -> dict[str, Any]:
    issue_keys, input_errors = load_issue_keys(input_dir)
    reviews_by_issue, review_errors = load_reviews(review_dir)
    duplicate_keys = find_duplicate_keys(issue_keys)
    unique_keys = list(dict.fromkeys(issue_keys))

    issues = [
        summarize_issue(issue_key, reviews_by_issue.get(issue_key, []), knowledge_dir)
        for issue_key in unique_keys
    ]

    pass_by_attempt = {
        attempt: sum(
            1
            for issue in issues
            if issue["status"] == "PASS" and issue["attempt"] == attempt
        )
        for attempt in range(1, MAX_ATTEMPTS + 1)
    }
    reviewed_scores = [issue["score"] for issue in issues if issue["score"] is not None]
    regenerated = [issue["issue_key"] for issue in issues if issue["attempt"] > 1]
    critical = [issue["issue_key"] for issue in issues if issue["had_critical"]]
    major = [issue["issue_key"] for issue in issues if issue["had_major"]]
    review_required = [
        issue["issue_key"] for issue in issues if issue["status"] == "REVIEW_REQUIRED"
    ]
    incomplete = [issue["issue_key"] for issue in issues if issue["status"] == "INCOMPLETE"]

    accounted = sum(pass_by_attempt.values()) + len(review_required) + len(incomplete)

    return {
        "target_issue_count": len(unique_keys),
        "input_error_count": len(input_errors),
        "input_error_files": input_errors,
        "first_pass_count": pass_by_attempt[1],
        "second_pass_count": pass_by_attempt[2],
        "third_pass_count": pass_by_attempt[3],
        "review_required_count": len(review_required),
        "review_required_issues": review_required,
        "incomplete_count": len(incomplete),
        "incomplete_issues": incomplete,
        "regenerated_issue_count": len(regenerated),
        "regenerated_issues": regenerated,
        "critical_issue_count": len(critical),
        "critical_issues": critical,
        "major_issue_count": len(major),
        "major_issues": major,
        "average_final_score": round(mean(reviewed_scores), 2) if reviewed_scores else None,
        "duplicate_issue_keys": duplicate_keys,
        "review_parse_errors": review_errors,
        "accounted_issue_count": accounted,
        "accounting_consistent": accounted == len(unique_keys),
        "issues": issues,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("knowledge_dir", type=Path)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for path in (args.input_dir, args.knowledge_dir, args.review_dir):
        if not path.is_dir():
            print(json.dumps({"error": f"missing directory: {path}"}, ensure_ascii=False))
            return 2

    summary = build_summary(args.input_dir, args.knowledge_dir, args.review_dir)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)

    if summary["duplicate_issue_keys"] or summary["review_parse_errors"]:
        return 1
    if not summary["accounting_consistent"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
