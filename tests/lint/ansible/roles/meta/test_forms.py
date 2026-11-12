"""Lint guard: every ``meta/forms.yml`` follows the managed-field schema.

Each form names its admin page ``path`` and its ``fields``; each field names
its inventory ``source``, its ``mode`` (``enforced`` or ``seeded``) and its
input ``selector``, optionally ``when``, ``label``, ``type``, ``enum``,
``validation`` and ``description``. A ``source`` or ``when`` resolves against
the role's ``applications.<role>`` defaults or a credential its
``meta/secrets.yml`` declares; a path under ``users`` must be exactly
``users.<key>.<attr>`` with an attr other than ``tokens``, and resolves
against the global user defaults. The schema lives in
``utils.roles.applications.forms``.

A role converges a form by reading its values through
``lookup('form_values', application_id, '<form>')`` with the form as a
literal, which returns exactly the declared fields whose ``when`` holds. So
the role converges every declared field and nothing else when each declared
form has such a lookup and each lookup names a declared form.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.applications import get_application_defaults
from utils.cache.files import read_text
from utils.cache.users import get_user_defaults
from utils.roles.applications import forms
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SECRETS

from . import load_role_meta, role_dirs

if TYPE_CHECKING:
    from pathlib import Path

FORM_VALUES = re.compile(
    r"""lookup\(\s*['"]form_values['"]\s*,\s*application_id\s*,\s*['"]([^'"]+)['"]"""
)
ROLE_SOURCE_SUFFIXES = frozenset({".yml", ".yaml", ".j2"})


def _credentials(role: Path) -> dict[str, Any]:
    secrets = load_role_meta(role / ROLE_FILE_META_SECRETS)
    credentials = secrets.get("credentials") if isinstance(secrets, dict) else None
    return credentials if isinstance(credentials, dict) else {}


def findings(
    roles: list[Path], defaults: dict[str, Any], users: dict[str, Any]
) -> list[str]:
    """Return every schema and resolution finding of the roles' forms files.

    Args:
        roles: role directories to check; a role without the file is skipped.
        defaults: ``applications`` defaults keyed by role.
        users: the global user defaults.
    """
    errors = []
    for role in roles:
        if not (role / ROLE_FILE_META_FORMS).is_file():
            continue
        data = load_role_meta(role / ROLE_FILE_META_FORMS)
        schema = forms.schema_errors(role.name, data)
        errors.extend(schema)
        if isinstance(data, dict):
            errors.extend(
                forms.source_errors(
                    role.name,
                    data,
                    defaults.get(role.name, {}),
                    users,
                    _credentials(role),
                )
            )
    return errors


def _converged_forms(role: Path) -> set[str]:
    return {
        form
        for path in sorted(role.rglob("*"))
        if path.suffix in ROLE_SOURCE_SUFFIXES and path.is_file()
        for form in FORM_VALUES.findall(read_text(str(path)))
    }


def convergence_findings(roles: list[Path]) -> list[str]:
    """Return every form a role declares but does not converge, or converges undeclared.

    Args:
        roles: role directories to check; a role without the file is skipped.
    """
    errors = []
    for role in roles:
        if not (role / ROLE_FILE_META_FORMS).is_file():
            continue
        data = load_role_meta(role / ROLE_FILE_META_FORMS)
        declared = set(data) if isinstance(data, dict) else set()
        converged = _converged_forms(role)
        errors.extend(
            f"{role.name}: {ROLE_FILE_META_FORMS} declares the form {form!r}, but no "
            f"lookup('form_values', application_id, '{form}') converges it"
            for form in sorted(declared - converged)
        )
        errors.extend(
            f"{role.name}: lookup('form_values', application_id, '{form}') converges "
            f"a form {ROLE_FILE_META_FORMS} does not declare"
            for form in sorted(converged - declared)
        )
    return errors


class TestForms(unittest.TestCase):
    def _roles(self) -> list[Path]:
        roles = [
            role for role in role_dirs() if (role / ROLE_FILE_META_FORMS).is_file()
        ]
        if not roles:
            self.skipTest(f"no role ships {ROLE_FILE_META_FORMS} yet")
        return roles

    def test_every_forms_file_follows_the_schema_and_resolves(self) -> None:
        self.assertEqual(
            [],
            findings(self._roles(), get_application_defaults(), get_user_defaults()),
        )

    def test_every_role_converges_exactly_the_forms_it_declares(self) -> None:
        self.assertEqual([], convergence_findings(self._roles()))


if __name__ == "__main__":
    unittest.main()
