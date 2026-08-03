from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .jira_client import JiraClient
from .raw_store import RawStore, safe_component
from .state_store import StateStore


@dataclass(frozen=True)
class ProjectInfo:
    key: str
    name: str
    raw: dict[str, Any]


def _project_items(payload: Any) -> tuple[list[dict[str, Any]], bool, int]:
    if isinstance(payload, list):
        items = [item for item in payload if isinstance(item, dict)]
        return items, True, len(items)

    if not isinstance(payload, dict):
        raise ValueError("프로젝트 목록 응답이 배열 또는 객체가 아닙니다.")

    raw_items = payload.get("values")
    if raw_items is None:
        raw_items = payload.get("projects")
    if raw_items is None:
        raise ValueError("프로젝트 목록 응답에서 values/projects 배열을 찾을 수 없습니다.")

    items = [item for item in raw_items if isinstance(item, dict)]
    start_at = int(payload.get("startAt", 0))
    total = int(payload.get("total", start_at + len(items)))
    is_last = bool(payload.get("isLast", start_at + len(items) >= total))
    return items, is_last, total


class ProjectDiscovery:
    def __init__(self, client: JiraClient, raw_store: RawStore, state: StateStore) -> None:
        self.client = client
        self.raw_store = raw_store
        self.state = state

    def discover(self, run_id: str) -> list[ProjectInfo]:
        settings = self.client.settings
        start_at = 0
        page_number = 1
        found: dict[str, ProjectInfo] = {}

        while True:
            result = self.client.get_json(
                settings.project_list_path,
                params={
                    "startAt": start_at,
                    "maxResults": settings.pagination.project_page_size,
                },
            )
            artifact = self.raw_store.save_json(
                f"runs/{safe_component(run_id)}/project_discovery/page_{page_number:04d}.json",
                result.payload,
            )
            self.state.record_artifact(
                run_id=run_id,
                project_key=None,
                issue_key=None,
                artifact_type="project_discovery_page",
                relative_path=artifact.relative_path,
                content_hash=artifact.content_sha256,
                size_bytes=artifact.size_bytes,
            )

            items, is_last, total = _project_items(result.payload)
            for item in items:
                key = str(item.get("key") or "").strip()
                if not key:
                    continue
                name = str(item.get("name") or key)
                found[key] = ProjectInfo(key=key, name=name, raw=item)

            if is_last:
                break
            if not items:
                break

            start_at += len(items)
            if start_at >= total:
                break
            page_number += 1

        return sorted(found.values(), key=lambda item: item.key)
