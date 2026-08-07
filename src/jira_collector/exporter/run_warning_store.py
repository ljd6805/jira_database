from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic_writer import AtomicTextWriter


class RunWarningStoreError(ValueError):
    """기존 parse_warnings.jsonl을 안전하게 병합할 수 없을 때 발생합니다."""


class RunWarningStore:
    """Exporter별 경고를 하나의 parse_warnings.jsonl에 안전하게 병합합니다."""

    def __init__(
        self,
        data_root: str | Path,
        analysis_directory: str = "analysis",
    ) -> None:
        """분석 결과 루트와 원자 저장 도구를 초기화합니다."""

        self.data_root = Path(data_root).resolve()
        self.analysis_root = (self.data_root / analysis_directory).resolve()
        self.writer = AtomicTextWriter(self.analysis_root)

    def replace_component(
        self,
        run_id: str,
        component: str,
        documents: list[dict[str, Any]],
    ) -> Path:
        """단일 component 교체를 다중 component 원자 교체 메서드에 위임합니다."""

        return self.replace_components(run_id, {component: documents})

    def replace_components(
        self,
        run_id: str,
        documents_by_component: dict[str, list[dict[str, Any]]],
    ) -> Path:
        """지정한 여러 component의 기존 경고만 제거하고 새 경고 묶음을 한 번에 저장합니다."""

        relative_path = Path(run_id) / "parse_warnings.jsonl"
        path = self.analysis_root / relative_path
        existing = self._read_documents(path)
        replaced_components = set(documents_by_component)
        preserved = [
            item
            for item in existing
            if item.get("component", "issues") not in replaced_components
        ]

        normalized: list[dict[str, Any]] = []
        for component, documents in documents_by_component.items():
            for item in documents:
                document = dict(item)
                document["component"] = component
                normalized.append(document)

        with self.writer.open_text(relative_path) as handle:
            for document in [*preserved, *normalized]:
                handle.write(
                    json.dumps(
                        document,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
        return path.resolve()

    @staticmethod
    def _read_documents(path: Path) -> list[dict[str, Any]]:
        """기존 JSONL을 읽고 깨진 줄이 있으면 기존 파일을 보존한 채 오류를 발생시킵니다."""

        if not path.exists():
            return []
        documents: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise RunWarningStoreError(
                            f"경고 JSONL의 {line_number}번째 줄이 객체가 아닙니다: {path}"
                        )
                    documents.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RunWarningStoreError(
                f"기존 경고 JSONL을 읽을 수 없습니다: {path}: {exc}"
            ) from exc
        return documents
