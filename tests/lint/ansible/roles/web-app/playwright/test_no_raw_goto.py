"""Lint: every navigation in a Playwright test MUST go through ``gotoOnion``.

Onion (Tor) rendezvous circuits vary per connection, so a cold circuit can fail
a navigation with a transient transport error (``ERR_TIMED_OUT`` /
``ERR_SOCKS…``) that a retry on a fresh circuit resolves. A raw ``page.goto(...)``
gets a single attempt and flakes over ``.onion``; the shared helper
``roles/test-e2e-playwright/files/personas/utils/env.js`` (``gotoOnion``) retries
only those transient Tor-transport errors, defaults the onion timeout, and is a
behaviour-identical drop-in on clearnet (single attempt, same return value).

Forbidden: ``page.goto(...)``. Allowed: ``gotoOnion(page, ...)``.

Scope: role specs + companions under ``roles/*/files/playwright/`` and the
persona-flow files. The onion primitive itself (``personas/utils/`` — where
``gotoOnion`` wraps the one legitimate raw ``page.goto``) is exempt because it is
not part of the target set.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_PERSONA_FLOW_DIR = (
    PROJECT_ROOT / "roles" / "test-e2e-playwright" / "files" / "personas"
)
_PERSONA_FLOW_FILES: tuple[str, ...] = ("biber.js", "admin.js", "guest.js")

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# Line comment not preceded by `:` so URLs (`http://…`) are not mistaken for one.
_LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")
# String literals (template / double / single, escape-aware). Blanked so a
# `page.goto(` mentioned inside an error message string is not a false match; a
# real call keeps its `page.goto(` before the string argument.
_STRING = re.compile(
    r"`(?:[^`\\]|\\.)*`|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", re.DOTALL
)

_RAW_GOTO = re.compile(r"\bpage\.goto\(")


def _blank(match: re.Match[str]) -> str:
    """Replace a comment/string with spaces, preserving newlines so line numbers hold."""
    return re.sub(r"[^\n]", " ", match.group(0))


def _strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT.sub(_blank, text)
    text = _LINE_COMMENT.sub(_blank, text)
    return _STRING.sub(_blank, text)


def _target_files() -> list:
    files = sorted(PROJECT_ROOT.glob("roles/*/files/playwright/**/*.js"))
    files += [
        _PERSONA_FLOW_DIR / name
        for name in _PERSONA_FLOW_FILES
        if (_PERSONA_FLOW_DIR / name).is_file()
    ]
    return files


class TestNoRawGoto(unittest.TestCase):
    def test_navigation_goes_through_goto_onion(self):
        offenders: list[str] = []
        for path in _target_files():
            text = _strip_comments(read_text(str(path)))
            for m in _RAW_GOTO.finditer(text):
                line = text[: m.start()].count("\n") + 1
                snippet = text[m.start() : m.start() + 40].splitlines()[0].strip()
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{line}: `{snippet}`"
                )

        if offenders:
            self.fail(
                "Raw `page.goto(...)` is forbidden — navigate via "
                "`gotoOnion(page, ...)` (require it from `./personas`, persona "
                "flows from `./utils`) so navigation retries transient Tor "
                "transport errors over onion:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
