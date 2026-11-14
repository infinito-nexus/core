from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_RBAC, ROLE_FILE_README

from . import PROJECT_ROOT
from .test_biber_end_surface import assertions_in
from .test_biber_gates import role_persona_tests

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .test_biber_end_surface import Assertion
    from .test_biber_gates import PersonaTest

_UNMAPPED_ROLES = frozenset({"administrator", "mcp"})
_ABSENCE_MATCHERS = frozenset({"toBeFalsy", "toBeHidden", "toBeNull", "toBeUndefined"})
_EQUALITY_MATCHERS = frozenset({"toBe", "toEqual", "toStrictEqual"})
_ABSENT_VALUES = frozenset({"0", "false", "null", "undefined"})
_REFUSAL_RE = re.compile(r"\b40[134]\b")
_ADMIN_SCOPE_RE = re.compile(
    r"(?i)(?<![\w$-])(?:wp-)?admin(?:istration|istrator|s)?(?:_[a-z_]+)?(?![a-z$]|-bar\b)"
)
_SECTION_RE = re.compile(
    r"^##+[ \t]+Biber coverage[ \t]*$(.*?)(?=^#|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def application_roles(rbac: object) -> frozenset[str]:
    """Return the application roles an RBAC contract can map biber to.

    Args:
        rbac: the parsed ``meta/rbac.yml`` of a role.

    Returns:
        The declared role names without ``administrator`` and the ``mcp``
        machine role.
    """
    roles = rbac.get("roles") if isinstance(rbac, dict) else None
    if not isinstance(roles, dict):
        return frozenset()
    return frozenset(roles) - _UNMAPPED_ROLES


def _absence(assertion: Assertion) -> bool:
    return (
        assertion.negated
        or assertion.matcher in _ABSENCE_MATCHERS
        or (assertion.matcher == "toHaveCount" and assertion.expected == "0")
        or (
            assertion.matcher in _EQUALITY_MATCHERS
            and assertion.expected in _ABSENT_VALUES
        )
        or bool(_REFUSAL_RE.search(assertion.expected))
        or (
            assertion.matcher == "toContain"
            and bool(_REFUSAL_RE.search(assertion.subject))
        )
    )


def pins_the_role(items: Iterable[PersonaTest], roles: Iterable[str]) -> bool:
    """Tell whether a role's biber tests pin the application role biber maps to.

    Args:
        items: :func:`persona_tests_in` results of one role.
        roles: :func:`application_roles` of the role's RBAC contract.

    Returns:
        True when a ``biber:`` test reaches an assertion that names one of
        ``roles``, or an absence or refusal assertion whose subject, expected
        value or test title names an admin-scoped element, path or role.
    """
    names = "|".join(re.escape(role) for role in sorted(roles))
    role_re = re.compile(rf"(?i)(?<![\w$-])(?:{names})(?![\w$-])") if names else None
    for item in items:
        if not item.scenario.title.startswith("biber:"):
            continue
        admin_title = bool(_ADMIN_SCOPE_RE.search(item.scenario.title))
        for assertion in assertions_in(item.code):
            sides = (assertion.subject, assertion.expected)
            if role_re and any(role_re.search(side) for side in sides):
                return True
            if _absence(assertion) and (
                admin_title or any(_ADMIN_SCOPE_RE.search(side) for side in sides)
            ):
                return True
    return False


def biber_coverage_section(readme: str) -> str | None:
    """Return the body of a README's ``Biber coverage`` section, if it has one.

    Args:
        readme: the role README text.
    """
    match = _SECTION_RE.search(readme)
    return match.group(1) if match else None


def role_pin_gap(items: Iterable[PersonaTest], rbac: object, readme: str) -> bool:
    """Tell whether a role leaves a bare biber post-login check unflagged.

    Args:
        items: :func:`persona_tests_in` results of one role.
        rbac: the parsed ``meta/rbac.yml`` of the role.
        readme: the role README text.

    Returns:
        True when the RBAC contract offers biber an application role, the role
        has ``biber:`` tests, none of them pins that role and the README carries
        no non-empty ``Biber coverage`` section.
    """
    items = list(items)
    roles = application_roles(rbac)
    if not roles or not any(i.scenario.title.startswith("biber:") for i in items):
        return False
    if pins_the_role(items, roles):
        return False
    section = biber_coverage_section(readme)
    return not (section and section.strip())


class TestBiberRolePin(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.by_role = role_persona_tests()

    def test_persona_tests_were_found(self) -> None:
        self.assertTrue(self.by_role, "no Playwright test(...) found to scan")

    def test_bare_biber_checks_are_flagged_in_the_readme(self) -> None:
        offenders: list[str] = []
        for role, items in sorted(self.by_role.items()):
            role_dir = PROJECT_ROOT / "roles" / role
            rbac = load_yaml_any(
                str(role_dir / ROLE_FILE_META_RBAC), default_if_missing={}
            )
            readme = role_dir / ROLE_FILE_README
            text = read_text(str(readme)) if readme.is_file() else ""
            if role_pin_gap(items, rbac, text):
                offenders.append(role)
        if offenders:
            self.fail(
                f"roles whose biber: tests prove only a bare post-login page ({len(offenders)}):\n\n"
                "The role's meta/rbac.yml offers biber an application role, but no biber:\n"
                "assertion names that role or expects an admin-scoped element, path or\n"
                "response to be absent or refused. Pin the role in a biber: test, or flag the\n"
                "bare check in a README '## Biber coverage' section so a follow-up can tighten\n"
                "it.\n\nOffenders:\n"
                + "\n".join(f"  roles/{role}" for role in offenders)
            )


if __name__ == "__main__":
    unittest.main()
