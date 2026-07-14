"""Lint: every click in the shared persona auth flows MUST scale its timeout.

The persona helpers under ``roles/test-e2e-playwright/files/personas/`` drive
login, logout and OIDC hand-offs for every role's E2E suite. A click that
submits credentials or follows an auth redirect auto-waits for the resulting
navigation; over a ``.onion`` target that redirect chain routinely exceeds
Playwright's fixed 30s default action timeout, so the click itself throws
before the flow's own (scaled) waits ever run. Because these files are
auth-flow-only, every ``.click(...)`` here must carry an onion-scaled timeout:

    await button.click({ timeout: resolveTimeout(30_000) });

Per-line opt-out for a click that genuinely must not scale (e.g. a DOM
``.click()`` inside ``page.evaluate``): ``// nocheck: unscaled-click`` plus a
one-line rationale.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_PERSONAS_DIR = PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "personas"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")
_STRING = re.compile(
    r"`(?:[^`\\]|\\.)*`|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", re.DOTALL
)

_CLICK = re.compile(r"\.click\(")
_NOCHECK = re.compile(r"nocheck:\s*unscaled-click")


def _blank(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _strip(text: str) -> str:
    text = _BLOCK_COMMENT.sub(_blank, text)
    text = _LINE_COMMENT.sub(_blank, text)
    return _STRING.sub(_blank, text)


def _click_args_span(text: str, open_paren: int) -> str:
    """Return the argument text of the call whose ``(`` sits at ``open_paren``."""
    depth = 0
    for i in range(open_paren, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : i]
    return text[open_paren + 1 :]


class TestPersonaClicksScaled(unittest.TestCase):
    def test_persona_clicks_carry_scaled_timeout(self):
        offenders: list[str] = []
        for path in sorted(_PERSONAS_DIR.glob("**/*.js")):
            raw_lines = read_text(str(path)).splitlines()
            text = _strip(read_text(str(path)))
            for m in _CLICK.finditer(text):
                args = _click_args_span(text, m.end() - 1)
                if "resolveTimeout" in args:
                    continue
                line = text[: m.start()].count("\n") + 1
                raw_line = raw_lines[line - 1] if line - 1 < len(raw_lines) else ""
                if _NOCHECK.search(raw_line):
                    continue
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{line}: `{raw_line.strip()[:90]}`"
                )

        if offenders:
            self.fail(
                "Every click in the shared persona auth flows must pass an "
                "onion-scaled timeout — `.click({ timeout: resolveTimeout(N) })` "
                "— so credential submits and OIDC redirects survive Tor "
                "latency. Annotate with `// nocheck: unscaled-click` plus a "
                "rationale only for non-Playwright DOM clicks:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
