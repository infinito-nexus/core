"""Lint guard: standalone Playwright ``request.<method>()`` calls MUST set an
onion-aware timeout.

On an onion node every canonical / peer URL a spec hits becomes a ``.onion``
address reached through the Tor SOCKS proxy. The standalone ``request`` fixture
(``APIRequestContext``) defaults to a hard 30s timeout, which is too short for a
cold Tor circuit + descriptor fetch on first contact: the request times out
before the circuit is built. This was observed deterministically (30s ×3) for
``web-svc-simpleicons``, ``web-app-prometheus`` (``/metricz``) and
``web-svc-css`` — and ``web-svc-css`` flaked across jobs (green in one batch,
red in another), confirming a timing gap rather than a broken fixture.

``page.request`` / ``ctx.request`` inherit the browser context (which already
carries the proxy and onion-scaled navigation timeouts) and are out of scope;
only the bare ``request`` fixture is affected.

Every ``request.get|post|put|patch|delete|head|fetch(...)`` in a role Playwright
spec must therefore pass ``timeout: resolveTimeout(30_000)``. ``resolveTimeout``
(from the staged ``./timeouts`` helper — ``../timeouts`` from an ``addons/``
subdir) scales the base by the onion multiplier on ``.onion`` targets and is the
identity on clearnet, so the timed call is behaviourally unchanged off onion.

Suppress on the call's opening line with
``# nocheck: onion-request-timeout -- <reason>`` when the target is provably
never an onion host (localhost, an external clearnet API, ...).
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

# A standalone `request.<method>(` call. The negative lookbehind rejects
# `page.request.get(` / `ctx.request.get(` (member access) so only the bare
# `request` fixture is flagged.
_CALL_RE = re.compile(
    r"(?<![.\w])request\.(?:get|post|put|patch|delete|head|fetch)\s*\("
)
_RESOLVE_RE = re.compile(r"\bresolveTimeout\s*\(")
# `require("./timeouts")` / `require("../timeouts")` — the staged helper.
_IMPORTS_TIMEOUTS = re.compile(r"""require\(\s*['"][^'"]*\btimeouts['"]\s*\)""")
_NOCHECK_RE = re.compile(r"#\s*nocheck:\s*onion-request-timeout\b")


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    detail: str


def _git_ls_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "-c", "safe.directory=*", "-C", str(PROJECT_ROOT), "ls-files"],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _call_end(text: str, open_idx: int) -> int:
    """Index of the ``)`` matching the ``(`` at ``open_idx`` (string-aware).

    Returns -1 when the parentheses do not balance before EOF.
    """
    depth = 0
    quote: str | None = None
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'`":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _scan_file(path: Path) -> list[Violation]:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError) as exc:
        return [Violation(rel, 0, str(exc))]

    lines = text.splitlines()
    violations: list[Violation] = []
    for m in _CALL_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        opening_line = lines[line_no - 1] if line_no - 1 < len(lines) else ""
        if _NOCHECK_RE.search(opening_line):
            continue
        open_idx = m.end() - 1
        end_idx = _call_end(text, open_idx)
        call_text = text[open_idx:] if end_idx == -1 else text[open_idx : end_idx + 1]
        if _RESOLVE_RE.search(call_text):
            continue
        violations.append(
            Violation(
                rel,
                line_no,
                "standalone `request.*()` without `timeout: resolveTimeout(...)`",
            )
        )

    # A file that uses `resolveTimeout` must import it from the staged helper,
    # or the spec crashes at runtime (a bad `require` path is invisible to a
    # syntax check). `./timeouts` from a top-level spec, `../timeouts` from an
    # `addons/` subdir.
    if _RESOLVE_RE.search(text) and not _IMPORTS_TIMEOUTS.search(text):
        line_no = 1
        for idx, raw in enumerate(lines, 1):
            if _RESOLVE_RE.search(raw):
                line_no = idx
                break
        violations.append(
            Violation(
                rel,
                line_no,
                'uses `resolveTimeout` without `require("./timeouts")` '
                '(`../timeouts` from an addons/ subdir)',
            )
        )
    return violations


def _scan_targets() -> list[Path]:
    return [
        PROJECT_ROOT / rel
        for rel in _git_ls_files()
        if rel.endswith(".js") and "/files/playwright/" in rel
    ]


class TestOnionRequestTimeout(unittest.TestCase):
    def test_standalone_request_calls_use_onion_aware_timeout(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no Playwright spec files found to scan")
        all_violations: list[Violation] = []
        for path in targets:
            all_violations.extend(_scan_file(path))
        if all_violations:
            grouped: dict[str, list[Violation]] = {}
            for v in all_violations:
                grouped.setdefault(v.file, []).append(v)
            header = [
                f"Standalone Playwright `request.*()` without an onion-aware "
                f"timeout ({len(all_violations)} across {len(grouped)} file(s)):",
                "",
                "On an onion node the target is a `.onion` reached via Tor; the",
                "default 30s APIRequestContext timeout is too short for a cold",
                "circuit on first contact and the request times out.",
                "",
                "Fix each call:",
                "  request.get(url, { timeout: resolveTimeout(30_000) })",
                'and import the helper (top-level spec: require("./timeouts");',
                'addons/ subdir spec: require("../timeouts")).',
                "`resolveTimeout` is the identity on clearnet, so this is a no-op",
                "off onion. If the target is provably never onion, suppress on the",
                "call's opening line with",
                "`# nocheck: onion-request-timeout -- <reason>`.",
                "",
                "Offenders:",
            ]
            body: list[str] = []
            for f, vs in sorted(grouped.items()):
                body.append(f"  {f}:")
                body.extend(f"    line {v.line_no}: {v.detail}" for v in vs)
            self.fail("\n".join(header + body))


if __name__ == "__main__":
    unittest.main()
