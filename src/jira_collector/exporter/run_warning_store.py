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
        """다른 component 경고는 보존하고 현재 component 경고만 새 결과로 교체합니다."""

        relative_path = Path(run_id) / "parse_warnings.jsonl"
        path = self.analysis_root / relative_path
        existing = self._read_documents(path)
        preserved = [
            item
            for item in existing
            if item.get("component", "issues") != component
        ]
        normalized: list[dict[str, Any]] = []
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
                            f"경고 JSONL의 {line_number}번째 줄이 객체가 아닙니다: "
                            f"{path}"
                        )
                    documents.append(value)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RunWarningStoreError(
                f"기존 경고 JSONL을 읽을 수 없습니다: {path}: {exc}"
            ) from exc
        return documents
