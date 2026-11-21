"""Every container logs to journald unless a reasoned marker says otherwise.

Scanned shapes, in role templates, vars, defaults and files:

* a compose ``logging:`` block whose ``driver:`` is not ``journald``, in block
  or in flow style;
* a daemon setting ``log-driver: <value>`` / ``"log-driver": "<value>"``,
  which also covers nested daemons such as the Matrix runner's;
* a CLI flag ``--log-driver=<value>`` / ``--log-driver <value>``.

A value rendered by Jinja counts as a finding as well.

Suppression: ``# nocheck: logging-driver`` (or the ``{# #}`` form) on the
offending line, on the ``logging:`` line, or in the contiguous comment block
directly above either, followed by the reason the container may not log to
journald. A bare marker grants nothing.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import line_has_rule
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

RULE = "logging-driver"
ALLOWED_DRIVER = "journald"
SCAN_EXTENSIONS = (".j2", ".yml", ".yaml", ".json", ".sh", ".py")
SCAN_DIRS = ("/templates/", "/vars/", "/defaults/", "/files/")

_LOGGING_BLOCK = re.compile(r"^(?P<indent>\s*)-?\s*logging:\s*(?:#.*)?$")
_LOGGING_FLOW = re.compile(r"^\s*-?\s*logging:\s*\{(?P<body>[^}]*)\}")
_DRIVER_KEY = re.compile(r"^\s*driver:\s*(?P<value>.*?)\s*(?:#.*)?$")
_FLOW_DRIVER = re.compile(r"\bdriver\s*:\s*(?P<value>[^,}]+)")
_DAEMON_KEY = re.compile(
    r"""(?<![\w-])["']?log-driver["']?\s*:\s*(?P<value>"[^"]*"|'[^']*'|[^\s,}#]+)"""
)
_CLI_FLAG = re.compile(r"--log-driver(?:=|\s+)(?P<value>\"[^\"]*\"|'[^']*'|[^\s]+)")
_MARKER_TAIL = re.compile(
    r"(?:noqa|nocheck)\s*:\s*[a-z0-9][a-z0-9\-]*(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*(?P<tail>.*)$",
    re.IGNORECASE,
)


def _is_scan_target(rel_path: str) -> bool:
    """Whether *rel_path* is a role file that can set a log driver.

    Args:
        rel_path: repository-relative path.
    """
    return (
        rel_path.startswith("roles/")
        and any(part in rel_path for part in SCAN_DIRS)
        and rel_path.endswith(SCAN_EXTENSIONS)
    )


def _normalise(value: str) -> str:
    return value.strip().strip("\"'").strip()


def _is_comment(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith(("#", "{#"))


def _marker_has_reason(line: str) -> bool:
    if not line_has_rule(line, RULE):
        return False
    match = _MARKER_TAIL.search(line)
    if match is None:
        return False
    tail = match.group("tail").replace("#}", "").strip(" -:—\t")
    return len(tail) > 0


def _suppressed(lines: list[str], numbers: tuple[int, ...]) -> bool:
    """Whether a reasoned marker covers any of the 1-based *numbers*.

    Args:
        lines: the file's lines.
        numbers: the construct's own line and, for a block, its ``logging:`` line.
    """
    for number in numbers:
        index = number - 1
        if _marker_has_reason(lines[index]):
            return True
        above = index - 1
        while above >= 0 and _is_comment(lines[above]):
            if _marker_has_reason(lines[above]):
                return True
            above -= 1
    return False


def findings_in(text: str) -> list[tuple[int, str]]:
    """``(line, driver)`` for every non-journald driver *text* sets.

    Args:
        text: the content of one scanned file.
    """
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    block_indent: int | None = None
    block_line = 0
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or _is_comment(line) or stripped.startswith("{%"):
            continue
        indent = len(line) - len(line.lstrip())
        if block_indent is not None and indent <= block_indent:
            block_indent = None
        if block_indent is not None:
            driver = _DRIVER_KEY.match(line)
            if driver and indent > block_indent:
                value = _normalise(driver.group("value"))
                if value != ALLOWED_DRIVER and not _suppressed(
                    lines, (number, block_line)
                ):
                    found.append((number, value))
            continue
        opener = _LOGGING_BLOCK.match(line)
        if opener:
            block_indent = len(opener.group("indent"))
            block_line = number
            continue
        flow = _LOGGING_FLOW.match(line)
        if flow:
            flow_driver = _FLOW_DRIVER.search(flow.group("body"))
            if flow_driver:
                value = _normalise(flow_driver.group("value"))
                if value != ALLOWED_DRIVER and not _suppressed(lines, (number,)):
                    found.append((number, value))
            continue
        for pattern in (_DAEMON_KEY, _CLI_FLAG):
            for match in pattern.finditer(line):
                value = _normalise(match.group("value"))
                if value != ALLOWED_DRIVER and not _suppressed(lines, (number,)):
                    found.append((number, value))
    return found


class TestComposeLoggingDriver(unittest.TestCase):
    def test_every_container_logs_to_journald(self) -> None:
        offenders: list[str] = []
        for path_str, content in iter_project_files_with_content(
            extensions=SCAN_EXTENSIONS,
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            offenders.extend(
                f"- {rel}:{number}: log driver {value!r}"
                for number, value in findings_in(content)
            )

        if offenders:
            self.fail(
                "A container leaves the journald logging contract. Log to "
                "journald (include roles/sys-svc-container/templates/logging.yml.j2, "
                "or base.yml.j2, which renders it), or mark the line with "
                f"`# nocheck: {RULE}` followed by the reason it cannot:\n\n"
                + "\n".join(sorted(offenders))
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
