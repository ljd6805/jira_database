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


# issue_key는 그대로 파일명이 되므로 디렉터리 탈출 문자나 경로 구분자를 허용하지 않습니다.
_SAFE_ISSUE_KEY = re.compile(r"^[A-Za-z0-9._-]+$")


class IssueKnowledgeInputBuilder:
    """ANALYSIS에 흩어진 사실을 이슈 하나당 JSON 한 파일로 조립합니다."""

    SCHEMA_VERSION = "1.0"
    SOURCE_HASH_PROFILE = "semantic_v2"

    def __init__(
        self,
        data_root: str | Path,
        analysis_directory: str = "analysis",
        knowledge_input_directory: str = "knowledge_input",
    ) -> None:
        """ANALYSIS 입력 루트와 KNOWLEDGE INPUT 출력 루트를 초기화합니다."""

        # 모든 경로를 절대 경로로 고정해 실행 위치에 따른 상대 경로 해석 차이를 없앱니다.
        self.data_root = Path(data_root).resolve()
        self.analysis_root = (self.data_root / analysis_directory).resolve()
        self.output_root = (
            self.data_root / knowledge_input_directory / "runs"
        ).resolve()

        # Loader는 ANALYSIS 계약 검증과 issue_key 인덱싱을 담당하고,
        # Builder는 검증된 데이터의 조립과 파일 출력을 담당합니다.
        self.loader = AnalysisRunLoader(self.analysis_root)
        self.writer = AtomicTextWriter(self.output_root)

    def build_run(self, run_id: str) -> KnowledgeInputBuildResult:
        """완료된 ANALYSIS run에서 package, package_warnings, manifest를 생성합니다."""

        # ANALYSIS 5개 영역이 모두 completed인지 확인한 뒤에만 실제 빌드를 시작합니다.
        loaded = self.loader.load(run_id)
        warnings = loaded["warnings"]
        manifest_relative = Path(run_id) / "manifest.json"
        manifest_path = (self.output_root / manifest_relative).resolve()

        # manifest는 run 전체의 완료 표식입니다.
        # 재실행 시작과 동시에 과거 manifest를 제거해 중간 실패를 완료 상태로 오해하지 않게 합니다.
        try:
            manifest_path.unlink()
        except FileNotFoundError:
            pass

        generated_at = self._utc_now()
        issues_relative = Path(run_id) / "issues"
        expected_files: set[str] = set()
        entries: list[dict[str, Any]] = []
        issues = loaded["issues"]

        # issue_key 순서로 처리해 파일 생성 순서와 manifest package 목록을 재현 가능하게 유지합니다.
        for issue_key in sorted(issues):
            filename = self._issue_filename(issue_key)
            expected_files.add(filename)

            # ANALYSIS의 여러 JSONL에서 이미 issue_key 기준으로 인덱싱한 데이터를 하나의 계층형 package로 조립합니다.
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

            # 각 Issue package도 기존 Exporter와 같은 AtomicTextWriter를 사용해 중간 파일 노출을 막습니다.
            relative = issues_relative / filename
            self.writer.write_text(
                relative,
                json.dumps(package, ensure_ascii=False, indent=2) + "\n",
            )

            # manifest에는 package를 다시 열지 않아도 증분 판단과 구성 건수를 확인할 수 있는 최소 index를 기록합니다.
            entries.append(
                {
                    "issue_key": issue_key,
                    "path": relative.as_posix(),
                    "source_hash": package["source_hash"],
                    "source_hash_profile": package["source_hash_profile"],
                    **package["counts"],
                }
            )

        # Knowledge Input은 append log가 아니라 현재 ANALYSIS snapshot의 재현물이므로 과거에만 있던 package를 제거합니다.
        self._remove_stale(
            (self.output_root / issues_relative).resolve(),
            expected_files,
        )

        # Loader와 Builder가 만든 경고에 run_id를 통일해 후속 자동화에서 단독으로 읽어도 출처를 알 수 있게 합니다.
        for warning in warnings:
            warning.setdefault("run_id", run_id)
        warnings_path = self._write_warnings(run_id, warnings)

        # manifest는 package와 warning 저장이 모두 끝난 뒤 생성합니다.
        # 이 순서를 유지해야 manifest 존재 자체를 완료 신호로 사용할 수 있습니다.
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

        # 각 하위 영역은 Agent에게 필요한 필드만 선택하며 RAW의 복잡한 객체를 다시 복제하지 않습니다.
        issue_doc = self._issue_doc(issue)

        # 댓글은 업무 논의 흐름이 중요하므로 sequence를 최우선으로 정렬합니다.
        comment_docs = [
            self._comment_doc(item)
            for item in sorted(comments, key=self._comment_sort)
        ]

        # Attachment는 현재 metadata만 있으므로 ID 기준의 안정된 순서로 정렬합니다.
        attachment_docs = [
            self._attachment_doc(item)
            for item in sorted(
                attachments,
                key=lambda item: str(item.get("attachment_id") or ""),
            )
        ]

        # canonical relationship에 현재 Issue 관점을 붙인 결과도 일정한 순서로 정렬해 hash 재현성을 확보합니다.
        relation_docs = [self._relationship_doc(item) for item in relationships]
        relation_docs.sort(
            key=lambda item: (
                str(item.get("relationship_category") or ""),
                str(item.get("relationship_type") or ""),
                str(item.get("other_issue_key") or ""),
            )
        )

        # Custom Field Value는 field_id로 Catalog 정의와 결합합니다.
        # 정의가 빠져 있어도 실제 값은 버리지 않고 warning을 남긴 뒤 최대한 package에 보존합니다.
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

        # semantic_v2는 Jira updated를 Delta 후보 탐색에만 사용하고 semantic identity에는 사용하지 않습니다.
        # package에는 updated_at을 그대로 남기지만 hash material에서는 Issue/Comment updated_at과 실행 파생 metadata를 제외합니다.
        hash_material = self._semantic_v2_hash_material(
            issue_doc=issue_doc,
            comment_docs=comment_docs,
            attachment_docs=attachment_docs,
            relation_docs=relation_docs,
            field_docs=field_docs,
        )

        # JSON key를 정렬하고 공백을 제거한 canonical 문자열을 사용해 같은 의미 입력의 hash를 안정적으로 만듭니다.
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
            "source_hash_profile": self.SOURCE_HASH_PROFILE,
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

        # warning은 정보성일 수 있지만 error가 하나라도 있으면 일부 Join이 누락됐을 가능성이 있으므로 partial로 표시합니다.
        status = (
            "partial"
            if any(item.get("severity") == "error" for item in warnings)
            else "completed"
        )

        return {
            "schema_version": self.SCHEMA_VERSION,
            "source_hash_profile": self.SOURCE_HASH_PROFILE,
            "run_id": run_id,
            "generated_at": generated_at,
            "status": status,
            "issue_count": len(loaded["issues"]),
            "package_count": len(entries),
            "comment_count": sum(map(len, loaded["comments"].values())),
            "attachment_count": sum(map(len, loaded["attachments"].values())),
            # 각 package에서 Relationship이 양 endpoint 관점으로 보일 수 있으므로 manifest는 원본 canonical edge 수를 기록합니다.
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

        # description_raw HTML이 아니라 ANALYSIS에서 정제한 description_text만 Agent 입력으로 사용합니다.
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

        # comment_id와 sequence를 모두 보존해 Agent 결과의 evidence를 특정 댓글로 역추적할 수 있게 합니다.
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

        # 현재 파일 바이너리를 수집하지 않았으므로 Agent가 내용을 읽었다고 오해하지 않게 false를 고정합니다.
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

        # DB/그래프용 canonical source/target과 Agent용 current issue 관점을 동시에 보존합니다.
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

        # value 쪽에 이름/스키마가 있으면 그것을 우선하고, 없을 때만 Catalog 정의를 보완 정보로 사용합니다.
        # RAW를 읽지 않으므로 emailAddress 같은 원본 사용자 정보는 이 단계에서 되살아나지 않습니다.
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

        # Warning 파일도 package와 마찬가지로 원자 교체해 부분 JSONL이 남지 않게 합니다.
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
            # 같은 data_root 아래의 절대 경로라면 이식 가능한 POSIX 상대 경로로 바꿉니다.
            return Path(value).resolve().relative_to(self.data_root).as_posix()
        except (OSError, ValueError):
            # 다른 OS에서 생성된 경로 등 안전하게 변환할 수 없는 문자열은 정보 손실 방지를 위해 그대로 둡니다.
            return value

    @classmethod
    def _semantic_v2_hash_material(
        cls,
        *,
        issue_doc: dict[str, Any],
        comment_docs: list[dict[str, Any]],
        attachment_docs: list[dict[str, Any]],
        relation_docs: list[dict[str, Any]],
        field_docs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """semantic_v2 계약에 맞는 canonical source hash 재료를 만듭니다."""

        issue_material = cls._strip_derived_metadata(issue_doc)
        if isinstance(issue_material, dict):
            issue_material.pop("updated_at", None)

        comment_material = cls._strip_derived_metadata(comment_docs)
        if isinstance(comment_material, list):
            for comment in comment_material:
                if isinstance(comment, dict):
                    comment.pop("updated_at", None)

        return {
            "issue": issue_material,
            "comments": comment_material,
            "attachments": cls._strip_derived_metadata(attachment_docs),
            "relationships": cls._strip_derived_metadata(relation_docs),
            "custom_fields": cls._strip_derived_metadata(field_docs),
        }

    @classmethod
    def _strip_derived_metadata(cls, value: Any) -> Any:
        """PC/실행 범위에 따라 달라지는 metadata가 semantic hash를 바꾸지 않게 제외합니다."""

        if isinstance(value, list):
            return [cls._strip_derived_metadata(item) for item in value]

        if isinstance(value, dict):
            return {
                key: cls._strip_derived_metadata(item)
                for key, item in value.items()
                if key
                not in {
                    "source_path",
                    "source_page",
                    "other_package_available",
                }
            }

        return value

    @staticmethod
    def _comment_sort(item: dict[str, Any]) -> tuple[int, str]:
        """댓글 sequence를 우선해 재현 가능한 순서를 만듭니다."""

        sequence = item.get("sequence")

        # sequence가 깨진 예외 데이터는 맨 뒤로 보내고 comment_id로 최종 순서를 고정합니다.
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
                    # 현재 ANALYSIS에 없는 이슈 파일을 남기면 snapshot 의미가 깨지므로 제거합니다.
                    path.unlink()

    def _relative(self, path: Path) -> str:
        """파일 위치를 data_root 기준 상대 경로로 기록합니다."""

        return path.resolve().relative_to(self.data_root).as_posix()

    @staticmethod
    def _utc_now() -> str:
        """UTC ISO 8601 시각을 반환합니다."""

        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
