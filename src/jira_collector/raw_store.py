from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StoredArtifact:
    relative_path: str
    content_sha256: str
    size_bytes: int


def safe_component(value: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("_", value.strip())
    cleaned = cleaned.strip("._")
    if not cleaned:
        raise ValueError("path component is empty after sanitization")
    return cleaned


class RawStore:
    def __init__(self, data_root: Path, raw_directory: str = "raw") -> None:
        self.data_root = data_root.resolve()
        self.raw_root = (self.data_root / raw_directory).resolve()
        self.raw_root.mkdir(parents=True, exist_ok=True)

    def save_json(self, relative_path: str | Path, payload: Any) -> StoredArtifact:
        target = (self.raw_root / relative_path).resolve()
        if self.raw_root not in target.parents:
            raise ValueError(f"raw root 밖의 경로는 저장할 수 없습니다: {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()

        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

        relative_to_data = target.relative_to(self.data_root).as_posix()
        return StoredArtifact(
            relative_path=relative_to_data,
            content_sha256=digest,
            size_bytes=len(encoded),
        )

    def verify(self, relative_path: str, expected_sha256: str) -> bool:
        target = (self.data_root / relative_path).resolve()
        if self.data_root not in target.parents:
            return False
        if not target.is_file():
            return False
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return digest == expected_sha256
