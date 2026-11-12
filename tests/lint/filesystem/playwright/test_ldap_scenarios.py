"""Lint guard: LDAP scenarios are persona tests behind the canonical ``ldap`` gate.

Every LDAP scenario is a test of its own:

* A test whose title names LDAP reaches ``skipUnlessServiceEnabled("ldap")``, so a
  deploy with ``disable=ldap`` reports it as ``skipped: LDAP_SERVICE_ENABLED=false``.
  A test that asserts the LDAP-off state through ``skipUnlessServiceDisabled("ldap")``
  passes, and so does a test without a persona token that reaches the ``sso`` gate:
  it probes the LDAP side from the SSO journey (login-method toggles, write-through).
* A test that reaches ``skipUnlessServiceEnabled("ldap")`` and names ``biber`` or
  ``administrator`` in its title starts that title with a persona token (``guest:``,
  ``biber:``, ``administrator:``) or with a ``${...}:`` placeholder that renders one,
  so the reporter groups the LDAP sign-in with that persona.

* A role whose ``meta/services.yml`` leaves ``ldap.enabled`` other than ``false`` and
  whose env template renders persona credentials ships at least one ldap-gated test,
  or its README carries an ``LDAP coverage`` section that states the exemption.
* A role with an ``administrator:`` ldap-gated test but no ``biber:`` one flags the
  biber follow-up in the ``LDAP coverage`` section of its README.

A gate counts when the test calls it directly, through a function declared in the
role's Playwright directory, or through a ``test.beforeEach`` / ``test.beforeAll``
hook of its file or of an enclosing ``test.describe``.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_README

from . import PROJECT_ROOT
from .test_sso_ldap_gate_canonical import (
    _PART_RE,
    _WORD_RE,
    _close_of,
    _first_argument,
    _lex,
    _scan_targets,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_TEST_RE = re.compile(r"(?<![\w$.])test\s*\(")
_DESCRIBE_RE = re.compile(r"(?<![\w$.])test\.describe(?:\.\w+)*\s*\(")
_HOOK_RE = re.compile(r"(?<![\w$.])test\.(?:beforeEach|beforeAll)\s*\(")
_GATE_RE = re.compile(
    r"\b(skipUnlessServiceEnabled|skipUnlessServiceDisabled|requireService|"
    r"safeSkipUnlessEnabled)\s*\(\s*['\"]([^'\"]+)['\"]"
)
_FUNCTION_DECL_RE = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")
_FUNCTION_BIND_RE = re.compile(
    r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?"
    r"(?:function\b[^{]*|(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*=>\s*)\{"
)
_CALL_RE = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)\s*\(")
_REFERENCE_RE = re.compile(r"(?<![\w$])([A-Za-z_$][\w$]*)")
_PERSONA_TITLE_RE = re.compile(r"^(?:guest|biber|administrator):|^\$\{[^}]*\}:")
_SIGNED_IN_PERSONA_RE = re.compile(r"\b(?:biber|administrator)\b", re.IGNORECASE)
_BIBER_RE = re.compile(r"\bbiber\b")
_ADMINISTRATOR_RE = re.compile(r"\badministrator\b", re.IGNORECASE)
_ENABLED = "enabled"
_DISABLED = "disabled"
_GATE_KIND = {
    "skipUnlessServiceEnabled": _ENABLED,
    "requireService": _ENABLED,
    "safeSkipUnlessEnabled": _ENABLED,
    "skipUnlessServiceDisabled": _DISABLED,
}
_MAX_DEPTH = 6
_ENV_TEMPLATE_REL = "templates/playwright.env.j2"  # nocheck: role-file-spot
_PERSONA_CREDENTIAL_RE = re.compile(r"^\s*(?:ADMIN|BIBER)_USERNAME\s*=", re.MULTILINE)
_COVERAGE_SECTION_RE = re.compile(
    r"^##+[ \t]+LDAP coverage[ \t]*$(.*?)(?=^#|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class Scenario:
    file: str
    line_no: int
    title: str
    gates: frozenset[tuple[str, str]]


def _body_after(skeleton: str, start: int) -> tuple[int, int] | None:
    brace = skeleton.find("{", start)
    if brace == -1:
        return None
    close = _close_of(skeleton, brace)
    return None if close == -1 else (brace, close)


def _functions_of(code: str, skeleton: str) -> dict[str, list[str]]:
    functions: dict[str, list[str]] = {}
    for match in _FUNCTION_DECL_RE.finditer(skeleton):
        params_close = _close_of(skeleton, match.end() - 1)
        span = None if params_close == -1 else _body_after(skeleton, params_close)
        if span:
            functions.setdefault(match.group(1), []).append(code[span[0] : span[1]])
    for match in _FUNCTION_BIND_RE.finditer(skeleton):
        close = _close_of(skeleton, match.end() - 1)
        if close != -1:
            functions.setdefault(match.group(1), []).append(
                code[match.end() - 1 : close]
            )
    return functions


def helper_functions_in(texts: Iterable[str]) -> dict[str, list[str]]:
    """Collect the functions of the helper modules in a role's Playwright directory.

    A module that declares no ``test(...)`` is a helper module (``_shared.js``,
    ``sign-in.js``); functions of test modules stay local to their own module.

    Args:
        texts: the JavaScript sources of one role's Playwright directory.

    Returns:
        Function name mapped to the comment-free code of each body declared for it.
    """
    functions: dict[str, list[str]] = {}
    for text in texts:
        code, skeleton = _lex(text)
        if _TEST_RE.search(skeleton):
            continue
        for name, bodies in _functions_of(code, skeleton).items():
            functions.setdefault(name, []).extend(bodies)
    return functions


def _gates_in(
    code_fragment: str,
    functions: Mapping[str, list[str]],
    seen: set[str],
    depth: int,
    names_re: re.Pattern[str],
) -> set[tuple[str, str]]:
    gates = {
        (_GATE_KIND[helper], service.lower())
        for helper, service in _GATE_RE.findall(code_fragment)
    }
    if depth >= _MAX_DEPTH:
        return gates
    for name in set(names_re.findall(code_fragment)) - seen:
        seen.add(name)
        for body in functions.get(name, ()):
            gates |= _gates_in(body, functions, seen, depth + 1, _CALL_RE)
    return gates


def _innermost(spans: list[tuple[int, int]], index: int) -> tuple[int, int] | None:
    enclosing = [span for span in spans if span[0] < index < span[1]]
    return min(enclosing, key=lambda span: span[1] - span[0], default=None)


def _title_of(code: str, start: int, end: int) -> str:
    title = code[start:end].strip()
    if len(title) >= 2 and title[0] in "\"'`" and title[-1] == title[0]:
        return title[1:-1]
    return title


def scenarios_in(
    rel: str, text: str, helpers: Mapping[str, list[str]]
) -> list[Scenario]:
    """Resolve every ``test(...)`` of one module with the service gates it reaches.

    Args:
        rel: the module's repository-relative path, carried into each scenario.
        text: the JavaScript source of the module.
        helpers: :func:`helper_functions_in` over the role's Playwright directory.

    Returns:
        One :class:`Scenario` per test, its gates as ``(kind, service)`` pairs with
        ``kind`` either ``"enabled"`` or ``"disabled"``.
    """
    code, skeleton = _lex(text)
    functions = {**helpers, **_functions_of(code, skeleton)}
    describes = []
    for match in _DESCRIBE_RE.finditer(skeleton):
        close = _close_of(skeleton, match.end() - 1)
        if close != -1:
            describes.append((match.end() - 1, close))
    hooks = []
    for match in _HOOK_RE.finditer(skeleton):
        close = _close_of(skeleton, match.end() - 1)
        if close != -1:
            gates = _gates_in(
                code[match.end() : close], functions, set(), 0, _REFERENCE_RE
            )
            hooks.append((_innermost(describes, match.start()), gates))
    scenarios: list[Scenario] = []
    for match in _TEST_RE.finditer(skeleton):
        open_idx = match.end() - 1
        close = _close_of(skeleton, open_idx)
        if close == -1:
            continue
        title_start, title_end = _first_argument(skeleton, open_idx, close)
        gates = _gates_in(code[title_end:close], functions, set(), 0, _CALL_RE)
        for scope, hook_gates in hooks:
            if scope is None or scope[0] < match.start() < scope[1]:
                gates |= hook_gates
        scenarios.append(
            Scenario(
                rel,
                text.count("\n", 0, match.start()) + 1,
                _title_of(code, title_start, title_end),
                frozenset(gates),
            )
        )
    return scenarios


def _names_ldap(title: str) -> bool:
    return any(
        part.lower() == "ldap"
        for word in _WORD_RE.findall(title)
        for part in _PART_RE.findall(word)
    )


def ungated_ldap_scenarios(scenarios: Iterable[Scenario]) -> list[Scenario]:
    """Return the tests whose title names LDAP but which skip past the ldap gate.

    Args:
        scenarios: :func:`scenarios_in` results.
    """
    return [
        s
        for s in scenarios
        if _names_ldap(s.title)
        and (_ENABLED, "ldap") not in s.gates
        and (_DISABLED, "ldap") not in s.gates
        and (_PERSONA_TITLE_RE.match(s.title) or (_ENABLED, "sso") not in s.gates)
    ]


def unpersonified_ldap_scenarios(scenarios: Iterable[Scenario]) -> list[Scenario]:
    """Return the ldap-gated tests that name a persona but start with no persona token.

    Args:
        scenarios: :func:`scenarios_in` results.
    """
    return [
        s
        for s in scenarios
        if (_ENABLED, "ldap") in s.gates
        and _SIGNED_IN_PERSONA_RE.search(s.title)
        and not _PERSONA_TITLE_RE.match(s.title)
    ]


def combined_sso_ldap_scenarios(scenarios: Iterable[Scenario]) -> list[Scenario]:
    """Return the tests that reach both the ``sso`` and the ``ldap`` enabled gate.

    Args:
        scenarios: :func:`scenarios_in` results.
    """
    return [
        s
        for s in scenarios
        if (_ENABLED, "sso") in s.gates and (_ENABLED, "ldap") in s.gates
    ]


def declares_ldap(services: object) -> bool:
    """Tell whether a parsed ``meta/services.yml`` leaves ``ldap.enabled`` switchable on.

    Args:
        services: the YAML root of the role's ``meta/services.yml``.
    """
    ldap = services.get("ldap") if isinstance(services, dict) else None
    if not isinstance(ldap, dict) or "enabled" not in ldap:
        return False
    return str(ldap["enabled"]).strip().lower() != "false"


def ldap_coverage_section(readme: str) -> str | None:
    """Return the body of a README's ``LDAP coverage`` section, if it has one.

    Args:
        readme: the role README text.
    """
    match = _COVERAGE_SECTION_RE.search(readme)
    return match.group(1) if match else None


def _ldap_gated(scenarios: Iterable[Scenario]) -> list[Scenario]:
    return [s for s in scenarios if (_ENABLED, "ldap") in s.gates]


def ldap_persona_gap(scenarios: Iterable[Scenario]) -> str | None:
    """Name the persona a role's ldap-gated tests never sign in.

    Args:
        scenarios: :func:`scenarios_in` results of one role.

    Returns:
        ``"biber"`` or ``"administrator"`` when only the other persona has an
        ldap-gated test, ``"persona"`` when no ldap-gated test carries a persona
        token, ``None`` when both are covered or no test is ldap-gated.
    """
    titles = [s.title for s in _ldap_gated(scenarios)]
    if not titles:
        return None
    placeholder = any(t.startswith("${") for t in titles)
    admin = placeholder or any(t.startswith("administrator:") for t in titles)
    biber = placeholder or any(t.startswith("biber:") for t in titles)
    if admin and biber:
        return None
    if admin:
        return "biber"
    return "administrator" if biber else "persona"


def lacks_biber_ldap_scenario(scenarios: Iterable[Scenario]) -> bool:
    """Tell whether a role signs the administrator in over LDAP but never biber.

    Args:
        scenarios: :func:`scenarios_in` results of one role.
    """
    return ldap_persona_gap(scenarios) == "biber"


def _role_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []
    for rels in _scan_targets().values():
        texts = {rel: read_text(str(PROJECT_ROOT / rel)) for rel in rels}
        helpers = helper_functions_in(texts.values())
        for rel, text in texts.items():
            scenarios.extend(scenarios_in(rel, text, helpers))
    return scenarios


def _report(header: list[str], offenders: list[Scenario]) -> str:
    body = [f"  {s.file}:{s.line_no}: {s.title[:140]}" for s in sorted(offenders)]
    return "\n".join([*header, "", "Offenders:", *body])


class TestLdapScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenarios = _role_scenarios()

    def test_scenarios_were_found(self) -> None:
        self.assertTrue(self.scenarios, "no Playwright test(...) found to scan")

    def test_ldap_scenarios_gate_on_ldap(self) -> None:
        offenders = ungated_ldap_scenarios(self.scenarios)
        if offenders:
            self.fail(
                _report(
                    [
                        f"Playwright tests naming LDAP without the ldap gate ({len(offenders)}):",
                        "",
                        'Call skipUnlessServiceEnabled("ldap") from ./service-gating at the top of',
                        "the test, so a deploy with disable=ldap reports it as",
                        "skipped: LDAP_SERVICE_ENABLED=false.",
                    ],
                    offenders,
                )
            )

    def test_ldap_scenarios_carry_a_persona_token(self) -> None:
        offenders = unpersonified_ldap_scenarios(self.scenarios)
        if offenders:
            self.fail(
                _report(
                    [
                        f"ldap-gated Playwright tests naming a persona without its token ({len(offenders)}):",
                        "",
                        "Start the title with administrator:, biber: or guest: so the reporter",
                        "groups the LDAP scenario with its persona.",
                    ],
                    offenders,
                )
            )

    def test_sso_and_ldap_scenarios_keep_separate_bodies(self) -> None:
        offenders = combined_sso_ldap_scenarios(self.scenarios)
        if offenders:
            self.fail(
                _report(
                    [
                        f"Playwright tests gated on both sso and ldap ({len(offenders)}):",
                        "",
                        'Gate the LDAP sign-in on skipUnlessServiceEnabled("ldap") alone and let',
                        'isServiceEnabled("sso") pick the front door at runtime, or split the SSO',
                        "journey into its own sso-gated test, so every variant drives the branch",
                        "it deploys.",
                    ],
                    offenders,
                )
            )

    def _by_role(self) -> dict[str, list[Scenario]]:
        by_role: dict[str, list[Scenario]] = defaultdict(list)
        for scenario in self.scenarios:
            by_role[scenario.file.split("/")[1]].append(scenario)
        return by_role

    def _readme_section(self, role: str) -> str | None:
        readme = PROJECT_ROOT / "roles" / role / ROLE_FILE_README
        return (
            ldap_coverage_section(read_text(str(readme))) if readme.is_file() else None
        )

    def _signs_personas_in(self, role: str) -> bool:
        role_dir = PROJECT_ROOT / "roles" / role
        services = role_dir / ROLE_FILE_META_SERVICES
        env = role_dir / _ENV_TEMPLATE_REL
        if not services.is_file() or not env.is_file():
            return False
        if not declares_ldap(load_yaml_any(str(services), default_if_missing={})):
            return False
        return bool(_PERSONA_CREDENTIAL_RE.search(read_text(str(env))))

    def test_ldap_capable_roles_ship_an_ldap_scenario(self) -> None:
        offenders: list[str] = []
        for role, scenarios in sorted(self._by_role().items()):
            if not self._signs_personas_in(role):
                continue
            if _ldap_gated(scenarios) or self._readme_section(role) is not None:
                continue
            offenders.append(role)
        if offenders:
            self.fail(
                f"Roles with ldap.enabled and an authenticated spec but no ldap-gated test ({len(offenders)}):\n\n"
                'Add a scenario gated by skipUnlessServiceEnabled("ldap") that drives the role\'s own\n'
                "LDAP-bind login, or state the exemption in a '## LDAP coverage' README section.\n\n"
                "Offenders:\n" + "\n".join(f"  roles/{r}" for r in offenders)
            )

    def test_admin_only_ldap_roles_flag_the_biber_follow_up(self) -> None:
        offenders: list[str] = []
        for role, scenarios in sorted(self._by_role().items()):
            if not lacks_biber_ldap_scenario(scenarios):
                continue
            section = self._readme_section(role)
            if section is None or not _BIBER_RE.search(section):
                offenders.append(role)
        if offenders:
            self.fail(
                f"Roles signing only the administrator in over LDAP ({len(offenders)}):\n\n"
                'Add a biber: scenario gated by skipUnlessServiceEnabled("ldap") or flag the\n'
                "biber follow-up in a '## LDAP coverage' README section.\n\n"
                "Offenders:\n" + "\n".join(f"  roles/{r}" for r in offenders)
            )

    def test_biber_only_ldap_roles_flag_the_administrator(self) -> None:
        offenders: list[str] = []
        for role, scenarios in sorted(self._by_role().items()):
            if ldap_persona_gap(scenarios) != "administrator":
                continue
            section = self._readme_section(role)
            if section is None or not _ADMINISTRATOR_RE.search(section):
                offenders.append(role)
        if offenders:
            self.fail(
                f"Roles signing only biber in over LDAP ({len(offenders)}):\n\n"
                'Add an administrator: scenario gated by skipUnlessServiceEnabled("ldap"), or\n'
                "state in a '## LDAP coverage' README section why the administrator never signs\n"
                "in over LDAP.\n\n"
                "Offenders:\n" + "\n".join(f"  roles/{r}" for r in offenders)
            )

    def test_ldap_sign_in_roles_name_their_personas(self) -> None:
        offenders = [
            role
            for role, scenarios in sorted(self._by_role().items())
            if ldap_persona_gap(scenarios) == "persona"
            and self._signs_personas_in(role)
            and self._readme_section(role) is None
        ]
        if offenders:
            self.fail(
                f"Roles whose ldap-gated tests sign no persona in ({len(offenders)}):\n\n"
                'Add administrator: and biber: scenarios gated by skipUnlessServiceEnabled("ldap")\n'
                "that drive the role's LDAP sign-in, or state in a '## LDAP coverage' README\n"
                "section why the role has none.\n\n"
                "Offenders:\n" + "\n".join(f"  roles/{r}" for r in offenders)
            )


if __name__ == "__main__":
    unittest.main()
