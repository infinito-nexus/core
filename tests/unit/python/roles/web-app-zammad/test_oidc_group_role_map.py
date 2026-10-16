from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-zammad"
VARS = ROLE / ROLE_FILE_VARS_MAIN
NATIVE = ROLE / "files/ruby/apply/administrator.rb"
CORE = ROLE / "tasks/00_core.yml"
TEMPLATE = ROLE / "templates/zz/oidc/group_role_mapping.rb.j2"
GRANTS_KEY = "ZAMMAD_OIDC_ROLE_GRANTS"
MAP_KEY = "ZAMMAD_OIDC_GROUP_ROLE_MAP"
ADMIN_ROLE = "administrator"
INITIALIZER = "zz/oidc/group_role_mapping.rb.j2"
RECREATE = "container-recreate"


def native_administrator_roles() -> list[str]:
    """Read the Zammad roles the password path grants the platform administrator.

    Returns:
        The role names of ``Role.where(name: %w[...])`` in ``administrator.rb``.
    """
    match = re.search(r"Role\.where\(name:\s*%w\[([^\]]*)\]\)", read_text(str(NATIVE)))
    if not match:
        raise AssertionError(
            f"{NATIVE} no longer grants its roles through Role.where(name: %w[...])"
        )
    return match.group(1).split()


def role_vars() -> dict:
    return load_yaml_str(read_text(str(VARS)))


def staged_initializer() -> dict:
    """Find the staging entry that renders the OIDC group-to-role initializer.

    Returns:
        The ``role_templates`` entry whose ``src`` is the initializer template.
    """
    for task in load_yaml_str(read_text(str(CORE))):
        for entry in (task.get("vars") or {}).get("role_templates") or []:
            if entry.get("src") == INITIALIZER:
                return entry
    raise AssertionError(f"{CORE} no longer stages {INITIALIZER}")


class TestOidcGroupRoleMap(unittest.TestCase):
    def test_the_administrator_group_grants_what_the_password_path_grants(self) -> None:
        self.assertCountEqual(
            role_vars()[GRANTS_KEY][ADMIN_ROLE],
            native_administrator_roles(),
            "Zammad's Admin role carries no ticket permission: an administrator who "
            "arrives through the identity provider and is not also an Agent loses the "
            "dashboard, the overviews and every ticket, while the same account signing "
            f"in with its password keeps them, because {NATIVE} grants Admin and Agent "
            "together",
        )

    def test_every_granted_role_resolves_its_group_path_through_the_lookup(
        self,
    ) -> None:
        variables = role_vars()
        expression = variables[MAP_KEY]
        self.assertIsInstance(
            expression,
            str,
            f"{VARS}: {MAP_KEY} must stay one Jinja expression. Ansible renders a "
            "mapping's values and leaves its keys alone, so a group path written as a "
            "mapping key reaches the Zammad initializer as its own '{{ ... }}' source "
            "text, matches no group Keycloak sends, and every account that signs in "
            "through the identity provider falls back to Customer",
        )
        for role in variables[GRANTS_KEY]:
            self.assertIn(
                f"role='{role}'",
                expression,
                f"{VARS}: {MAP_KEY} grants nothing to the '{role}' group because it "
                f"never resolves its path, while {GRANTS_KEY} declares roles for it",
            )

    def test_restaging_the_initializer_recreates_the_rails_tasks(self) -> None:
        self.assertIn(
            RECREATE,
            staged_initializer().get("notify") or [],
            f"{CORE}: staging {INITIALIZER} must notify '{RECREATE}'. A Rails "
            "initializer binds its patches at boot, and the default 'compose-up' "
            "redeploys a swarm service only when its spec changed, which a "
            "bind-mounted file is not, so an existing stack would keep granting the "
            "roles of the initializer it booted with",
        )

    def test_a_patch_target_that_disappeared_stops_the_boot(self) -> None:
        source = read_text(str(TEMPLATE))
        reason = (
            "Zammad 7.1.2 defines only User.create_from_hash! (app/models/user.rb:312), "
            "so the earlier guard 'next unless User.respond_to?(...)' matched nothing, "
            "installed no patch at all and left every account that signed in through the "
            "identity provider on its signup role. A patch target that disappears must "
            "stop the boot, which the deploy's convergence wait turns into a failed CI "
            "deploy, instead of silently granting no role"
        )
        self.assertIn("Authorization.respond_to?(method_name)", source, reason)
        self.assertIn("raise ", source, reason)
        self.assertNotIn("User.respond_to?", source, reason)


if __name__ == "__main__":
    unittest.main()
