"""Lint: curl/wget that DOWNLOAD to a real file in a verbatim shell script
MUST carry native retries, because ``files/*.sh`` are copied unrendered and
cannot reach the retry-hardened ``curl`` filter (plugins/filter/curl.py). A
transport-layer reset (curl exit 35) on flaky CI egress then hard-fails the
deploy with no retry.

Scope is deliberately narrow to avoid flagging the many status probes and
local-API calls that legitimately fast-fail:

* curl offender: ``-o <file>`` / ``-O`` / ``--remote-name`` writing to a real
  path (not ``/dev/null`` or ``-``) without ``--retry-all-errors``.
* wget offender: ``-O <file>`` writing to a real path (not ``-``), or a plain
  ``wget <url>`` download, without ``--tries=``.

Exempt: ``-o /dev/null`` / ``-O-`` stdout probes, ``command -v`` checks, and
lines suppressed via ``# nocheck: shell-download-retry``.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text

from . import PROJECT_ROOT

_RULE = "shell-download-retry"

_CURL_RE = re.compile(r"(?<![\w-])curl\s+(?:-|http)")
_CURL_OUT_RE = re.compile(
    r"(?:-o|--output)\s+(?!/dev/null\b|-\s)(\S+)|(?:-O\b|--remote-name\b)"
)
_WGET_RE = re.compile(r"(?<![\w-])wget\s+(?:-|http)")
_WGET_STDOUT_RE = re.compile(r"-O\s*-|-\w*O-")

_GLOBS = ("roles/*/files/**/*.sh", "scripts/**/*.sh")


class TestShellDownloadRetry(unittest.TestCase):
    def test_shell_downloads_carry_native_retries(self) -> None:
        offenders: list[str] = []
        for glob in _GLOBS:
            for path in sorted(PROJECT_ROOT.glob(glob)):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                lines = read_text(str(path)).splitlines()
                for no, line in enumerate(lines, start=1):
                    bad = None
                    is_curl_dl = _CURL_RE.search(line) and _CURL_OUT_RE.search(line)
                    is_wget_dl = _WGET_RE.search(line) and not _WGET_STDOUT_RE.search(
                        line
                    )
                    if is_curl_dl and "--retry-all-errors" not in line:
                        bad = "curl download without --retry-all-errors"
                    elif is_wget_dl and "--tries=" not in line and "-t " not in line:
                        bad = "wget download without --tries="
                    if not bad:
                        continue
                    if is_suppressed_at(lines, no, _RULE):
                        continue
                    offenders.append(f"{rel}:{no}: {line.strip()[:100]}")

        if offenders:
            self.fail(
                f"{len(offenders)} shell download(s) without native retries. Add "
                "`--retry-all-errors --retry-delay 2` to curl or `--tries=3 "
                "--waitretry=2` to wget (files/*.sh cannot use the curl filter), "
                f"or mark a legitimate exception with `# nocheck: {_RULE}`:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
