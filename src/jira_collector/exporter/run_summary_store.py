from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .atomic_writer import AtomicTextWriter


class RunSummaryError(ValueError):
    """기존 summary.json을 안전하게 읽거나 병합할 수 없을 때 발생합니다."""


class RunSummaryStore:
    """run_id별 summary.json의 버전 변환과 단계별 통계 병합을 담당합니다."""

    SCHEMA_VERSION = "2.0"
    _SECTIONS = (
        "issues",
        "comments",
        "attachments",
        "relationships",
        "custom_fields",
    )
    _BASE_REQUIRED_SECTIONS = ("issues", "comments")

    def __init__(
        self,
        data_root: str | Path,
        analysis_directory: str = "analysis",
    ) -> None:
        """분석 결과 루트와 원자 저장 도구를 초기화합니다."""

        self.data_root = Path(data_root).resolve()
        self.analysis_root = (self.data_root / analysis_directory).resolve()
        self.writer = AtomicTextWriter(self.analysis_root)

    def update_section(
        self,
        run_id: str,
        section: str,
        section_document: dict[str, Any],
        output_files: dict[str, str],
    ) -> Path:
        """단일 영역 갱신을 다중 영역 원자 갱신 메서드에 위임합니다."""

        return self.update_sections(
            run_id,
            {section: section_document},
            output_files,
        )

    def update_sections(
        self,
        run_id: str,
        sections: dict[str, dict[str, Any]],
        output_files: dict[str, str],
    ) -> Path:
        """기존 다른 영역을 보존하면서 여러 분석 영역을 한 번의 원자 저장으로 갱신합니다."""

        unknown = sorted(set(sections) - set(self._SECTIONS))
        if unknown:
            raise ValueError(f"지원하지 않는 summary 영역입니다: {', '.join(unknown)}")

        document = self._load_or_create(run_id)
        for section, section_document in sections.items():
            if not isinstance(section_document, dict):
                raise ValueError(f"summary.{section} 갱신 값은 객체여야 합니다.")
            document[section] = dict(section_document)

        document["output_files"].update(output_files)
        document["updated_at"] = self._utc_now_text()
        document["status"] = self._overall_status(document)
        relative_path = Path(run_id) / "summary.json"
        return self.writer.write_text(
            relative_path,
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        )

    def _load_or_create(self, run_id: str) -> dict[str, Any]:
        """summary.json이 없으면 새 문서를 만들고, 1.0이면 2.0 구조로 변환합니다."""

        path = self.analysis_root / run_id / "summary.json"
        if not path.exists():
            now = self._utc_now_text()
            document: dict[str, Any] = {
                "schema_version": self.SCHEMA_VERSION,
                "run_id": run_id,
                "created_at": now,
                "updated_at": now,
                "status": "incomplete",
                "output_files": {
                    "summary": self._relative_to_data_root(path),
                },
            }
            for section in self._SECTIONS:
                document[section] = {"status": "not_run"}
            return document

        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RunSummaryError(
                f"기존 summary.json을 읽을 수 없습니다: {path}: {exc}"
            ) from exc
        if not isinstance(loaded, dict):
            raise RunSummaryError(
                f"summary.json 최상위 값은 객체여야 합니다: {path}"
            )
        stored_run_id = loaded.get("run_id")
        if stored_run_id != run_id:
            raise RunSummaryError(
                f"summary.json run_id가 경로와 다릅니다: "
                f"expected={run_id!r}, actual={stored_run_id!r}"
            )
        version = str(loaded.get("schema_version") or "1.0")
        if version == self.SCHEMA_VERSION:
            return self._validate_v2(loaded, path)
        if version == "1.0":
            return self._migrate_v1(loaded, path)
        raise RunSummaryError(
            f"지원하지 않는 summary schema_version입니다: {version}"
        )

    def _validate_v2(
        self,
        loaded: dict[str, Any],
        path: Path,
    ) -> dict[str, Any]:
        """2.0 문서의 필수 객체를 검증하고 새 분석 영역의 not_run 기본값을 보완합니다."""

        document = dict(loaded)
        for section in self._SECTIONS:
            value = document.get(section, {"status": "not_run"})
            if not isinstance(value, dict):
                raise RunSummaryError(
                    f"summary.{section} 값은 객체여야 합니다: {path}"
                )
            document[section] = value
        output_files = document.get("output_files", {})
        if not isinstance(output_files, dict):
            raise RunSummaryError(
                f"summary.output_files 값은 객체여야 합니다: {path}"
            )
        document["output_files"] = output_files
        document.setdefault(
            "created_at",
            document.get("updated_at") or self._utc_now_text(),
        )
        return document

    def _migrate_v1(
        self,
        loaded: dict[str, Any],
        path: Path,
    ) -> dict[str, Any]:
        """기존 이슈 전용 1.0 요약을 여러 분석 영역을 지원하는 2.0 문서로 변환합니다."""

        output_files = loaded.get("output_files", {})
        if not isinstance(output_files, dict):
            raise RunSummaryError(
                f"1.0 summary.output_files 값은 객체여야 합니다: {path}"
            )
        generated_at = str(loaded.get("generated_at") or self._utc_now_text())
        issue_status = str(loaded.get("status") or "not_run")
        document: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": loaded["run_id"],
            "created_at": generated_at,
            "updated_at": self._utc_now_text(),
            "status": "incomplete",
            "issues": {
                "status": issue_status,
                "discovered_count": int(loaded.get("discovered_issue_count", 0)),
                "exported_count": int(loaded.get("exported_issue_count", 0)),
                "failed_count": int(loaded.get("failed_issue_count", 0)),
                "warning_count": int(loaded.get("warning_count", 0)),
                "parse_error_count": int(loaded.get("parse_error_count", 0)),
                "description_formats": loaded.get("description_formats", {}),
            },
            "comments": {"status": "not_run"},
            "attachments": {"status": "not_run"},
            "relationships": {"status": "not_run"},
            "custom_fields": {"status": "not_run"},
            "output_files": dict(output_files),
        }
        document["output_files"].setdefault(
            "summary",
            self._relative_to_data_root(path),
        )
        document["status"] = self._overall_status(document)
        return document

    @classmethod
    def _overall_status(cls, document: dict[str, Any]) -> str:
        """기본 이슈·댓글 완료 여부와 실행된 선택 영역의 실패 여부를 조합합니다."""

        statuses = {
            name: str(document.get(name, {}).get("status", "not_run"))
            for name in cls._SECTIONS
        }
        if "failed" in statuses.values():
            return "failed"
        if "partial" in statuses.values():
            return "partial"
        if not all(statuses[name] == "completed" for name in cls._BASE_REQUIRED_SECTIONS):
            return "incomplete"
        # Attachment/Relationship/Custom Field는 아직 실행하지 않았어도 기존 2.0 의미를 깨지 않도록
        # not_run을 허용합니다. 실행된 선택 영역이 모두 completed면 전체 상태도 completed입니다.
        optional_statuses = [
            status
            for name, status in statuses.items()
            if name not in cls._BASE_REQUIRED_SECTIONS and status != "not_run"
        ]
        if all(status == "completed" for status in optional_statuses):
            return "completed"
        return "incomplete"

    def _relative_to_data_root(self, path: Path) -> str:
        """절대 경로를 data_root 기준의 POSIX 상대 경로로 변환합니다."""

        return path.resolve().relative_to(self.data_root).as_posix()

    @staticmethod
    def _utc_now_text() -> str:
        """현재 UTC 시각을 ISO 8601 문자열로 반환합니다."""

        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
