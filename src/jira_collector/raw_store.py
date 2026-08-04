from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
_WINDOWS_TRANSIENT_FILE_ERRORS = {5, 32, 33}
LOGGER = logging.getLogger(__name__)

ReplaceFunction = Callable[[str | os.PathLike[str], str | os.PathLike[str]], None]
SleepFunction = Callable[[float], None]


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
    def __init__(
        self,
        data_root: Path,
        raw_directory: str = "raw",
        *,
        replace_attempts: int = 6,
        replace_initial_delay_seconds: float = 0.2,
        replace_max_delay_seconds: float = 2.0,
        sleeper: SleepFunction = time.sleep,
        replacer: ReplaceFunction = os.replace,
    ) -> None:
        if replace_attempts <= 0:
            raise ValueError("replace_attempts는 1 이상이어야 합니다.")
        if replace_initial_delay_seconds < 0:
            raise ValueError("replace_initial_delay_seconds는 0 이상이어야 합니다.")
        if replace_max_delay_seconds < replace_initial_delay_seconds:
            raise ValueError(
                "replace_max_delay_seconds는 replace_initial_delay_seconds 이상이어야 합니다."
            )

        self.data_root = data_root.resolve()
        self.raw_root = (self.data_root / raw_directory).resolve()
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.replace_attempts = replace_attempts
        self.replace_initial_delay_seconds = replace_initial_delay_seconds
        self.replace_max_delay_seconds = replace_max_delay_seconds
        self._sleeper = sleeper
        self._replacer = replacer

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
            self._replace_with_retry(temp_name, target)
        except Exception:
            self._cleanup_temp_file(temp_name)
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

    def _replace_with_retry(self, temp_name: str, target: Path) -> None:
        for attempt in range(1, self.replace_attempts + 1):
            try:
                self._replacer(temp_name, target)
                return
            except OSError as exc:
                if not self._is_transient_windows_file_lock(exc):
                    raise
                if attempt >= self.replace_attempts:
                    raise

                delay = min(
                    self.replace_initial_delay_seconds * (2 ** (attempt - 1)),
                    self.replace_max_delay_seconds,
                )
                LOGGER.warning(
                    "Windows 파일 잠금으로 JSON 교체를 재시도합니다. "
                    "attempt=%s/%s delay=%.2fs target=%s",
                    attempt,
                    self.replace_attempts,
                    delay,
                    target,
                )
                self._sleeper(delay)

    @staticmethod
    def _is_transient_windows_file_lock(exc: OSError) -> bool:
        return getattr(exc, "winerror", None) in _WINDOWS_TRANSIENT_FILE_ERRORS

    @staticmethod
    def _cleanup_temp_file(temp_name: str) -> None:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            return
        except OSError as cleanup_error:
            # 정리 실패가 최초 저장 오류를 덮어쓰지 않도록 경고만 남깁니다.
            LOGGER.warning(
                "실패한 JSON 임시 파일을 삭제하지 못했습니다: %s: %s",
                temp_name,
                cleanup_error,
            )
