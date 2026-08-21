"""Forbid writing onto ``${ANSIBLE_LOG_PATH}`` from the deploy scripts.

The deploy workflows tee the whole deploy stdout into the very file that
``ANSIBLE_LOG_PATH`` names, and the downstream steps parse that tee'd
stream: only stdout carries the host-side ``matrix-deploy: round N/M ...``
markers, which Ansible's own log can never contain. A ``docker cp`` of the
container-side log onto the same path therefore replaces the file the
summary needs with one that cannot produce per-variant tables. The copy
also fails silently wherever ``/tmp`` is a tmpfs inside the container, so
the damage only appears on some distros and reads as a flake.

Per-line opt-out: ``# nocheck: ansible-log-clobber``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "ansible-log-clobber"

_LOG_VAR = r"\"?\$\{ANSIBLE_LOG_PATH\}\"?"
_WRITERS = (
    re.compile(rf"\bcp\b.*\s{_LOG_VAR}(?:\s|$)"),
    re.compile(rf">>?\s*{_LOG_VAR}"),
    re.compile(rf"\btee\b.*\s{_LOG_VAR}(?:\s|$)"),
)


class TestNoAnsibleLogClobber(unittest.TestCase):
    def test_nothing_writes_onto_the_ansible_log_path(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(
            extensions=(".yml", ".yaml", ".sh"),
            exclude_tests=True,
            exclude_dirs=("docs",),
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(path_str).splitlines()
            for lineno, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                if not any(writer.search(line) for writer in _WRITERS):
                    continue
                if is_suppressed_at(lines, lineno, _RULE):
                    continue
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

        if offenders:
            self.fail(
                f"{len(offenders)} write(s) onto ${{ANSIBLE_LOG_PATH}}. That "
                "file is the deploy stdout the role-runtime summary parses; "
                "overwriting it drops the matrix-deploy round markers and "
                "yields an empty summary. Write to a distinct path:\n  "
                + "\n  ".join(offenders)
            )
