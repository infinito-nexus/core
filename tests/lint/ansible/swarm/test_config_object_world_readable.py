"""Enforce that Swarm ``type: config`` objects are world-readable (o+r).

Rationale
=========
A Swarm ``config`` object is mounted into its service ``root:root``. A
``mode`` without the other-read bit (e.g. ``0440``) is unreadable by a
container whose application process runs as a non-root uid, so the
service crashloops (jenkins JCasC ``AccessDeniedException`` on
``/var/jenkins_home/casc.yaml``, exit 5). ``docker compose`` never hits
this: there the same file is a host bind-mount inheriting host perms.

Configs are single-container, non-secret payloads that the container's
app user must read, so the sane mode is ``0444``. Widening ``0440`` to
``0444`` only adds read access and cannot break a reader.

``type: secret`` is intentionally OUT of scope -- secrets warrant tight
perms and are read as root.

Per-line opt-out
================
Add ``# nocheck: config-world-readable`` on the ``mode:`` line or the
line immediately above it (e.g. a config whose container legitimately
runs as root and must keep a tighter mode).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

_RULE = "config-world-readable"

_TOP_LEVEL_KEY = re.compile(r"^(?P<key>\S[^:]*):\s*(?:#.*)?$")
_TYPE_LINE = re.compile(r"^\s+type:\s*['\"]?(?P<type>[A-Za-z0-9_-]+)")
_MODE_LINE = re.compile(r"^\s+mode:\s*['\"]?(?P<mode>[0-7]{3,4})")


def _is_volumes_meta(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and rel_path.endswith(
        "/" + ROLE_FILE_META_VOLUMES
    )


def _other_read_missing(mode: str) -> bool:
    """True when the octal *mode* lacks the other-read bit (o+r)."""
    return (int(mode[-1], 8) & 0o4) == 0


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
        mode_match = _MODE_LINE.match(line)
        if not mode_match or current_type != "config":
            continue
        if not _other_read_missing(mode_match.group("mode")):
            continue
        line_no = idx + 1
        if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
            continue
        findings.append((rel_path, line_no, line.strip()))


class TestConfigObjectWorldReadable(unittest.TestCase):
    def test_config_objects_are_world_readable(self) -> None:
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
                "Found `type: config` Swarm objects whose `mode` lacks the "
                "other-read bit (o+r). Swarm mounts configs root:root, so a "
                "0440 mode is unreadable by a non-root container app user and "
                "crashloops the service in swarm (works in compose only "
                "because there it is a host bind-mount).\n\n"
                "Fix: widen the mode to 0444 (adds read only, cannot break a "
                "reader).\n"
                "Or, if the container legitimately runs as root and must keep "
                "a tighter mode, add `# nocheck: config-world-readable` on the "
                "mode line or the line above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
