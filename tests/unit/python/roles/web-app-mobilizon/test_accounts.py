"""Mobilizon provisions the atmo bridge its own account exactly while the bridge runs."""

from __future__ import annotations

import re
import unittest

from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, StrictUndefined

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.users import get_user_defaults
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_ACCOUNT,
    ROLE_FILE_META_USERS,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-mobilizon"
ACCOUNT_SCRIPT = ROLE / "files" / "elixir" / "account.exs"
ACCOUNT_TASKS = ROLE / "tasks" / "01_design.yml"
ACCOUNT_POLICY = ROLE / ROLE_FILE_META_ACCOUNT
BRIDGE_ACCOUNT = "web-app-mobilizon-atmo-bridge"
PLATFORM_ADMIN = "platform_administrator"


class _AtmoAbsentError(AssertionError):
    pass


def accounts(group_names: list[str], bridge_flag: bool) -> list[tuple[str, str]]:
    """Resolve ``MOBILIZON_ACCOUNTS`` from the role's own vars.

    Args:
        group_names: the roles of the inventory.
        bridge_flag: what ``services.bridge.enabled`` of web-app-atmo renders to.

    Returns:
        ``(user key, Mobilizon role)`` per account the task provisions.
    """
    variables = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))

    def lookup(name, *terms):
        if name == "users":
            return {"key": terms[0]}
        if name == "config" and terms[0] == "web-app-atmo":
            if "web-app-atmo" not in group_names:
                raise _AtmoAbsentError("read web-app-atmo config without the role")
            return str(bridge_flag)
        raise AssertionError(f"unexpected lookup {name}{terms}")

    environment = Environment(  # noqa: S701 - compiles expressions of a vars file, renders no markup
        undefined=StrictUndefined
    )
    environment.globals["lookup"] = lookup
    environment.filters["bool"] = to_bool

    def expression(name: str):
        return environment.compile_expression(variables[name].strip()[2:-2])

    enabled = expression("MOBILIZON_ATMO_BRIDGE_ENABLED")(group_names=group_names)
    resolved = expression("MOBILIZON_ACCOUNTS")(MOBILIZON_ATMO_BRIDGE_ENABLED=enabled)
    return [(entry["user"]["key"], entry["role"]) for entry in resolved]


class TestBridgeAccountProvisioning(unittest.TestCase):
    ADMIN = (PLATFORM_ADMIN, "administrator")
    BRIDGE = (BRIDGE_ACCOUNT, "user")

    def test_without_atmo_only_the_administrator_is_provisioned(self):
        self.assertEqual(accounts(["web-app-mobilizon"], True), [self.ADMIN])

    def test_with_the_bridge_on_its_account_is_provisioned_as_a_plain_user(self):
        groups = ["web-app-mobilizon", "web-app-atmo", "web-app-bluesky"]
        self.assertEqual(accounts(groups, True), [self.ADMIN, self.BRIDGE])

    def test_with_the_bridge_off_its_account_is_not_provisioned(self):
        groups = ["web-app-mobilizon", "web-app-atmo"]
        self.assertEqual(accounts(groups, False), [self.ADMIN])

    def test_the_task_provisions_every_account_with_its_own_role(self):
        task = next(
            entry
            for entry in load_yaml_str(read_text(str(ACCOUNT_TASKS)))
            if "account.exs" in str(entry.get("ansible.builtin.command", {}))
        )
        self.assertEqual(task["loop"], "{{ MOBILIZON_ACCOUNTS }}")
        self.assertEqual(task["loop_control"]["label"], "{{ item.user.username }}")
        stdin = task["ansible.builtin.command"]["stdin"]
        for field in ("item.user.email", "item.user.password", "item.role"):
            with self.subTest(field=field):
                self.assertIn(field, stdin)

    def test_the_script_applies_the_role_it_is_given(self):  # nocheck: test.text-presence -- asserts Elixir that runs only inside the app container; no Elixir runner yet  # fmt: skip
        script = read_text(str(ACCOUNT_SCRIPT))
        self.assertIn('"role" => role', script)
        self.assertNotIn(":administrator", script)
        self.assertEqual(len(re.findall(r"\brole: role\b", script)), 2)


class TestBridgeAccountDeclaration(unittest.TestCase):
    def setUp(self):
        self.declared = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_USERS)))[
            BRIDGE_ACCOUNT
        ]
        self.users = get_user_defaults()

    def test_the_account_stays_out_of_ldap_keycloak_and_mail(self):
        self.assertEqual(self.declared["accounts"], [])

    def test_the_profile_name_is_a_valid_mobilizon_username(self):
        pattern = load_yaml_str(read_text(str(ACCOUNT_POLICY)))["account_policy"][
            "username_pattern"
        ]
        self.assertRegex(self.users[BRIDGE_ACCOUNT]["username"], rf"^{pattern}$")
        self.assertNotRegex(BRIDGE_ACCOUNT, rf"^{pattern}$")

    def test_the_account_shares_no_identity_with_the_administrator(self):
        bridge, admin = self.users[BRIDGE_ACCOUNT], self.users[PLATFORM_ADMIN]
        self.assertNotEqual(bridge["username"], admin["username"])
        self.assertNotEqual(bridge["email"], admin["email"])


if __name__ == "__main__":
    unittest.main()
