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

A download the script retries itself counts as retry-hardened only in a
bounded retry loop: a literal counter header (``for n in 3 2 1 0; do`` or
``for ((...)); do``), the download directly in its body leaving the loop on
success (``&& exit 0``, ``&& break`` or ``&& return``), and a ``sleep``
directly in the body after it.

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
_COUNTER_LOOP_RE = re.compile(
    r"^\s*for\s+(?:\w+\s+in(?:\s+\d+)+|\(\(.*\)\))\s*;\s*do\s*$"
)
_BLOCK_OPEN_RE = re.compile(r"(?:^|;)\s*(?:if|case|for|while|until)\b")
_BLOCK_CLOSE_RE = re.compile(r"(?:^|;)\s*(?:fi|esac|done)\b")
_LOOP_END_RE = re.compile(r"^\s*done\b")
_LEAVES_ON_SUCCESS_RE = re.compile(r"&&\s*(?:exit\s+0|break|return(?:\s+0)?)\s*$")
_SLEEP_RE = re.compile(r"^\s*sleep\s+\S")

_GLOBS = ("roles/*/files/**/*.sh", "scripts/**/*.sh")


def _retried_lines(lines: list[str]) -> set[int]:
    """Return the lines a bounded retry loop repeats until they succeed.

    Args:
        lines: the script's lines.

    Returns:
        1-based numbers of every line that sits directly in the body of a
        literal counter loop, leaves the loop on success, and is followed
        by a ``sleep`` directly in the same body.
    """
    retried: set[int] = set()
    for header, line in enumerate(lines):
        if not _COUNTER_LOOP_RE.search(line):
            continue
        depth = 0
        leaving: list[int] = []
        for no in range(header + 1, len(lines)):
            body = lines[no]
            if depth == 0 and _LOOP_END_RE.search(body):
                break
            if depth == 0 and _LEAVES_ON_SUCCESS_RE.search(body):
                leaving.append(no + 1)
            elif depth == 0 and _SLEEP_RE.search(body):
                retried.update(leaving)
            depth += len(_BLOCK_OPEN_RE.findall(body))
            depth -= len(_BLOCK_CLOSE_RE.findall(body))
    return retried


def _offenders(rel: str, lines: list[str]) -> list[str]:
    """Return one finding per download line that carries no retry.

    Args:
        rel: the script's repository-relative path, used in each finding.
        lines: the script's lines.

    Returns:
        ``<rel>:<line>: <code>`` for every unretried download.
    """
    retried = _retried_lines(lines)
    found: list[str] = []
    for no, line in enumerate(lines, start=1):
        is_curl_dl = _CURL_RE.search(line) and _CURL_OUT_RE.search(line)
        is_wget_dl = _WGET_RE.search(line) and not _WGET_STDOUT_RE.search(line)
        bad = (is_curl_dl and "--retry-all-errors" not in line) or (
            is_wget_dl and "--tries=" not in line and "-t " not in line
        )
        if not bad or no in retried or is_suppressed_at(lines, no, _RULE):
            continue
        found.append(f"{rel}:{no}: {line.strip()[:100]}")
    return found


class TestShellDownloadRetry(unittest.TestCase):
    def test_shell_downloads_carry_native_retries(self) -> None:
        offenders: list[str] = []
        for glob in _GLOBS:
            for path in sorted(PROJECT_ROOT.glob(glob)):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                offenders += _offenders(rel, read_text(str(path)).splitlines())

        if offenders:
            self.fail(
                f"{len(offenders)} shell download(s) without native retries. Add "
                "`--retry-all-errors --retry-delay 2` to curl or `--tries=3 "
                "--waitretry=2` to wget (files/*.sh cannot use the curl filter), "
                "retry it in a bounded retry loop (see this lint's docstring), "
                f"or mark a legitimate exception with `# nocheck: {_RULE}`:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )

    def test_a_bounded_retry_loop_counts_as_retried(self) -> None:
        lines = [
            "for retries_left in 3 2 1 0; do",
            '\treply="$(curl -L -f -w "%{http_code}" -o "${out}" "${url}")" && exit 0',
            '\tif [[ "${reply}" == 404 ]]; then',
            "\t\texit 22",
            "\tfi",
            '\tsleep "${delay}"',
            "done",
        ]
        self.assertEqual(_offenders("x.sh", lines), [])

    def test_an_arithmetic_counter_loop_counts_as_retried(self) -> None:
        lines = [
            "for ((attempt = 1; attempt <= 4; attempt++)); do",
            '\tcurl -fsSL -o "${out}" "${url}" && break',
            "\tsleep 2",
            "done",
        ]
        self.assertEqual(_offenders("x.sh", lines), [])

    def test_a_rate_limited_url_loop_is_flagged(self) -> None:
        lines = [
            'for url in "${urls[@]}"; do',
            '\tcurl -fsSL -o "${dir}/${url##*/}" "${url}"',
            "\tsleep 1",
            "done",
        ]
        self.assertEqual(_offenders("x.sh", lines), [f"x.sh:2: {lines[1].strip()}"])

    def test_a_while_read_mirror_loop_is_flagged(self) -> None:
        lines = [
            "while read -r mirror; do",
            '\tcurl -fsSL -o "${out}" "${mirror}/core.db" && break',
            "\tsleep 1",
            'done < "${mirrorlist}"',
        ]
        self.assertEqual(_offenders("x.sh", lines), [f"x.sh:2: {lines[1].strip()}"])

    def test_an_hourly_service_loop_is_flagged(self) -> None:
        lines = [
            "while true; do",
            '\tcurl -fsSL -o "${out}" "${url}"',
            "\tsleep 3600",
            "done",
        ]
        self.assertEqual(_offenders("x.sh", lines), [f"x.sh:2: {lines[1].strip()}"])

    def test_a_sleep_only_in_a_skip_branch_is_flagged(self) -> None:
        lines = [
            "for attempt in 1 2 3; do",
            '\tif [[ -e "${skip}" ]]; then',
            "\t\tsleep 1",
            "\t\tcontinue",
            "\tfi",
            '\tcurl -fsSL -o "${out}" "${url}" && break',
            '\tif [[ -e "${slow}" ]]; then',
            "\t\tsleep 5",
            "\tfi",
            "done",
        ]
        self.assertEqual(_offenders("x.sh", lines), [f"x.sh:6: {lines[5].strip()}"])

    def test_a_download_that_never_leaves_the_loop_is_flagged(self) -> None:
        lines = [
            "for attempt in 1 2 3; do",
            '\tcurl -fsSL -o "${out}" "${url}"',
            "\tsleep 2",
            "done",
        ]
        self.assertEqual(_offenders("x.sh", lines), [f"x.sh:2: {lines[1].strip()}"])

    def test_a_download_outside_any_loop_is_flagged(self) -> None:
        lines = ['wget -qO "${out}" "${url}"']
        self.assertEqual(_offenders("x.sh", lines), [f"x.sh:1: {lines[0]}"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
