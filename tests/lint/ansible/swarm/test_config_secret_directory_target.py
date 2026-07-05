"""Forbid ``type: config`` / ``type: secret`` mounts onto a directory target.

Rationale
=========
A Docker Swarm ``config`` (and ``secret``) object is a SINGLE FILE in the
raft store: ``docker config create`` reads exactly one file, and the object
mounts to a single file path inside the container. Pointing such a mount at a
directory-style target (one ending in ``/``, e.g.
``/var/www/html/config/infinito/``) is only viable in ``docker compose``,
which emulates ``configs:`` as host bind-mounts and happily binds a directory.
``docker stack deploy`` creates a real config object and aborts the whole
stack with ``read <source>: is a directory``.

A directory payload belongs in a ``type: bind`` (host directory) or
``type: volume`` mount, not a config/secret object.

Per-line opt-out
================
Add ``# nocheck: config-secret-directory-target`` on the ``target:`` line or
the line immediately above it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

_RULE = "config-secret-directory-target"

_TOP_LEVEL_KEY = re.compile(r"^(?P<key>\S[^:]*):\s*(?:#.*)?$")
_TYPE_LINE = re.compile(r"^\s+type:\s*['\"]?(?P<type>[A-Za-z0-9_-]+)")
_TARGET_LINE = re.compile(r"^\s+-?\s*target:\s*['\"]?(?P<target>[^'\"#\s]+)")

_SINGLE_FILE_TYPES = frozenset({"config", "secret"})


def _is_volumes_meta(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and rel_path.endswith(
        "/" + ROLE_FILE_META_VOLUMES
    )


def _scan(
    rel_path: str, lines: list[str], findings: list[tuple[str, int, str]]
) -> None:
    current_type: str | None = None
    for idx, line in enumerate(lines):
        if _TOP_LEVEL_KEY.match(line):
            current_type = None
            continue
        type_match = _TYPE_LINE.match(line)
        if type_match:
            current_type = type_match.group("type")
            continue
        target_match = _TARGET_LINE.match(line)
        if not target_match or current_type not in _SINGLE_FILE_TYPES:
            continue
        if not target_match.group("target").endswith("/"):
            continue
        line_no = idx + 1
        if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
            continue
        findings.append((rel_path, line_no, line.strip()))


class TestConfigSecretDirectoryTarget(unittest.TestCase):
    def test_config_secret_targets_are_files_not_directories(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_volumes_meta(rel):
                continue
            _scan(rel, content.splitlines(), findings)

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(set(findings))
            )
            self.fail(
                "Found `type: config`/`type: secret` mounts whose target is a "
                "directory (ends with '/'). Swarm config/secret objects are "
                "single files; `docker stack deploy` aborts with '<source>: is "
                "a directory' (compose only tolerates it by emulating configs "
                "as bind-mounts).\n\n"
                "Fix: use `type: bind` (host directory) or `type: volume` for a "
                "directory payload; keep config/secret for single files with a "
                "file target.\n"
                "Or add `# nocheck: config-secret-directory-target` on the "
                "target line or the line above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
