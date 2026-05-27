from __future__ import annotations

import contextlib
import os
import pty
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TextIO

from cli.core.colors import Fore, color_text

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class RunConfig:
    log_enabled: bool


def open_log_file(log_dir: Path) -> tuple[TextIO, Path]:
    """
    Create/open a timestamped log file inside log_dir.

    - log_dir is mandatory (provided via --log <LOG_DIR>)
    - log_dir is created with parents=True if missing
    """
    log_dir = log_dir.expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    # Best-effort permission hardening (ignore failures on non-POSIX / special FS).
    with contextlib.suppress(Exception):
        log_dir.chmod(0o700)

    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%S")
    log_file_path = log_dir / f"{timestamp}.log"
    fd = os.open(str(log_file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    return os.fdopen(fd, "a", encoding="utf-8"), log_file_path


def run_command_once(
    full_cmd: list[str], cfg: RunConfig, log_file: TextIO | None
) -> bool:
    try:
        if cfg.log_enabled and log_file is not None:
            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(
                full_cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                text=True,
            )
            os.close(slave_fd)

            import errno

            with os.fdopen(master_fd) as master:
                try:
                    for line in master:
                        ts = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
                        log_file.write(f"{ts} {line}")
                        log_file.flush()
                        print(line, end="")
                except OSError as e:
                    if e.errno != errno.EIO:
                        raise

            proc.wait()
            rc = proc.returncode
        else:
            proc = subprocess.Popen(full_cmd)
            proc.wait()
            rc = proc.returncode

    except Exception as e:
        print(color_text(f"Exception running command: {e}", Fore.RED))
        raise SystemExit(1) from e

    if rc != 0:
        raise SystemExit(rc)
    return True
