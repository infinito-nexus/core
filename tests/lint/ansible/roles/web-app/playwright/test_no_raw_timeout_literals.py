"""Lint: every timeout in a Playwright test MUST go through ``resolveTimeout``.

Onion (Tor) targets add per-request circuit latency, so the shared helper
``roles/test-e2e-playwright/files/timeouts.js`` scales every base timeout by the
global ``PLAYWRIGHT_TIMEOUT_FACTOR`` and — when the canonical domain is a
``.onion`` — by the onion multiplier. A raw numeric literal bypasses that
scaling and flakes over onion while passing on clearnet.

Forbidden (raw milliseconds)          Required (scaled)
    ``timeout: 30_000``                   ``timeout: resolveTimeout(30_000)``
    ``waitForTimeout(500)``               ``waitForTimeout(resolveTimeout(500))``
    ``test.setTimeout(120_000)``          ``test.setTimeout(resolveTimeout(120_000))``
    ``setTimeout(resolve, 250)``          ``setTimeout(resolve, resolveTimeout(250))``

Scope: role specs + companions under ``roles/*/files/playwright/`` and the
shared persona flows/utilities under ``roles/test-e2e-playwright/files/``. The
scaling primitive itself (``timeouts.js``) is exempt. Per-line opt-out for a
duration that intentionally must NOT scale: ``// nocheck: raw-timeout`` plus a
one-line rationale.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_SHARED_DIR = PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")
_STRING = re.compile(
    r"`(?:[^`\\]|\\.)*`|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", re.DOTALL
)

_RAW_TIMEOUT = re.compile(
    r"\btimeout:\s*[0-9]"
    r"|\bwaitForTimeout\(\s*[0-9]"
    r"|\bsetTimeout\(\s*[0-9]"
    r"|\bsetTimeout\(\s*[^,()]+,\s*[0-9]"
)
_NOCHECK = re.compile(r"nocheck:\s*raw-timeout")


def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _strip_strings(text: str) -> str:
    text = _BLOCK_COMMENT.sub(_blank, text)
    return _STRING.sub(_blank, text)


def _target_files() -> list:
    files = sorted(PROJECT_ROOT.glob("roles/*/files/playwright/**/*.js"))
    files += sorted(_SHARED_DIR.glob("**/*.js"))
    return [f for f in dict.fromkeys(files) if f.name != "timeouts.js"]


class TestNoRawTimeoutLiterals(unittest.TestCase):
    def test_timeouts_route_through_resolve_timeout(self):
        offenders: list[str] = []
        for path in _target_files():
            raw_lines = read_text(str(path)).splitlines()
            text = _strip_strings(read_text(str(path)))
            for m in _RAW_TIMEOUT.finditer(_LINE_COMMENT.sub(_blank, text)):
                line = text[: m.start()].count("\n") + 1
                raw_line = raw_lines[line - 1] if line - 1 < len(raw_lines) else ""
                if _NOCHECK.search(raw_line):
                    continue
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{line}: `{raw_line.strip()[:90]}`"
                )

        if offenders:
            self.fail(
                "Raw numeric timeout literals are forbidden in Playwright "
                "specs — wrap the base milliseconds in `resolveTimeout(...)` "
                "(from `./timeouts`) so the value scales on onion targets. "
                "Annotate with `// nocheck: raw-timeout` plus a rationale only "
                "when a duration must intentionally not scale:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
