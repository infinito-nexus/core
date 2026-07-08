"""Lint: every timeout in a Playwright test MUST go through ``resolveTimeout``.

Onion (Tor) transport adds per-request latency, so a raw numeric timeout that is
fine on clearnet silently fails over ``.onion``. The shared helper
``roles/test-e2e-playwright/files/timeouts.js`` scales a base timeout by the
global ``TIMEOUT_FACTOR`` and an onion multiplier; every spec + persona-flow file
MUST route its timeouts through it so the whole suite is onion-compatible.

Forbidden (raw numeric literal): ``timeout: <n>``, ``timeout = <n>``,
``setTimeout(<n>)``, ``waitForTimeout(<n>)``. Allowed: the same wrapped in
``resolveTimeout(<n>)`` (the char after ``:``/``=``/``(`` is then ``r``, not a
digit). Positional numeric args to custom deadline helpers cannot be detected
statically; those helpers must scale their own ``timeout`` param instead.

Scope: role specs + companions under ``roles/*/files/playwright/`` and the
persona-flow files. The onion primitives themselves (``personas/utils/`` — e.g.
``gotoOnion``), the helper, the config and the gating helpers are exempt.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_PERSONA_FLOW_DIR = PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "personas"
_PERSONA_FLOW_FILES: tuple[str, ...] = ("biber.js", "admin.js", "guest.js")

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# Line comment not preceded by `:` so URLs (`http://…`) are not mistaken for one.
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")

_RAW_TIMEOUT = re.compile(
    r"\b(?:timeout:\s*|timeout\s*=\s*|setTimeout\(\s*|waitForTimeout\(\s*)[0-9]"
)


def _blank(match: re.Match[str]) -> str:
    """Replace a comment with spaces, preserving newlines so line numbers hold."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT.sub(_blank, text)
    return _LINE_COMMENT.sub(_blank, text)


def _target_files() -> list:
    files = sorted(PROJECT_ROOT.glob("roles/*/files/playwright/**/*.js"))
    files += [
        _PERSONA_FLOW_DIR / name
        for name in _PERSONA_FLOW_FILES
        if (_PERSONA_FLOW_DIR / name).is_file()
    ]
    return files


class TestNoRawTimeouts(unittest.TestCase):
    def test_timeouts_go_through_resolve(self):
        offenders: list[str] = []
        for path in _target_files():
            text = _strip_comments(read_text(str(path)))
            for m in _RAW_TIMEOUT.finditer(text):
                line = text[: m.start()].count("\n") + 1
                snippet = text[m.start() : m.start() + 40].splitlines()[0].strip()
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{line}: `{snippet}`"
                )

        if offenders:
            self.fail(
                "Raw numeric timeouts are forbidden — wrap each in "
                "`resolveTimeout(...)` (require it from `./timeouts`, personas via "
                "`../timeouts`) so timeouts scale over Tor/onion:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
