from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


_FORBIDDEN_KEYS = {"source_path", "source_page"}


@dataclass(frozen=True)
class M10RealRunValidation:
    search_result_count: int
    evidence_count: int
    warning_count: int
    path_leak_count: int
    issue_lookup_ok: bool
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


def validate_m10_payloads(
    search_payload: Mapping[str, object],
    issue_payload: Mapping[str, object],
) -> M10RealRunValidation:
    """MCP 응답 내용을 출력하지 않고 M10 Real-run Gate 조건만 검사합니다."""

    failures: list[str] = []
    results = _list_value(search_payload.get("results"))
    warnings = _list_value(search_payload.get("warnings"))
    if not results:
        failures.append("검색 결과가 없습니다.")
    if warnings:
        failures.append("Real-run 검색 결과에 warning이 있습니다.")

    evidence_count = 0
    first_issue_key: str | None = None
    for index, raw_result in enumerate(results):
        if not isinstance(raw_result, Mapping):
            failures.append(f"results[{index}]가 object가 아닙니다.")
            continue
        issue = raw_result.get("issue")
        issue_key = issue.get("issue_key") if isinstance(issue, Mapping) else None
        if not isinstance(issue_key, str) or not issue_key:
            failures.append(f"results[{index}]에 issue_key가 없습니다.")
        elif first_issue_key is None:
            first_issue_key = issue_key
        statement = raw_result.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            failures.append(f"results[{index}]에 statement가 없습니다.")
        evidence = _list_value(raw_result.get("evidence"))
        if not evidence:
            failures.append(f"results[{index}]에 Evidence가 없습니다.")
        evidence_count += len(evidence)

    issue_lookup_ok = _validate_issue_lookup(issue_payload, first_issue_key)
    if not issue_lookup_ok:
        failures.append("get_jira_issue 결과가 검색 결과의 Issue와 일치하지 않습니다.")

    path_leak_count = _count_forbidden_keys(search_payload) + _count_forbidden_keys(issue_payload)
    if path_leak_count:
        failures.append("MCP 응답에 내부 source path 필드가 노출됐습니다.")

    return M10RealRunValidation(
        search_result_count=len(results),
        evidence_count=evidence_count,
        warning_count=len(warnings),
        path_leak_count=path_leak_count,
        issue_lookup_ok=issue_lookup_ok,
        failures=tuple(failures),
    )


def _validate_issue_lookup(payload: Mapping[str, object], expected_key: str | None) -> bool:
    if expected_key is None:
        return False
    issue = payload.get("issue")
    return isinstance(issue, Mapping) and issue.get("issue_key") == expected_key


def _count_forbidden_keys(value: object) -> int:
    if isinstance(value, Mapping):
        count = sum(1 for key in value if str(key) in _FORBIDDEN_KEYS)
        return count + sum(_count_forbidden_keys(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_forbidden_keys(child) for child in value)
    return 0


def _list_value(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []
