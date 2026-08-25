#!/usr/bin/env python3
"""M7 실데이터 Gate를 materialize 2회와 DB integrity 검사로 자동 판정한다."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _PROJECT_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from jira_collector.knowledge_db import KnowledgeDbError, KnowledgeDbMaterializer
from jira_collector.knowledge_db.validation import (
    expected_counts_from_profile,
    snapshot_database,
    validate_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--database", help="검증용 SQLite 경로")
    parser.add_argument("--profile", help="M5 profile.json 경로")
    parser.add_argument("--skill-version", default="0.9")
    parser.add_argument("--runtime-version", default="0.9")
    parser.add_argument("--model-profile", required=True)
    parser.add_argument("--review-schema-version", default="0.3")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="기존 검증 DB가 있으면 삭제하고 처음부터 검사",
    )
    parser.add_argument("--report", help="Gate 결과 JSON 저장 경로")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data_root = Path(args.data_root).resolve()
    database = _database_path(data_root, args.run_id, args.database)
    profile = _profile_path(data_root, args.run_id, args.profile)
    report = _report_path(data_root, args.run_id, args.report)

    try:
        _prepare_database(database, args.reset)
        expected = expected_counts_from_profile(profile)
        materializer = KnowledgeDbMaterializer(
            data_root,
            database,
            skill_version=args.skill_version,
            runtime_version=args.runtime_version,
            model_profile=args.model_profile,
            review_schema_version=args.review_schema_version,
        )
        first_result = materializer.materialize_run(args.run_id)
        first_snapshot = snapshot_database(database)
        second_result = materializer.materialize_run(args.run_id)
        second_snapshot = snapshot_database(database)
        failures = _gate_failures(
            expected,
            first_result,
            second_result,
            first_snapshot,
            second_snapshot,
        )
    except (KnowledgeDbError, ValueError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    payload = {
        "gate": "M7_REAL_RUN",
        "run_id": args.run_id,
        "status": "PASS" if not failures else "FAIL",
        "database": str(database),
        "profile": str(profile),
        "expected": asdict(expected),
        "first_snapshot": first_snapshot.to_dict(),
        "second_snapshot": second_snapshot.to_dict(),
        "idempotent": first_snapshot == second_snapshot,
        "failures": failures,
    }
    _write_report(report, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def _gate_failures(expected, first_result, second_result, first_snapshot, second_snapshot):
    failures = validate_snapshot(first_snapshot, expected)
    failures.extend(f"second_run: {value}" for value in validate_snapshot(second_snapshot, expected))
    if first_snapshot != second_snapshot:
        failures.append("same-run idempotency failure: first/second DB snapshot differs")
    if first_result != second_result:
        failures.append("same-run materialization result differs")
    return failures


def _database_path(data_root: Path, run_id: str, raw: str | None) -> Path:
    if raw:
        return Path(raw).resolve()
    return data_root / "knowledge_db" / "validation" / f"{run_id}.sqlite3"


def _profile_path(data_root: Path, run_id: str, raw: str | None) -> Path:
    if raw:
        return Path(raw).resolve()
    return data_root / "knowledge" / "runs" / run_id / "profile.json"


def _report_path(data_root: Path, run_id: str, raw: str | None) -> Path:
    if raw:
        return Path(raw).resolve()
    return data_root / "knowledge_db" / "validation" / f"{run_id}.gate.json"


def _prepare_database(path: Path, reset: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = [candidate for candidate in _sqlite_files(path) if candidate.exists()]
    if existing and not reset:
        raise KnowledgeDbError(
            f"검증 DB가 이미 있습니다: {path}. 새 Gate 검증은 --reset으로 시작하세요."
        )
    if reset:
        for candidate in existing:
            candidate.unlink()


def _sqlite_files(path: Path) -> tuple[Path, Path, Path]:
    return path, Path(str(path) + "-wal"), Path(str(path) + "-shm")


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
