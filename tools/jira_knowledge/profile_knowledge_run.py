#!/usr/bin/env python3
"""M5 Jira Knowledge / Review 산출물을 결정론적으로 프로파일링한다.

Knowledge와 Review JSON만 읽어 크기, 분포, 빈 배열, Evidence, Review 이력,
이상치를 계산한다. 원문 statement 내용은 profile 출력에 포함하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


PROFILE_SCHEMA_VERSION = "0.1"
MAX_ATTEMPTS = 3
ARRAY_CATEGORIES = (
    "problem_or_goal",
    "key_findings",
    "actions_and_decisions",
    "outcomes",
    "open_items",
)
ALL_CATEGORIES = ("issue_summary",) + ARRAY_CATEGORIES
AUDIT_CATEGORIES = (
    "fact_audit",
    "causal_claim_audit",
    "evidence_audit",
    "classification_audit",
    "missing_knowledge_audit",
    "duplication_audit",
)
REVIEW_RE = re.compile(r"^(?P<issue>.+)\.review\.attempt(?P<attempt>[1-9]\d*)\.json$")


@dataclass(frozen=True)
class KnowledgeItemRef:
    issue_key: str
    category: str
    index: int
    statement_length_chars: int
    evidence_count: int


@dataclass(frozen=True)
class KnowledgeIssue:
    issue_key: str
    schema_version: str
    category_counts: dict[str, int]
    total_statement_chars: int
    items: tuple[KnowledgeItemRef, ...]
    evidence_types: tuple[str, ...]

    @property
    def total_item_count(self) -> int:
        return len(self.items)

    @property
    def array_item_count(self) -> int:
        return sum(self.category_counts[name] for name in ARRAY_CATEGORIES)


@dataclass(frozen=True)
class ReviewRecord:
    issue_key: str
    attempt: int
    score: float
    verdict: str
    critical_error: bool
    major_issue_count: int
    critical_issues: tuple[Any, ...]
    major_issues: tuple[Any, ...]
    audit_counts: dict[str, int]
    category_scores: dict[str, float]

    @property
    def has_critical(self) -> bool:
        return self.critical_error or bool(self.critical_issues)

    @property
    def has_major(self) -> bool:
        return self.major_issue_count > 0 or bool(self.major_issues)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def number_stats(values: Iterable[int | float]) -> dict[str, int | float | None]:
    numbers = [float(value) for value in values]
    if not numbers:
        return {"count": 0, "min": None, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "count": len(numbers),
        "min": round(min(numbers), 2),
        "mean": round(mean(numbers), 2),
        "p50": round(percentile(numbers, 0.50) or 0.0, 2),
        "p95": round(percentile(numbers, 0.95) or 0.0, 2),
        "max": round(max(numbers), 2),
    }


def ratio(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def evidence_type(reference: str) -> str:
    return reference.split(":", 1)[0]


def parse_item(
    issue_key: str,
    category: str,
    index: int,
    raw_item: Any,
) -> tuple[KnowledgeItemRef, list[str]]:
    if not isinstance(raw_item, dict):
        raise ValueError(f"{issue_key}:{category}[{index}] item must be object")
    statement = raw_item.get("statement")
    evidence_refs = raw_item.get("evidence_refs")
    if not isinstance(statement, str) or not statement.strip():
        raise ValueError(f"{issue_key}:{category}[{index}] statement missing")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise ValueError(f"{issue_key}:{category}[{index}] evidence_refs missing")
    if any(not isinstance(ref, str) or not ref for ref in evidence_refs):
        raise ValueError(f"{issue_key}:{category}[{index}] invalid evidence_refs")
    item = KnowledgeItemRef(
        issue_key=issue_key,
        category=category,
        index=index,
        statement_length_chars=len(statement),
        evidence_count=len(evidence_refs),
    )
    return item, [evidence_type(ref) for ref in evidence_refs]


def parse_knowledge(path: Path) -> KnowledgeIssue:
    data = read_json(path)
    issue_key = data.get("issue_key")
    if not isinstance(issue_key, str) or not issue_key.strip():
        raise ValueError("issue_key missing")
    issue_key = issue_key.strip()
    if path.stem != issue_key:
        raise ValueError(f"filename issue_key mismatch: {path.name} != {issue_key}")

    schema_version = str(data.get("knowledge_schema_version", ""))
    items: list[KnowledgeItemRef] = []
    evidence_types: list[str] = []
    category_counts: dict[str, int] = {}

    summary_item, summary_evidence = parse_item(issue_key, "issue_summary", 0, data.get("issue_summary"))
    items.append(summary_item)
    evidence_types.extend(summary_evidence)
    category_counts["issue_summary"] = 1

    for category in ARRAY_CATEGORIES:
        raw_items = data.get(category)
        if not isinstance(raw_items, list):
            raise ValueError(f"{issue_key}:{category} must be array")
        category_counts[category] = len(raw_items)
        for index, raw_item in enumerate(raw_items):
            item, item_evidence = parse_item(issue_key, category, index, raw_item)
            items.append(item)
            evidence_types.extend(item_evidence)

    return KnowledgeIssue(
        issue_key=issue_key,
        schema_version=schema_version,
        category_counts=category_counts,
        total_statement_chars=sum(item.statement_length_chars for item in items),
        items=tuple(items),
        evidence_types=tuple(evidence_types),
    )


def load_knowledge(knowledge_dir: Path) -> tuple[list[KnowledgeIssue], list[str], list[str]]:
    issues: list[KnowledgeIssue] = []
    errors: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()

    for path in sorted(knowledge_dir.glob("*.json")):
        try:
            issue = parse_knowledge(path)
            if issue.issue_key in seen:
                duplicates.add(issue.issue_key)
            seen.add(issue.issue_key)
            issues.append(issue)
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
    return issues, errors, sorted(duplicates)


def parse_review(path: Path, match: re.Match[str]) -> ReviewRecord:
    data = read_json(path)
    issue_key = str(data["issue_key"])
    attempt = int(match.group("attempt"))
    if issue_key != match.group("issue"):
        raise ValueError("filename issue_key mismatch")
    if attempt > MAX_ATTEMPTS:
        raise ValueError(f"attempt exceeds {MAX_ATTEMPTS}")

    raw_audit = data.get("audit_findings", {})
    if not isinstance(raw_audit, dict):
        raise ValueError("audit_findings must be object")
    audit_counts: dict[str, int] = {}
    for category in AUDIT_CATEGORIES:
        findings = raw_audit.get(category, [])
        if not isinstance(findings, list):
            raise ValueError(f"audit_findings.{category} must be array")
        audit_counts[category] = len(findings)

    raw_scores = data.get("category_scores", {})
    if not isinstance(raw_scores, dict):
        raise ValueError("category_scores must be object")
    category_scores = {
        name: float(value)
        for name, value in raw_scores.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }

    return ReviewRecord(
        issue_key=issue_key,
        attempt=attempt,
        score=float(data["score"]),
        verdict=str(data["verdict"]),
        critical_error=bool(data["critical_error"]),
        major_issue_count=int(data["major_issue_count"]),
        critical_issues=tuple(data.get("critical_issues", [])),
        major_issues=tuple(data.get("major_issues", [])),
        audit_counts=audit_counts,
        category_scores=category_scores,
    )


def load_reviews(review_dir: Path) -> tuple[dict[str, list[ReviewRecord]], list[str]]:
    grouped: dict[str, list[ReviewRecord]] = defaultdict(list)
    errors: list[str] = []
    for path in sorted(review_dir.glob("*.review.attempt*.json")):
        match = REVIEW_RE.match(path.name)
        if not match:
            continue
        try:
            grouped[match.group("issue")].append(parse_review(path, match))
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: {exc}")
    for records in grouped.values():
        records.sort(key=lambda item: item.attempt)
    return dict(grouped), errors


def profile_categories(issues: list[KnowledgeIssue]) -> tuple[dict[str, Any], dict[str, Any]]:
    category_counts = {
        category: sum(issue.category_counts[category] for issue in issues)
        for category in ALL_CATEGORIES
    }
    per_issue = {
        category: number_stats(issue.category_counts[category] for issue in issues)
        for category in ALL_CATEGORIES
    }
    return category_counts, per_issue


def profile_empty_arrays(issues: list[KnowledgeIssue]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for category in ARRAY_CATEGORIES:
        empty_count = sum(issue.category_counts[category] == 0 for issue in issues)
        result[category] = {
            "empty_issue_count": empty_count,
            "empty_ratio": ratio(empty_count, len(issues)),
        }
    return result


def profile_items(issues: list[KnowledgeIssue]) -> dict[str, Any]:
    items = [item for issue in issues for item in issue.items]
    by_category: dict[str, list[KnowledgeItemRef]] = defaultdict(list)
    for item in items:
        by_category[item.category].append(item)

    return {
        "statement_length_chars": {
            "overall": number_stats(item.statement_length_chars for item in items),
            "by_category": {
                category: number_stats(item.statement_length_chars for item in by_category.get(category, []))
                for category in ALL_CATEGORIES
            },
        },
        "evidence_refs_per_item": {
            "overall": number_stats(item.evidence_count for item in items),
            "by_category": {
                category: number_stats(item.evidence_count for item in by_category.get(category, []))
                for category in ALL_CATEGORIES
            },
        },
    }


def profile_evidence(issues: list[KnowledgeIssue]) -> dict[str, Any]:
    counter = Counter(value for issue in issues for value in issue.evidence_types)
    total = sum(counter.values())
    return {
        "total_evidence_ref_count": total,
        "type_counts": dict(sorted(counter.items())),
        "type_ratios": {name: ratio(count, total) for name, count in sorted(counter.items())},
    }


def profile_reviews(
    reviews_by_issue: dict[str, list[ReviewRecord]],
    knowledge_keys: set[str],
) -> dict[str, Any]:
    final_records = [records[-1] for key, records in reviews_by_issue.items() if key in knowledge_keys and records]
    attempt_distribution = Counter(record.attempt for record in final_records)
    verdict_distribution = Counter(record.verdict for record in final_records)
    historical_critical = 0
    historical_major = 0
    audit_finding_counts = Counter()
    audit_issue_sets: dict[str, set[str]] = {name: set() for name in AUDIT_CATEGORIES}

    for issue_key, records in reviews_by_issue.items():
        if issue_key not in knowledge_keys:
            continue
        if any(record.has_critical for record in records):
            historical_critical += 1
        if any(record.has_major for record in records):
            historical_major += 1
        for record in records:
            for category, count in record.audit_counts.items():
                audit_finding_counts[category] += count
                if count:
                    audit_issue_sets[category].add(issue_key)

    score_names = sorted({name for record in final_records for name in record.category_scores})
    category_score_stats = {
        name: number_stats(record.category_scores[name] for record in final_records if name in record.category_scores)
        for name in score_names
    }

    return {
        "review_file_count": sum(len(records) for records in reviews_by_issue.values()),
        "reviewed_issue_count": len(final_records),
        "final_attempt_distribution": {
            str(attempt): attempt_distribution.get(attempt, 0)
            for attempt in range(1, MAX_ATTEMPTS + 1)
        },
        "regenerated_issue_count": sum(record.attempt > 1 for record in final_records),
        "historical_critical_issue_count": historical_critical,
        "historical_major_issue_count": historical_major,
        "final_verdict_counts": dict(sorted(verdict_distribution.items())),
        "final_score": number_stats(record.score for record in final_records),
        "final_category_score": category_score_stats,
        "audit_finding_counts": {
            category: audit_finding_counts.get(category, 0) for category in AUDIT_CATEGORIES
        },
        "audit_issue_counts": {
            category: len(audit_issue_sets[category]) for category in AUDIT_CATEGORIES
        },
    }


def top_issue_rows(issues: list[KnowledgeIssue], key_name: str, top_n: int) -> list[dict[str, Any]]:
    if key_name == "item_count":
        ranked = sorted(issues, key=lambda item: (-item.total_item_count, item.issue_key))
    else:
        ranked = sorted(issues, key=lambda item: (-item.total_statement_chars, item.issue_key))
    return [
        {
            "issue_key": issue.issue_key,
            "item_count": issue.total_item_count,
            "array_item_count": issue.array_item_count,
            "total_statement_chars": issue.total_statement_chars,
        }
        for issue in ranked[:top_n]
    ]


def item_row(item: KnowledgeItemRef) -> dict[str, Any]:
    return {
        "issue_key": item.issue_key,
        "category": item.category,
        "index": item.index,
        "statement_length_chars": item.statement_length_chars,
        "evidence_count": item.evidence_count,
    }


def build_outliers(
    issues: list[KnowledgeIssue],
    reviews_by_issue: dict[str, list[ReviewRecord]],
    top_n: int,
) -> dict[str, Any]:
    items = [item for issue in issues for item in issue.items]
    longest = sorted(
        items,
        key=lambda item: (-item.statement_length_chars, item.issue_key, item.category, item.index),
    )[:top_n]
    evidence_heavy = sorted(
        items,
        key=lambda item: (-item.evidence_count, item.issue_key, item.category, item.index),
    )[:top_n]
    highest_attempt = sorted(
        (
            (issue_key, records[-1])
            for issue_key, records in reviews_by_issue.items()
            if records
        ),
        key=lambda pair: (-pair[1].attempt, pair[0]),
    )[:top_n]

    return {
        "largest_issues_by_item_count": top_issue_rows(issues, "item_count", top_n),
        "largest_issues_by_statement_chars": top_issue_rows(issues, "statement_chars", top_n),
        "longest_statements": [item_row(item) for item in longest],
        "most_evidence_heavy_items": [item_row(item) for item in evidence_heavy],
        "highest_attempt_issues": [
            {
                "issue_key": issue_key,
                "attempt": record.attempt,
                "final_score": record.score,
                "final_verdict": record.verdict,
            }
            for issue_key, record in highest_attempt
        ],
    }


def build_integrity(
    issues: list[KnowledgeIssue],
    knowledge_errors: list[str],
    duplicate_keys: list[str],
    reviews_by_issue: dict[str, list[ReviewRecord]],
    review_errors: list[str],
    expected_issue_count: int | None,
) -> dict[str, Any]:
    knowledge_keys = {issue.issue_key for issue in issues}
    review_keys = set(reviews_by_issue)
    missing_reviews = sorted(knowledge_keys - review_keys)
    orphan_reviews = sorted(review_keys - knowledge_keys)
    expected_ok = expected_issue_count is None or len(issues) == expected_issue_count
    ok = not any((knowledge_errors, duplicate_keys, review_errors, missing_reviews, orphan_reviews)) and expected_ok
    return {
        "ok": ok,
        "expected_issue_count": expected_issue_count,
        "actual_issue_count": len(issues),
        "expected_issue_count_match": expected_ok,
        "knowledge_parse_errors": knowledge_errors,
        "duplicate_issue_keys": duplicate_keys,
        "review_parse_errors": review_errors,
        "missing_review_issue_keys": missing_reviews,
        "orphan_review_issue_keys": orphan_reviews,
    }


def build_profile(
    knowledge_dir: Path,
    review_dir: Path,
    expected_issue_count: int | None,
    top_n: int,
) -> dict[str, Any]:
    issues, knowledge_errors, duplicate_keys = load_knowledge(knowledge_dir)
    reviews_by_issue, review_errors = load_reviews(review_dir)
    integrity = build_integrity(
        issues,
        knowledge_errors,
        duplicate_keys,
        reviews_by_issue,
        review_errors,
        expected_issue_count,
    )
    category_counts, category_per_issue = profile_categories(issues)
    total_items = sum(issue.total_item_count for issue in issues)
    array_items = sum(issue.array_item_count for issue in issues)
    knowledge_keys = {issue.issue_key for issue in issues}

    return {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "knowledge": {
            "issue_count": len(issues),
            "knowledge_schema_versions": sorted({issue.schema_version for issue in issues}),
            "total_statement_item_count": total_items,
            "array_item_count": array_items,
            "items_per_issue": number_stats(issue.total_item_count for issue in issues),
            "array_items_per_issue": number_stats(issue.array_item_count for issue in issues),
            "category_item_counts": category_counts,
            "category_items_per_issue": category_per_issue,
            "empty_arrays": profile_empty_arrays(issues),
            **profile_items(issues),
            "evidence": profile_evidence(issues),
        },
        "review": profile_reviews(reviews_by_issue, knowledge_keys),
        "outliers": build_outliers(issues, reviews_by_issue, top_n),
        "integrity": integrity,
        "notes": {
            "statement_length_unit": "Unicode character count (Python len)",
            "token_count": "not measured; exact BGE-M3 tokenizer analysis is deferred to M8",
            "item_count_definition": "issue_summary 1개 + 5개 array category의 모든 item",
            "outlier_content_policy": "statement text is not copied into profile.json",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("knowledge_dir", type=Path)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-issue-count", type=int)
    parser.add_argument("--top-n", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.top_n < 1:
        print(json.dumps({"error": "--top-n must be >= 1"}, ensure_ascii=False))
        return 2
    for path in (args.knowledge_dir, args.review_dir):
        if not path.is_dir():
            print(json.dumps({"error": f"missing directory: {path}"}, ensure_ascii=False))
            return 2

    profile = build_profile(
        args.knowledge_dir,
        args.review_dir,
        args.expected_issue_count,
        args.top_n,
    )
    text = json.dumps(profile, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if profile["integrity"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
