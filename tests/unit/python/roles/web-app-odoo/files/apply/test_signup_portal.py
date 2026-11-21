from __future__ import annotations

import io
import runpy
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock

from utils.cache.files import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-odoo/files/python/apply/signup_portal.py"
MARKER = "infinito.rbac.signup_portal_reconciled"
PUBLIC_USER_ID = 4


class Records:
    """Recordset stand-in: iterating yields one-record sets, attributes read the single record."""

    def __init__(self, items):
        self.items = list(items)

    def __iter__(self):
        return (Records([item]) for item in self.items)

    def __bool__(self):
        return bool(self.items)

    def __or__(self, other):
        return Records(
            self.items + [item for item in other.items if item not in self.items]
        )

    def __eq__(self, other):
        return isinstance(other, Records) and self.items == other.items

    def __getattr__(self, name):
        (item,) = self.items
        return item[name]

    def filtered(self, predicate):
        return Records([item for item in self.items if predicate(Records([item]))])


class Users(Records):
    """The res.users model: an empty recordset whose search answers ``found``."""

    def __init__(self, found):
        super().__init__([])
        self.found = found
        self.domains = []

    def sudo(self):
        return self

    def with_context(self, **_context):
        return self

    def search(self, domain):
        self.domains.append(domain)
        return Records(self.found)


def user(login: str) -> dict[str, str]:
    """Build one res.users row.

    Args:
        login: Odoo login of the user.

    Returns:
        The row a ``Records`` item holds.
    """
    return {"login": login}


class TestSignupPortal(unittest.TestCase):
    def _run(self, found: list[str], protected: tuple[str, ...], marker: bool):
        groups = {
            "base.group_portal": Records(["portal"]),
            "base.group_user": Records(["internal"]),
            "base.public_user": Records([{"id": PUBLIC_USER_ID}]),
        }
        parameters = MagicMock(name="ir.config_parameter")
        parameters.sudo.return_value = parameters
        parameters.get_param.side_effect = lambda key: (
            "1" if marker and key == MARKER else False
        )
        rbac = MagicMock(name="infinito.rbac")
        rbac._is_protected.side_effect = lambda login: login in protected
        users = Users([user(login) for login in found])
        env = MagicMock(name="env")
        env.__getitem__.side_effect = {
            "ir.config_parameter": parameters,
            "res.users": users,
            "infinito.rbac": rbac,
        }.__getitem__
        env.ref.side_effect = groups.__getitem__

        buf = io.StringIO()
        with redirect_stdout(buf):
            runpy.run_path(
                str(SCRIPT_PATH), init_globals={"env": env}, run_name="__main__"
            )
        return buf.getvalue().split(), users, parameters, rbac, env

    def test_an_internal_self_signup_moves_to_the_portal(self) -> None:
        lines, _users, parameters, rbac, env = self._run(["biber"], (), False)

        rbac._apply.assert_called_once_with(
            Records([user("biber")]),
            Records(["portal", "internal"]),
            Records(["portal"]),
        )
        parameters.set_param.assert_called_once_with(MARKER, "1")
        env.cr.commit.assert_called_once_with()
        self.assertEqual(lines, ["portal=biber", "SIGNUP_PORTAL_CHANGED"])

    def test_only_internal_users_the_public_user_created_without_an_identity_provider_link_are_selected(
        self,
    ) -> None:
        _lines, users, _parameters, _rbac, _env = self._run([], (), False)

        self.assertEqual(
            users.domains,
            [
                [
                    ("create_uid", "=", PUBLIC_USER_ID),
                    ("share", "=", False),
                    ("oauth_uid", "=", False),
                ]
            ],
        )

    def test_the_protected_login_stays_internal(self) -> None:
        lines, _users, parameters, rbac, _env = self._run(
            ["administrator"], ("administrator",), False
        )

        rbac._apply.assert_not_called()
        parameters.set_param.assert_called_once_with(MARKER, "1")
        self.assertEqual(lines, ["SIGNUP_PORTAL_UNCHANGED"])

    def test_a_set_marker_leaves_every_user_alone(self) -> None:
        lines, users, parameters, rbac, env = self._run(["biber"], (), True)

        self.assertEqual(users.domains, [])
        rbac._apply.assert_not_called()
        parameters.set_param.assert_not_called()
        env.cr.commit.assert_not_called()
        self.assertEqual(lines, ["SIGNUP_PORTAL_UNCHANGED"])


if __name__ == "__main__":
    unittest.main()
