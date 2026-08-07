from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .models import KnowledgeInputBuildError


_REQUIRED_FILES = (
    "issues.jsonl",
    "comments.jsonl",
    "attachments.jsonl",
    "issue_relationships.jsonl",
    "custom_field_catalog.jsonl",
    "custom_field_values.jsonl",
)
_REQUIRED_SECTIONS = (
    "issues",
    "comments",
    "attachments",
    "relationships",
    "custom_fields",
)


class AnalysisRunLoader:
    """완료된 ANALYSIS run의 JSONL을 검증하고 이슈 단위로 인덱싱합니다."""

    def __init__(self, analysis_root: Path) -> None:
        """ANALYSIS 루트를 절대 경로로 고정합니다."""

        self.analysis_root = analysis_root.resolve()

    def load(self, run_id: str) -> dict[str, Any]:
        """필수 파일과 summary 완료 상태를 확인한 뒤 조립용 인덱스를 반환합니다."""

        run_root = (self.analysis_root / run_id).resolve()
        if run_root != self.analysis_root and self.analysis_root not in run_root.parents:
            raise KnowledgeInputBuildError(f"ANALYSIS 루트 밖의 경로입니다: {run_root}")

        paths = {name: run_root / name for name in _REQUIRED_FILES}
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing:
            raise KnowledgeInputBuildError(
                "필수 ANALYSIS 파일이 없습니다: " + ", ".join(sorted(missing))
            )

        summary_path = run_root / "summary.json"
        self._validate_summary(summary_path, run_id)

        warnings: list[dict[str, Any]] = []
        issues = self._unique_map(paths["issues.jsonl"], run_id, "issue_key", "Issue")
        catalog = self._unique_map(
            paths["custom_field_catalog.jsonl"],
            run_id,
            "field_id",
            "Custom Field Catalog",
        )
        comments = self._group_issue_rows(
            paths["comments.jsonl"], run_id, issues, warnings
        )
        attachments = self._group_issue_rows(
            paths["attachments.jsonl"], run_id, issues, warnings
        )
        custom_values = self._group_issue_rows(
            paths["custom_field_values.jsonl"], run_id, issues, warnings
        )
        relationship_rows = list(
            self._read_jsonl(paths["issue_relationships.jsonl"], run_id)
        )
        relationships = self._relationship_index(
            relationship_rows, issues, warnings
        )

        return {
            "paths": paths,
            "summary_path": summary_path,
            "issues": issues,
            "catalog": catalog,
            "comments": comments,
            "attachments": attachments,
            "custom_values": custom_values,
            "relationship_rows": relationship_rows,
            "relationships": relationships,
            "warnings": warnings,
        }

    def _validate_summary(self, path: Path, run_id: str) -> None:
        """불완전한 ANALYSIS 결과가 다음 계층으로 넘어가지 않도록 막습니다."""

        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise KnowledgeInputBuildError(
                f"ANALYSIS summary.json을 읽을 수 없습니다: {path}: {exc}"
            ) from exc

        if not isinstance(doc, dict) or doc.get("run_id") != run_id:
            raise KnowledgeInputBuildError(
                f"summary.json 구조 또는 run_id가 잘못됐습니다: {path}"
            )

        incomplete = [
            name
            for name in _REQUIRED_SECTIONS
            if not isinstance(doc.get(name), dict)
            or doc[name].get("status") != "completed"
        ]
        if incomplete:
            raise KnowledgeInputBuildError(
                "Knowledge Input 생성 전 completed여야 하는 ANALYSIS 영역: "
                + ", ".join(incomplete)
            )

    def _unique_map(
        self,
        path: Path,
        run_id: str,
        key_name: str,
        label: str,
    ) -> dict[str, dict[str, Any]]:
        """JSONL을 유일 식별자 기준 사전으로 읽습니다."""

        result: dict[str, dict[str, Any]] = {}
        for row in self._read_jsonl(path, run_id):
            key = row.get(key_name)
            if not isinstance(key, str) or not key.strip():
                raise KnowledgeInputBuildError(
                    f"{label} 레코드에 {key_name}가 없습니다."
                )
            key = key.strip()
            if key in result:
                raise KnowledgeInputBuildError(
                    f"{label}에 중복 {key_name}가 있습니다: {key}"
                )
            result[key] = row

        if label == "Issue" and not result:
            raise KnowledgeInputBuildError("issues.jsonl에 이슈가 없습니다.")
        return result

    def _group_issue_rows(
        self,
        path: Path,
        run_id: str,
        issues: dict[str, dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """issue_key 기준으로 레코드를 묶고 고아 레코드를 경고합니다."""

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in self._read_jsonl(path, run_id):
            key = row.get("issue_key")
            if not isinstance(key, str) or not key.strip():
                warnings.append(
                    self._warning("error", "missing_issue_key", path.name)
                )
                continue

            key = key.strip()
            if key not in issues:
                warnings.append(
                    self._warning(
                        "error",
                        "orphan_analysis_record",
                        path.name,
                        key,
                    )
                )
                continue
            grouped[key].append(row)
        return dict(grouped)

    def _relationship_index(
        self,
        rows: list[dict[str, Any]],
        issues: dict[str, dict[str, Any]],
        warnings: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """canonical edge를 양 endpoint 패키지에서 볼 수 있는 현재 이슈 관점으로 만듭니다."""

        indexed: dict[str, list[dict[str, Any]]] = defaultdict(list)
        known = set(issues)

        for row in rows:
            source = row.get("source_issue_key")
            target = row.get("target_issue_key")
            if not isinstance(source, str) or not isinstance(target, str):
                warnings.append(
                    self._warning(
                        "error",
                        "invalid_relationship_endpoint",
                        "issue_relationships.jsonl",
                    )
                )
                continue

            if source not in known and target not in known:
                warnings.append(
                    self._warning(
                        "warning",
                        "relationship_outside_package_scope",
                        "issue_relationships.jsonl",
                    )
                )
                continue

            if source in known:
                indexed[source].append(
                    self._relationship_view(
                        row,
                        "source",
                        target,
                        target in known,
                    )
                )
            if target in known and target != source:
                indexed[target].append(
                    self._relationship_view(
                        row,
                        "target",
                        source,
                        source in known,
                    )
                )
        return dict(indexed)

    @staticmethod
    def _relationship_view(
        row: dict[str, Any],
        role: str,
        other: str,
        available: bool,
    ) -> dict[str, Any]:
        """canonical 관계는 보존하고 현재 이슈의 source/target 관점만 추가합니다."""

        result = dict(row)
        result.update(
            {
                "current_issue_role": role,
                "current_issue_direction": (
                    "outgoing" if role == "source" else "incoming"
                ),
                "other_issue_key": other,
                "other_package_available": available,
            }
        )
        return result

    def _read_jsonl(
        self,
        path: Path,
        run_id: str,
    ) -> Iterable[dict[str, Any]]:
        """JSONL을 줄 단위로 읽으며 객체 형식과 run_id를 검증합니다."""

        try:
            with path.open("r", encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise KnowledgeInputBuildError(
                            f"JSONL 객체 형식 오류: {path}:{number}"
                        )
                    if row.get("run_id") != run_id:
                        raise KnowledgeInputBuildError(
                            f"run_id 불일치: {path}:{number}"
                        )
                    yield row
        except KnowledgeInputBuildError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise KnowledgeInputBuildError(
                f"JSONL 읽기 실패: {path}: {exc}"
            ) from exc

    @staticmethod
    def _warning(
        severity: str,
        code: str,
        source_file: str,
        issue_key: str | None = None,
    ) -> dict[str, Any]:
        """Knowledge Input 정합성 경고의 공통 형식을 만듭니다."""

        return {
            "severity": severity,
            "code": code,
            "issue_key": issue_key,
            "source_file": source_file,
        }
