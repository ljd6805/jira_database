from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jira_collector.exporter.atomic_writer import AtomicTextWriter

from .analysis_loader import AnalysisRunLoader
from .models import KnowledgeInputBuildError, KnowledgeInputBuildResult


_SAFE_ISSUE_KEY = re.compile(r"^[A-Za-z0-9._-]+$")


class IssueKnowledgeInputBuilder:
    """ANALYSIS에 흩어진 사실을 이슈 하나당 JSON 한 파일로 조립합니다."""

    SCHEMA_VERSION = "1.0"

    def __init__(
        self,
        data_root: str | Path,
        analysis_directory: str = "analysis",
        knowledge_input_directory: str = "knowledge_input",
    ) -> None:
        """ANALYSIS 입력 루트와 KNOWLEDGE INPUT 출력 루트를 초기화합니다."""

        self.data_root = Path(data_root).resolve()
        self.analysis_root = (self.data_root / analysis_directory).resolve()
        self.output_root = (
            self.data_root / knowledge_input_directory / "runs"
        ).resolve()
        self.loader = AnalysisRunLoader(self.analysis_root)
        self.writer = AtomicTextWriter(self.output_root)

    def build_run(self, run_id: str) -> KnowledgeInputBuildResult:
        """완료된 ANALYSIS run에서 package, package_warnings, manifest를 생성합니다."""

        loaded = self.loader.load(run_id)
        warnings = loaded["warnings"]
        manifest_relative = Path(run_id) / "manifest.json"
        manifest_path = (self.output_root / manifest_relative).resolve()

        # manifest는 완료 표식이다. 빌드 도중 중단되면 manifest가 없어야 한다.
        try:
            manifest_path.unlink()
        except FileNotFoundError:
            pass

        generated_at = self._utc_now()
        issues_relative = Path(run_id) / "issues"
        expected_files: set[str] = set()
        entries: list[dict[str, Any]] = []
        issues = loaded["issues"]

        for issue_key in sorted(issues):
            filename = self._issue_filename(issue_key)
            expected_files.add(filename)
            package = self._package(
                run_id,
                issues[issue_key],
                loaded["comments"].get(issue_key, []),
                loaded["attachments"].get(issue_key, []),
                loaded["relationships"].get(issue_key, []),
                loaded["custom_values"].get(issue_key, []),
                loaded["catalog"],
                generated_at,
                warnings,
            )
            relative = issues_relative / filename
            self.writer.write_text(
                relative,
                json.dumps(package, ensure_ascii=False, indent=2) + "\n",
            )
            entries.append(
                {
                    "issue_key": issue_key,
                    "path": relative.as_posix(),
                    "source_hash": package["source_hash"],
                    **package["counts"],
                }
            )

        self._remove_stale(
            (self.output_root / issues_relative).resolve(),
            expected_files,
        )
        for warning in warnings:
            warning.setdefault("run_id", run_id)
        warnings_path = self._write_warnings(run_id, warnings)
        manifest = self._manifest(
            run_id,
            loaded,
            entries,
            warnings_path,
            generated_at,
        )
        self.writer.write_text(
            manifest_relative,
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

        return KnowledgeInputBuildResult(
            run_id=run_id,
            issue_count=len(issues),
            package_count=len(entries),
            comment_count=manifest["comment_count"],
            attachment_count=manifest["attachment_count"],
            relationship_count=manifest["relationship_count"],
            custom_field_value_count=manifest["custom_field_value_count"],
            warning_count=len(warnings),
            issues_directory=(self.output_root / issues_relative).resolve(),
            manifest_path=manifest_path,
            warnings_path=warnings_path,
        )

    def _package(
        self,
        run_id: str,
        issue: dict[str, Any],
        comments: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        custom_values: list[dict[str, Any]],
        catalog: dict[str, dict[str, Any]],
        generated_at: str,
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """한 이슈의 ANALYSIS 레코드를 계층형 입력 패키지로 바꿉니다."""

        issue_key = str(issue["issue_key"])
        issue_doc = self._issue_doc(issue)
        comment_docs = [
            self._comment_doc(item)
            for item in sorted(comments, key=self._comment_sort)
        ]
        attachment_docs = [
            self._attachment_doc(item)
            for item in sorted(
                attachments,
                key=lambda item: str(item.get("attachment_id") or ""),
            )
        ]
        relation_docs = [self._relationship_doc(item) for item in relationships]
        relation_docs.sort(
            key=lambda item: (
                str(item.get("relationship_category") or ""),
                str(item.get("relationship_type") or ""),
                str(item.get("other_issue_key") or ""),
            )
        )

        field_docs: list[dict[str, Any]] = []
        for value in sorted(
            custom_values,
            key=lambda item: str(item.get("field_id") or ""),
        ):
            field_id = str(value.get("field_id") or "")
            definition = catalog.get(field_id, {})
            if not definition:
                warnings.append(
                    {
                        "severity": "warning",
                        "code": "custom_field_definition_missing",
                        "issue_key": issue_key,
                        "source_file": "custom_field_values.jsonl",
                    }
                )
            field_docs.append(self._field_doc(value, definition))

        # source_hash는 의미 데이터만 사용한다. PC 절대 경로나 생성 시각은 제외한다.
        hash_material = self._strip_paths(
            {
                "issue": issue_doc,
                "comments": comment_docs,
                "attachments": attachment_docs,
                "relationships": relation_docs,
                "custom_fields": field_docs,
            }
        )
        source_hash = "sha256:" + hashlib.sha256(
            json.dumps(
                hash_material,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        return {
            "package_schema_version": self.SCHEMA_VERSION,
            "run_id": run_id,
            "project_key": issue.get("project_key"),
            "issue_key": issue_key,
            "generated_at": generated_at,
            "source_hash": source_hash,
            "issue": issue_doc,
            "comments": comment_docs,
            "attachments": attachment_docs,
            "relationships": relation_docs,
            "custom_fields": field_docs,
            "counts": {
                "comment_count": len(comment_docs),
                "attachment_count": len(attachment_docs),
                "relationship_count": len(relation_docs),
                "custom_field_count": len(field_docs),
            },
        }

    def _manifest(
        self,
        run_id: str,
        loaded: dict[str, Any],
        entries: list[dict[str, Any]],
        warnings_path: Path,
        generated_at: str,
    ) -> dict[str, Any]:
        """전체 패키지 생성 상태와 입력 ANALYSIS 파일을 기록합니다."""

        warnings = loaded["warnings"]
        return {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": run_id,
            "generated_at": generated_at,
            "status": (
                "partial"
                if any(item.get("severity") == "error" for item in warnings)
                else "completed"
            ),
            "issue_count": len(loaded["issues"]),
            "package_count": len(entries),
            "comment_count": sum(map(len, loaded["comments"].values())),
            "attachment_count": sum(map(len, loaded["attachments"].values())),
            "relationship_count": len(loaded["relationship_rows"]),
            "custom_field_catalog_count": len(loaded["catalog"]),
            "custom_field_value_count": sum(
                map(len, loaded["custom_values"].values())
            ),
            "warning_count": len(warnings),
            "input_files": {
                **{
                    name.removesuffix(".jsonl"): self._relative(path)
                    for name, path in loaded["paths"].items()
                },
                "summary": self._relative(loaded["summary_path"]),
            },
            "warnings_file": self._relative(warnings_path),
            "packages": entries,
        }

    def _issue_doc(self, item: dict[str, Any]) -> dict[str, Any]:
        """Issue 핵심 필드를 분석 입력 구조로 선택합니다."""

        return {
            "jira_id": item.get("jira_id"),
            "summary": item.get("summary"),
            "description": item.get("description_text"),
            "description_format": item.get("description_format"),
            "issue_type": item.get("issue_type"),
            "status": item.get("status"),
            "priority": item.get("priority"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "source_path": self._portable_path(item.get("source_path")),
        }

    def _comment_doc(self, item: dict[str, Any]) -> dict[str, Any]:
        """댓글의 시간 순서와 출처를 유지한 입력 구조를 만듭니다."""

        return {
            "comment_id": item.get("comment_id"),
            "sequence": item.get("sequence"),
            "author_name": item.get("author_name"),
            "author_key": item.get("author_key"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "body": item.get("body_text"),
            "body_format": item.get("body_format"),
            "source_path": self._portable_path(item.get("source_path")),
            "source_page": item.get("source_page"),
        }

    def _attachment_doc(self, item: dict[str, Any]) -> dict[str, Any]:
        """첨부파일은 메타데이터만 포함하고 본문 미수집 상태를 명시합니다."""

        return {
            "attachment_id": item.get("attachment_id"),
            "filename": item.get("filename"),
            "author_name": item.get("author_name"),
            "author_key": item.get("author_key"),
            "created_at": item.get("created_at"),
            "size_bytes": item.get("size_bytes"),
            "mime_type": item.get("mime_type"),
            "content_available": False,
            "source_path": self._portable_path(item.get("source_path")),
        }

    def _relationship_doc(self, item: dict[str, Any]) -> dict[str, Any]:
        """canonical 관계와 현재 이슈의 source/target 관점을 함께 유지합니다."""

        return {
            "relationship_id": item.get("relationship_id"),
            "relationship_category": item.get("relationship_category"),
            "relationship_type": item.get("relationship_type"),
            "relationship_text": item.get("relationship_text"),
            "source_issue_key": item.get("source_issue_key"),
            "target_issue_key": item.get("target_issue_key"),
            "current_issue_role": item.get("current_issue_role"),
            "current_issue_direction": item.get("current_issue_direction"),
            "other_issue_key": item.get("other_issue_key"),
            "other_package_available": item.get("other_package_available"),
            "source_summary": item.get("source_summary"),
            "source_status": item.get("source_status"),
            "target_summary": item.get("target_summary"),
            "target_status": item.get("target_status"),
            "derived": item.get("derived"),
            "source_path": self._portable_path(item.get("source_path")),
        }

    def _field_doc(
        self,
        value: dict[str, Any],
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        """Catalog와 Value를 합치되 ANALYSIS에 없는 개인정보는 다시 꺼내지 않습니다."""

        return {
            "field_id": value.get("field_id"),
            "field_name": value.get("field_name") or definition.get("field_name"),
            "schema_type": value.get("schema_type") or definition.get("schema_type"),
            "schema_items": value.get("schema_items") or definition.get("schema_items"),
            "schema_custom": value.get("schema_custom") or definition.get("schema_custom"),
            "actual_type": value.get("actual_type"),
            "value_kind": value.get("value_kind"),
            "display_value": value.get("display_value"),
            "display_values": value.get("display_values") or [],
            "value_id": value.get("value_id"),
            "value_ids": value.get("value_ids") or [],
            "user_keys": value.get("user_keys") or [],
            "value_shape": value.get("value_shape") or [],
            "source_path": self._portable_path(value.get("source_path")),
        }

    def _write_warnings(
        self,
        run_id: str,
        warnings: list[dict[str, Any]],
    ) -> Path:
        """패키지 조립 중 발견한 정합성 경고를 별도 JSONL로 저장합니다."""

        relative = Path(run_id) / "package_warnings.jsonl"
        with self.writer.open_text(relative) as handle:
            for row in warnings:
                handle.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        return (self.output_root / relative).resolve()

    def _portable_path(self, value: Any) -> str | None:
        """가능한 경우 source_path를 data_root 기준 상대 경로로 바꿉니다."""

        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return Path(value).resolve().relative_to(self.data_root).as_posix()
        except (OSError, ValueError):
            return value

    @classmethod
    def _strip_paths(cls, value: Any) -> Any:
        """PC별 경로 차이가 source_hash를 바꾸지 않도록 경로 필드를 제외합니다."""

        if isinstance(value, list):
            return [cls._strip_paths(item) for item in value]
        if isinstance(value, dict):
            return {
                key: cls._strip_paths(item)
                for key, item in value.items()
                if key not in {"source_path", "source_page"}
            }
        return value

    @staticmethod
    def _comment_sort(item: dict[str, Any]) -> tuple[int, str]:
        """댓글 sequence를 우선해 재현 가능한 순서를 만듭니다."""

        sequence = item.get("sequence")
        return (
            sequence if isinstance(sequence, int) else 2**31 - 1,
            str(item.get("comment_id") or ""),
        )

    @staticmethod
    def _issue_filename(issue_key: str) -> str:
        """issue_key를 디렉터리 탈출이 불가능한 파일명으로 검증합니다."""

        if not _SAFE_ISSUE_KEY.fullmatch(issue_key):
            raise KnowledgeInputBuildError(
                f"안전하지 않은 issue_key 파일명입니다: {issue_key!r}"
            )
        return issue_key + ".json"

    @staticmethod
    def _remove_stale(directory: Path, expected: set[str]) -> None:
        """동일 run 재생성 시 더 이상 존재하지 않는 과거 package를 제거합니다."""

        if directory.is_dir():
            for path in directory.glob("*.json"):
                if path.name not in expected:
                    path.unlink()

    def _relative(self, path: Path) -> str:
        """파일 위치를 data_root 기준 상대 경로로 기록합니다."""

        return path.resolve().relative_to(self.data_root).as_posix()

    @staticmethod
    def _utc_now() -> str:
        """UTC ISO 8601 시각을 반환합니다."""

        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
