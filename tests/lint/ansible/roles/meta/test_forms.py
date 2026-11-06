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
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.applications import get_application_defaults
from utils.cache.users import get_user_defaults
from utils.roles.applications import forms
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SECRETS

from . import load_role_meta, role_dirs

if TYPE_CHECKING:
    from pathlib import Path


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


class TestForms(unittest.TestCase):
    def test_every_forms_file_follows_the_schema_and_resolves(self) -> None:
        roles = [
            role for role in role_dirs() if (role / ROLE_FILE_META_FORMS).is_file()
        ]
        if not roles:
            self.skipTest(f"no role ships {ROLE_FILE_META_FORMS} yet")
        self.assertEqual(
            [], findings(roles, get_application_defaults(), get_user_defaults())
        )


if __name__ == "__main__":
    unittest.main()
