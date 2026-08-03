from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .state_store import StateStore


class ReportWriter:
    def __init__(self, report_root: Path) -> None:
        self.report_root = report_root
        self.report_root.mkdir(parents=True, exist_ok=True)

    def write(self, state: StateStore, run_id: str) -> Path:
        summary = state.get_run_summary(run_id)
        projects = [project.__dict__ for project in state.list_all_projects(run_id)]
        artifacts = state.list_artifacts(run_id)
        by_type: dict[str, int] = {}
        for artifact in artifacts:
            by_type[artifact.artifact_type] = by_type.get(artifact.artifact_type, 0) + 1

        payload = {
            "run": summary,
            "projects": projects,
            "artifacts": {
                "total": len(artifacts),
                "by_type": by_type,
            },
        }
        target = self.report_root / f"{run_id}.json"
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=f".{run_id}.", suffix=".tmp", dir=self.report_root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return target
