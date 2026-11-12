from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tests.lint.filesystem.playwright.test_sso_ldap_gate_canonical import (
    _close_of,
    _first_argument,
    _lex,
)

from .test_biber_gates import PersonaTest, role_persona_tests, runs_biber_flow

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from tests.lint.filesystem.playwright.test_ldap_scenarios import Scenario

_EXPECT_RE = re.compile(r"(?<![\w$.])expect\s*(?:\.\s*(?:poll|soft)\s*)?\(")
_MATCHER_RE = re.compile(r"\s*(\.\s*not)?\s*\.\s*(to\w+)\s*\(")
_WEB_FIRST = frozenset(
    {
        "toBeAttached",
        "toBeVisible",
        "toContainText",
        "toHaveText",
        "toHaveTitle",
        "toHaveURL",
    }
)
_COUNT = "toHaveCount"
_VALUE_MATCHERS = frozenset(
    {"toBe", "toContain", "toEqual", "toMatch", "toStrictEqual"}
)
_PAGE_READ_RE = re.compile(
    r"\.\s*(?:url|title|innerText|textContent|allInnerTexts|allTextContents)\s*\("
)
_ADMIN_RE = re.compile(
    r"(?i)(?<![\w$-])(?:wp-)?admin(?:istration|istrator|s)?(?![\w$]|-bar\b)"
)
_SECOND_SESSION_RE = re.compile(
    r"\bnew(?:Context|Page)\s*\(|\badmin\w*(?:Page|Context)\b|"
    r"\badmin(?:Username|Password)\b|\bADMIN_(?:USERNAME|PASSWORD)\b"
)
_ADMIN_GRANT_RE = re.compile(
    r"(?i)administrator\w*_?group|groups\.administrator|[-/]administrator\b|site-?owner"
)


@dataclass(frozen=True)
class Assertion:
    subject: str
    negated: bool
    matcher: str
    expected: str


def assertions_in(code: str) -> Iterator[Assertion]:
    """Yield every ``expect(...)`` of a comment-free JavaScript fragment.

    Args:
        code: a :class:`PersonaTest` ``code``.

    Returns:
        One :class:`Assertion` per ``expect``, ``expect.poll`` or ``expect.soft``
        call followed by a matcher, with the first argument of each side.
    """
    _, skeleton = _lex(code)
    for match in _EXPECT_RE.finditer(skeleton):
        open_idx = match.end() - 1
        close = _close_of(skeleton, open_idx)
        tail = _MATCHER_RE.match(skeleton, close + 1) if close != -1 else None
        if tail is None:
            continue
        subject_start, subject_end = _first_argument(skeleton, open_idx, close)
        matcher_open = tail.end() - 1
        matcher_close = _close_of(skeleton, matcher_open)
        expected = ""
        if matcher_close != -1:
            start, end = _first_argument(skeleton, matcher_open, matcher_close)
            expected = code[start:end].strip()
        yield Assertion(
            code[subject_start:subject_end].strip(),
            bool(tail.group(1)),
            tail.group(2),
            expected,
        )


def is_surface(assertion: Assertion) -> bool:
    """Tell whether an assertion pins what the page renders for its viewer.

    Args:
        assertion: one :func:`assertions_in` result.
    """
    if assertion.negated:
        return False
    if assertion.matcher in _WEB_FIRST:
        return True
    if assertion.matcher == _COUNT:
        return assertion.expected not in ("", "0")
    return assertion.matcher in _VALUE_MATCHERS and bool(
        _PAGE_READ_RE.search(assertion.subject)
    )


def asserts_admin_ui(assertion: Assertion) -> bool:
    """Tell whether a surface assertion expects an admin-only element or path.

    Args:
        assertion: one :func:`assertions_in` result.
    """
    return is_surface(assertion) and bool(
        _ADMIN_RE.search(assertion.subject) or _ADMIN_RE.search(assertion.expected)
    )


def _biber_only_session(item: PersonaTest) -> bool:
    return not (
        _SECOND_SESSION_RE.search(item.code) or _ADMIN_GRANT_RE.search(item.code)
    )


def _ends_on_surface(item: PersonaTest) -> bool:
    return runs_biber_flow(item) or any(is_surface(a) for a in assertions_in(item.code))


def end_surface_offenders(items: Iterable[PersonaTest]) -> list[tuple[Scenario, str]]:
    """Return the biber scenarios that break the end-surface rule.

    Args:
        items: :func:`persona_tests_in` results of one role.

    Returns:
        The role's first ``biber:`` scenario with ``"no-surface"`` when none of
        its ``biber:`` tests runs ``runBiberFlow`` or reaches an assertion that
        pins the rendered page, then each ``biber:`` scenario with
        ``"admin-ui"`` whose lone biber session expects an admin-only element
        or path.
    """
    biber = [i for i in items if i.scenario.title.startswith("biber:")]
    offenders = [
        (item.scenario, "admin-ui")
        for item in biber
        if _biber_only_session(item)
        and any(asserts_admin_ui(a) for a in assertions_in(item.code))
    ]
    if biber and not any(_ends_on_surface(item) for item in biber):
        offenders.insert(0, (biber[0].scenario, "no-surface"))
    return offenders


class TestBiberEndSurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.by_role = role_persona_tests()

    def test_persona_tests_were_found(self) -> None:
        self.assertTrue(self.by_role, "no Playwright test(...) found to scan")

    def test_biber_scenarios_end_on_a_non_admin_surface(self) -> None:
        offenders = sorted(
            (scenario, reason)
            for items in self.by_role.values()
            for scenario, reason in end_surface_offenders(items)
        )
        if offenders:
            self.fail(
                f"biber: scenarios without a non-admin end surface ({len(offenders)}):\n\n"
                "[no-surface]: let one biber: test of the role run runBiberFlow or end on a\n"
                "deterministic surface the biber session renders: a URL (toHaveURL,\n"
                "page.url()), a heading or title (toHaveTitle, toHaveText) or a stable\n"
                "selector (toBeVisible, toBeAttached, toHaveCount(n > 0)).\n"
                "[admin-ui]: never expect an admin-only element or path from a lone biber\n"
                "session.\n\nOffenders:\n"
                + "\n".join(
                    f"  {s.file}:{s.line_no}: [{reason}] {s.title[:120]}"
                    for s, reason in offenders
                )
            )


if __name__ == "__main__":
    unittest.main()
