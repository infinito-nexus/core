"""Lint: curl invocations in role tasks/templates/files MUST go through
the ``curl`` filter (plugins/filter/curl.py), which pins
``--connect-timeout`` and ``--max-time``. A bare curl against an
accepted-but-silent peer hangs forever; task retries never fire and the
CI job dies at the 6h runner cut.

Exempt:

* lines already rendering ``| curl``
* lines carrying ``--max-time`` themselves (plain .sh files and Dockerfiles
  cannot render the filter; they pin the flags inline or via a variable)
* Docker healthcheck blocks (the healthcheck ``timeout:`` field caps them)
* package-name mentions (``name: curl``) - only command invocations match
* lines suppressed via ``# nocheck: curl-timeout`` (same line or above)
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text

from . import PROJECT_ROOT

_RULE = "curl-timeout"

_CURL_INVOCATION_RE = re.compile(r"(?<![\w-])curl\s+(?:-|http)")
_FILTER_RE = re.compile(r"\|\s*curl\b")

_GLOBS = (
    "roles/*/tasks/**/*.yml",
    "roles/*/templates/**/*.j2",
    "roles/*/files/**/*.sh",
    "roles/*/files/**/Dockerfile",
)


def _healthcheck_exempt_lines(lines: list[str]) -> set[int]:
    """1-based line numbers inside a ``healthcheck:`` block or on a ``test:`` line."""
    exempt: set[int] = set()
    block_indent: int | None = None
    for no, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip())
        if block_indent is not None:
            if stripped and indent <= block_indent and not stripped.startswith("#"):
                block_indent = None
            else:
                exempt.add(no)
                continue
        if stripped.startswith("healthcheck:"):
            block_indent = indent
            exempt.add(no)
        elif stripped.startswith("test:"):
            exempt.add(no)
    return exempt


class TestCurlViaFilter(unittest.TestCase):
    def test_curl_invocations_use_the_curl_filter(self) -> None:
        offenders: list[str] = []
        for glob in _GLOBS:
            for path in sorted(PROJECT_ROOT.glob(glob)):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                lines = read_text(str(path)).splitlines()
                exempt = _healthcheck_exempt_lines(lines)
                for no, line in enumerate(lines, start=1):
                    if not _CURL_INVOCATION_RE.search(line):
                        continue
                    if _FILTER_RE.search(line) or "--max-time" in line:
                        continue
                    if no in exempt:
                        continue
                    if is_suppressed_at(lines, no, _RULE):
                        continue
                    offenders.append(f"{rel}:{no}: {line.strip()[:100]}")

        if offenders:
            self.fail(
                f"{len(offenders)} bare curl invocation(s). Use "
                '"{{ <max_time_seconds> | curl }} <extra flags> <url>" so every '
                "call carries --connect-timeout/--max-time (connect_timeout= "
                "kwarg available), or mark a legitimate exception with "
                f"`# nocheck: {_RULE}`:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
