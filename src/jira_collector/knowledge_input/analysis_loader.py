from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .models import KnowledgeInputBuildError


# Knowledge Input은 ANALYSIS를 공식 입력 계약으로 사용하므로 아래 파일이 모두 필요합니다.
_REQUIRED_FILES = (
    "issues.jsonl",
    "comments.jsonl",
    "attachments.jsonl",
    "issue_relationships.jsonl",
    "custom_field_catalog.jsonl",
    "custom_field_values.jsonl",
)

# 파일 존재만으로는 충분하지 않습니다. 이전 Export 단계가 정상 완료됐는지도 확인합니다.
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

        # 이후 경로 검증에서 상대 경로 해석 차이가 생기지 않도록 초기화 시 절대 경로로 고정합니다.
        self.analysis_root = analysis_root.resolve()

    def load(self, run_id: str) -> dict[str, Any]:
        """필수 파일과 summary 완료 상태를 확인한 뒤 조립용 인덱스를 반환합니다."""

        # run_id가 ../ 같은 경로 조작으로 ANALYSIS 루트 밖을 가리키지 못하게 방어합니다.
        run_root = (self.analysis_root / run_id).resolve()
        if run_root != self.analysis_root and self.analysis_root not in run_root.parents:
            raise KnowledgeInputBuildError(f"ANALYSIS 루트 밖의 경로입니다: {run_root}")

        # Knowledge Input 스키마가 요구하는 ANALYSIS 파일이 모두 존재하는지 먼저 확인합니다.
        paths = {name: run_root / name for name in _REQUIRED_FILES}
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing:
            raise KnowledgeInputBuildError(
                "필수 ANALYSIS 파일이 없습니다: " + ", ".join(sorted(missing))
            )

        # 불완전한 Export 결과를 최종 Agent 입력으로 넘기지 않도록 summary 완료 상태를 게이트로 사용합니다.
        summary_path = run_root / "summary.json"
        self._validate_summary(summary_path, run_id)

        warnings: list[dict[str, Any]] = []

        # Issue와 Catalog는 식별자가 유일해야 하므로 바로 key 기반 사전으로 만듭니다.
        # 중복을 조용히 덮어쓰지 않고 오류로 처리해 결정성을 보장합니다.
        issues = self._unique_map(paths["issues.jsonl"], run_id, "issue_key", "Issue")
        catalog = self._unique_map(
            paths["custom_field_catalog.jsonl"],
            run_id,
            "field_id",
            "Custom Field Catalog",
        )

        # 다대일 구조의 데이터는 issue_key 기준으로 묶어 Builder가 JOIN하기 쉽게 준비합니다.
        comments = self._group_issue_rows(
            paths["comments.jsonl"], run_id, issues, warnings
        )
        attachments = self._group_issue_rows(
            paths["attachments.jsonl"], run_id, issues, warnings
        )
        custom_values = self._group_issue_rows(
            paths["custom_field_values.jsonl"], run_id, issues, warnings
        )

        # Relationship은 ANALYSIS의 canonical edge를 그대로 읽은 뒤 양 endpoint 패키지에서 볼 수 있게 인덱싱합니다.
        relationship_rows = list(
            self._read_jsonl(paths["issue_relationships.jsonl"], run_id)
        )
        relationships = self._relationship_index(
            relationship_rows, issues, warnings
        )

        # Builder는 아래 인덱스만 사용하므로 이후 단계가 RAW/Jira 구조에 다시 의존하지 않습니다.
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

        # summary.json은 각 Exporter의 완료 여부를 표현하는 ANALYSIS 완료 계약입니다.
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise KnowledgeInputBuildError(
                f"ANALYSIS summary.json을 읽을 수 없습니다: {path}: {exc}"
            ) from exc

        # 다른 run의 summary를 잘못 합치는 상황을 방지합니다.
        if not isinstance(doc, dict) or doc.get("run_id") != run_id:
            raise KnowledgeInputBuildError(
                f"summary.json 구조 또는 run_id가 잘못됐습니다: {path}"
            )

        # Issue/Comment만 완료되고 Structure가 덜 끝난 경우에도 패키지는 만들지 않습니다.
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

            # Join 기준 key가 없으면 어느 패키지에 넣어야 할지 결정할 수 없으므로 치명적 오류입니다.
            if not isinstance(key, str) or not key.strip():
                raise KnowledgeInputBuildError(
                    f"{label} 레코드에 {key_name}가 없습니다."
                )

            key = key.strip()

            # 첫 값/마지막 값을 임의 선택하지 않고 중복 자체를 데이터 계약 위반으로 처리합니다.
            if key in result:
                raise KnowledgeInputBuildError(
                    f"{label}에 중복 {key_name}가 있습니다: {key}"
                )
            result[key] = row

        # Issue가 하나도 없다면 패키지 run 자체가 의미가 없으므로 조용히 빈 manifest를 만들지 않습니다.
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

            # 개별 부가 레코드 오류는 전체 run을 즉시 중단하지 않고 경고로 격리합니다.
            if not isinstance(key, str) or not key.strip():
                warnings.append(
                    self._warning("error", "missing_issue_key", path.name)
                )
                continue

            key = key.strip()

            # issues.jsonl에 없는 레코드는 고아 데이터이므로 어떤 패키지에도 넣지 않습니다.
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

            # canonical edge의 양 끝점이 없으면 관계 의미를 보존할 수 없으므로 해당 레코드를 제외합니다.
            if not isinstance(source, str) or not isinstance(target, str):
                warnings.append(
                    self._warning(
                        "error",
                        "invalid_relationship_endpoint",
                        "issue_relationships.jsonl",
                    )
                )
                continue

            # 양 endpoint가 모두 현재 파일럿 밖이면 연결할 package가 없으므로 warning만 남깁니다.
            if source not in known and target not in known:
                warnings.append(
                    self._warning(
                        "warning",
                        "relationship_outside_package_scope",
                        "issue_relationships.jsonl",
                    )
                )
                continue

            # 현재 Issue가 canonical source이면 outgoing 관점을 추가합니다.
            if source in known:
                indexed[source].append(
                    self._relationship_view(
                        row,
                        "source",
                        target,
                        target in known,
                    )
                )

            # 현재 Issue가 canonical target이면 incoming 관점을 추가합니다.
            # self-loop 관계는 같은 package에 두 번 넣지 않습니다.
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

        # 원본 ANALYSIS edge를 복사한 뒤 Agent가 현재 Issue 관점에서 읽을 보조 필드만 덧붙입니다.
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
                    # 빈 줄은 데이터 레코드로 보지 않습니다.
                    if not line.strip():
                        continue

                    row = json.loads(line)

                    # JSON 값이더라도 객체가 아니면 ANALYSIS 저장 계약을 위반한 것입니다.
                    if not isinstance(row, dict):
                        raise KnowledgeInputBuildError(
                            f"JSONL 객체 형식 오류: {path}:{number}"
                        )

                    # 여러 run의 JSONL이 섞이는 것을 조기에 차단합니다.
                    if row.get("run_id") != run_id:
                        raise KnowledgeInputBuildError(
                            f"run_id 불일치: {path}:{number}"
                        )
                    yield row
        except KnowledgeInputBuildError:
            # 이미 의미 있는 도메인 오류는 원문 메시지를 유지합니다.
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            # 파일/인코딩/JSON 오류를 동일한 상위 BuildError로 정규화합니다.
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
