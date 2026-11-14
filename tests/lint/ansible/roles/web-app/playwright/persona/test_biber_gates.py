from __future__ import annotations

import re
import unittest
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from tests.lint.filesystem.playwright.test_ldap_scenarios import (
    Scenario,
    _functions_of,
    helper_functions_in,
    scenarios_in,
)
from tests.lint.filesystem.playwright.test_sso_ldap_gate_canonical import (
    _close_of,
    _first_argument,
    _lex,
    _scan_targets,
)
from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_TEST_RE = re.compile(r"(?<![\w$.])test\s*\(")
_CALL_RE = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*\(")
_MAX_DEPTH = 6
_SIGN_IN_SERVICES = frozenset({"sso", "ldap"})
_ENABLED = "enabled"
_BIBER_FLOW = "runBiberFlow"


@dataclass(frozen=True)
class PersonaTest:
    scenario: Scenario
    code: str


def _reached(
    fragment: str, functions: Mapping[str, list[str]], seen: set[str], depth: int
) -> list[str]:
    texts = [fragment]
    if depth >= _MAX_DEPTH:
        return texts
    for name in set(_CALL_RE.findall(fragment)) - seen:
        seen.add(name)
        for body in functions.get(name, ()):
            texts.extend(_reached(body, functions, seen, depth + 1))
    return texts


def persona_tests_in(
    rel: str, text: str, helpers: Mapping[str, list[str]]
) -> list[PersonaTest]:
    """Pair every ``test(...)`` of one module with the code its body reaches.

    Args:
        rel: the module's repository-relative path.
        text: the JavaScript source of the module.
        helpers: ``helper_functions_in`` over the role's Playwright directory.

    Returns:
        One :class:`PersonaTest` per test, its ``code`` holding the comment-free
        body plus every function body it calls, up to six calls deep.
    """
    code, skeleton = _lex(text)
    functions = {**helpers, **_functions_of(code, skeleton)}
    bodies: list[str] = []
    for match in _TEST_RE.finditer(skeleton):
        close = _close_of(skeleton, match.end() - 1)
        if close == -1:
            continue
        _, title_end = _first_argument(skeleton, match.end() - 1, close)
        bodies.append("\n".join(_reached(code[title_end:close], functions, set(), 0)))
    return [
        PersonaTest(scenario, body)
        for scenario, body in zip(scenarios_in(rel, text, helpers), bodies, strict=True)
    ]


@cache
def role_persona_tests() -> dict[str, list[PersonaTest]]:
    """Collect the persona tests of every role's Playwright directory.

    Returns:
        Role name mapped to the :class:`PersonaTest` of each of its tests.
    """
    by_role: dict[str, list[PersonaTest]] = defaultdict(list)
    for rels in _scan_targets().values():
        texts = {rel: read_text(str(PROJECT_ROOT / rel)) for rel in rels}
        helpers = helper_functions_in(texts.values())
        for rel, text in texts.items():
            by_role[rel.split("/")[1]].extend(persona_tests_in(rel, text, helpers))
    return by_role


def runs_biber_flow(item: PersonaTest) -> bool:
    """Tell whether a test reaches the shared ``runBiberFlow`` persona.

    Args:
        item: one :func:`persona_tests_in` result.
    """
    return _BIBER_FLOW in _CALL_RE.findall(item.code)


def is_biber_scenario(item: PersonaTest) -> bool:
    """Tell whether a test is a ``biber:`` scenario outside ``runBiberFlow``.

    Args:
        item: one :func:`persona_tests_in` result.
    """
    return item.scenario.title.startswith("biber:") and not runs_biber_flow(item)


def _sign_in_gates(scenario: Scenario) -> frozenset[tuple[str, str]]:
    return frozenset(g for g in scenario.gates if g[1] in _SIGN_IN_SERVICES)


def _enabled(gates: Iterable[tuple[str, str]]) -> set[str]:
    return {service for kind, service in gates if kind == _ENABLED}


def biber_gate_offenders(items: Iterable[PersonaTest]) -> list[tuple[Scenario, str]]:
    """Return the biber scenarios whose sso and ldap gates break the gate rule.

    Args:
        items: :func:`persona_tests_in` results of one role.

    Returns:
        Each offending scenario with ``"ungated"`` when it reaches no enabled
        ``sso`` or ``ldap`` gate, or ``"mismatch"`` when its ``sso`` and ``ldap``
        gates equal none of the ``administrator:`` tests of its module that gate
        on one of the services it gates on.
    """
    items = list(items)
    admins = [
        i.scenario for i in items if i.scenario.title.startswith("administrator:")
    ]
    offenders: list[tuple[Scenario, str]] = []
    for item in items:
        if not is_biber_scenario(item):
            continue
        scenario = item.scenario
        gates = _sign_in_gates(scenario)
        if not _enabled(gates):
            offenders.append((scenario, "ungated"))
            continue
        matching = {
            _sign_in_gates(admin)
            for admin in admins
            if admin.file == scenario.file
            and _enabled(_sign_in_gates(admin)) & _enabled(gates)
        }
        if matching and gates not in matching:
            offenders.append((scenario, "mismatch"))
    return offenders


class TestBiberGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.by_role = role_persona_tests()

    def test_persona_tests_were_found(self) -> None:
        self.assertTrue(self.by_role, "no Playwright test(...) found to scan")

    def test_biber_scenarios_gate_like_their_administrator(self) -> None:
        offenders = sorted(
            (scenario, reason)
            for items in self.by_role.values()
            for scenario, reason in biber_gate_offenders(items)
        )
        if offenders:
            self.fail(
                f"biber: tests outside runBiberFlow with the wrong sign-in gates ({len(offenders)}):\n\n"
                'Gate the test on skipUnlessServiceEnabled("sso") or ("ldap"), so a deploy with\n'
                "disable=sso,ldap reports it as skipped, and on the same sso and ldap gates as\n"
                "the administrator: tests of its module that gate on one of those services.\n\n"
                "Offenders:\n"
                + "\n".join(
                    f"  {s.file}:{s.line_no}: [{reason}] {s.title[:120]}"
                    for s, reason in offenders
                )
            )


if __name__ == "__main__":
    unittest.main()
