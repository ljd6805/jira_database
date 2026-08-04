from __future__ import annotations

import logging
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TextIO


_WINDOWS_TRANSIENT_FILE_ERRORS = {5, 32, 33}
LOGGER = logging.getLogger(__name__)

ReplaceFunction = Callable[[str | os.PathLike[str], str | os.PathLike[str]], None]
SleepFunction = Callable[[float], None]


class AtomicTextWriter:
    """UTF-8 텍스트 파일을 같은 디렉터리의 임시 파일을 거쳐 원자적으로 저장합니다."""

    def __init__(
        self,
        root: str | Path,
        *,
        replace_attempts: int = 6,
        replace_initial_delay_seconds: float = 0.2,
        replace_max_delay_seconds: float = 2.0,
        sleeper: SleepFunction = time.sleep,
        replacer: ReplaceFunction = os.replace,
    ) -> None:
        """저장 루트와 Windows 파일 잠금 재시도 정책을 초기화합니다."""

        if replace_attempts <= 0:
            raise ValueError("replace_attempts는 1 이상이어야 합니다.")
        if replace_initial_delay_seconds < 0:
            raise ValueError("replace_initial_delay_seconds는 0 이상이어야 합니다.")
        if replace_max_delay_seconds < replace_initial_delay_seconds:
            raise ValueError(
                "replace_max_delay_seconds는 replace_initial_delay_seconds 이상이어야 합니다."
            )

        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.replace_attempts = replace_attempts
        self.replace_initial_delay_seconds = replace_initial_delay_seconds
        self.replace_max_delay_seconds = replace_max_delay_seconds
        self._sleeper = sleeper
        self._replacer = replacer

    @contextmanager
    def open_text(self, relative_path: str | Path) -> Iterator[TextIO]:
        """임시 UTF-8 파일을 열고 정상 종료 시 대상 파일로 교체합니다."""

        target = (self.root / relative_path).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"저장 루트 밖의 경로는 쓸 수 없습니다: {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                yield handle
                # 프로세스 종료 직전에도 디스크에 내용이 남도록 flush와 fsync를 수행합니다.
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_with_retry(temp_name, target)
        except Exception:
            self._cleanup_temp_file(temp_name)
            raise

    def write_text(self, relative_path: str | Path, content: str) -> Path:
        """문자열 전체를 UTF-8 텍스트 파일로 원자 저장하고 대상 경로를 반환합니다."""

        with self.open_text(relative_path) as handle:
            handle.write(content)
        return (self.root / relative_path).resolve()

    def _replace_with_retry(self, temp_name: str, target: Path) -> None:
        """Windows의 일시적 파일 잠금 오류가 발생하면 지수적으로 재시도합니다."""

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
                    "Windows 파일 잠금으로 분석 결과 교체를 재시도합니다. "
                    "attempt=%s/%s delay=%.2fs target=%s",
                    attempt,
                    self.replace_attempts,
                    delay,
                    target,
                )
                self._sleeper(delay)

    @staticmethod
    def _is_transient_windows_file_lock(exc: OSError) -> bool:
        """Windows에서 재시도 가능한 파일 잠금 오류인지 판별합니다."""

        return getattr(exc, "winerror", None) in _WINDOWS_TRANSIENT_FILE_ERRORS

    @staticmethod
    def _cleanup_temp_file(temp_name: str) -> None:
        """실패 후 남은 임시 파일을 제거하되 최초 오류는 덮어쓰지 않습니다."""

        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            return
        except OSError as cleanup_error:
            LOGGER.warning(
                "실패한 분석 임시 파일을 삭제하지 못했습니다: %s: %s",
                temp_name,
                cleanup_error,
            )
