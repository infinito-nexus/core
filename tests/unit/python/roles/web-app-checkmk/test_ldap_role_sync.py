import ast
import importlib.util
import re
import unittest
from string import Template

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_RBAC, ROLE_FILE_VARS_MAIN

APPLICATION_ID = "web-app-checkmk"
ROLE_DIR = PROJECT_ROOT / "roles" / APPLICATION_ID
CONFIGURE_SCRIPT = ROLE_DIR / "files/shell/configure-sso.sh"
MANAGER_OPS = ROLE_DIR / "tasks/01_manager_ops.yml"
ROLE_ENTRY_BUILDER = (
    PROJECT_ROOT / "roles/svc-db-openldap/filter_plugins/build_ldap_role_entries.py"
)
ROLE_VARS = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
DIRECTORY_RBAC = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/12_ldap.yml"))[
    "LDAP"
]["RBAC"]

USERS_OU = "ou=users,dc=example,dc=org"
ROLES_OU = "ou=roles,dc=example,dc=org"
USER_ID_ATTRIBUTE = "uid"
ADMINISTRATOR = "administrator"
ADMINISTRATOR_DN = f"{USER_ID_ATTRIBUTE}={ADMINISTRATOR},{USERS_OU}"
LDAP = {
    "DN": {"OU": {"USERS": USERS_OU, "ROLES": ROLES_OU}},
    "USER": {"ATTRIBUTES": {"ID": USER_ID_ATTRIBUTE}},
    "RBAC": DIRECTORY_RBAC,
}

CHECKMK_OPENLDAP_GROUP_FILTER = "(objectclass=groupOfUniqueNames)"
CHECKMK_OPENLDAP_GROUP_MEMBER = "uniquemember"
CHECKMK_DEFAULT_ROLES = ["user"]
CHECKMK_ADMIN_ROLE = "admin"

RENDERED_VARS = (
    "CHECKMK_LDAP_GROUP_FILTER",
    "CHECKMK_LDAP_GROUP_MEMBER_ATTR",
    "CHECKMK_LDAP_ROLE_ADMIN_DN",
    "CHECKMK_LDAP_ROLE_USER_DN",
    "CHECKMK_LDAP_ROLE_GUEST_DN",
)
UNRENDERED = "1"
TASK_ENV = re.compile(r"-e (\w+)=\{\{ (\w+) \| quote \}\}")
CONNECTIONS_HEREDOC = re.compile(r"<<EOF\n(user_connections = .*?)\nEOF\n", re.DOTALL)
OBJECT_CLASS_CLAUSE = re.compile(r"\(objectclass=([^()]+)\)", re.IGNORECASE)


class _ContainerEnv(dict):
    def __missing__(self, key: str) -> str:
        return UNRENDERED


def rendered_var(name: str) -> str:
    """Render one role variable against the fixture directory.

    Args:
        name: the variable name in the role's vars file.

    Returns:
        The rendered value.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return env.from_string(ROLE_VARS[name]).render(
        application_id=APPLICATION_ID, LDAP=LDAP
    )


def container_env() -> _ContainerEnv:
    """Return the environment the configure task hands the Checkmk container.

    Returns:
        The variables the task passes, rendered where the fixture allows it.
    """
    return _ContainerEnv(
        {
            env_name: rendered_var(var_name)
            for env_name, var_name in TASK_ENV.findall(read_text(str(MANAGER_OPS)))
            if var_name in RENDERED_VARS
        }
    )


def checkmk_connection() -> dict:
    """Return the LDAP connector configure-sso.sh writes into the site.

    Returns:
        The first entry of the written ``user_connections`` list.
    """
    heredoc = CONNECTIONS_HEREDOC.search(read_text(str(CONFIGURE_SCRIPT))).group(1)
    _, _, literal = Template(heredoc).substitute(container_env()).partition("=")
    return ast.literal_eval(literal.strip())[0]


def directory_role_groups() -> dict[str, dict]:
    """Return the role groups the directory holds for Checkmk.

    Returns:
        The role group entries keyed by their lower-cased DN.
    """
    spec = importlib.util.spec_from_file_location(
        "checkmk_build_ldap_role_entries", ROLE_ENTRY_BUILDER
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    applications = {
        APPLICATION_ID: {"rbac": load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_RBAC))}
    }
    users = {ADMINISTRATOR: {"roles": [ADMINISTRATOR]}}
    return {
        dn.lower(): {key.lower(): value for key, value in entry.items()}
        for dn, entry in module.build_ldap_role_entries(
            applications, users, LDAP
        ).items()
    }


def checkmk_group_members(
    connection: dict, groups: dict[str, dict], group_dn: str
) -> list[str] | None:
    """Mirror the base search the Checkmk groups_to_roles plug-in runs per group DN.

    Args:
        connection: the connector configure-sso.sh writes.
        groups: the role group entries keyed by lower-cased DN.
        group_dn: one group DN of the groups_to_roles mapping.

    Returns:
        The lower-cased member DNs, or None when the search finds no group.
    """
    entry = groups.get(group_dn.lower())
    if entry is None:
        return None
    group_filter = connection.get("group_filter", CHECKMK_OPENLDAP_GROUP_FILTER)
    wanted = {name.lower() for name in OBJECT_CLASS_CLAUSE.findall(group_filter)}
    if not wanted & {name.lower() for name in entry["objectclass"]}:
        return None
    member_attr = connection.get("group_member", CHECKMK_OPENLDAP_GROUP_MEMBER)
    return [member.lower() for member in entry.get(member_attr.lower(), [])]


def synced_roles(connection: dict, groups: dict[str, dict], user_dn: str) -> list[str]:
    """Mirror the roles the Checkmk groups_to_roles plug-in assigns to one user.

    Args:
        connection: the connector configure-sso.sh writes.
        groups: the role group entries keyed by lower-cased DN.
        user_dn: the DN of the synced user.

    Returns:
        The Checkmk role ids, falling back to the default user profile roles.
    """
    plugin = connection["active_plugins"]["groups_to_roles"]
    roles = [
        role_id
        for role_id, group_specs in plugin.items()
        if any(
            user_dn.lower() in (checkmk_group_members(connection, groups, dn) or [])
            for dn, _connection_id in group_specs
        )
    ]
    return roles or CHECKMK_DEFAULT_ROLES


class TestCheckmkLdapRoleSync(unittest.TestCase):
    def test_every_mapped_role_group_is_found_by_the_checkmk_group_search(self):
        connection = checkmk_connection()
        groups = directory_role_groups()
        for role_id, group_specs in connection["active_plugins"][
            "groups_to_roles"
        ].items():
            for group_dn, _connection_id in group_specs:
                with self.subTest(role=role_id, group=group_dn):
                    self.assertIsNotNone(
                        checkmk_group_members(connection, groups, group_dn)
                    )

    def test_the_administrator_group_member_syncs_into_the_checkmk_admin_role(self):
        self.assertEqual(
            synced_roles(
                checkmk_connection(), directory_role_groups(), ADMINISTRATOR_DN
            ),
            [CHECKMK_ADMIN_ROLE],
        )

    def test_a_checkmk_group_search_default_drops_the_administrator_to_default_roles(
        self,
    ):
        groups = directory_role_groups()
        for setting in ("group_filter", "group_member"):
            with self.subTest(setting=setting):
                connection = checkmk_connection()
                self.assertIn(setting, connection)
                del connection[setting]
                self.assertEqual(
                    synced_roles(connection, groups, ADMINISTRATOR_DN),
                    CHECKMK_DEFAULT_ROLES,
                )


if __name__ == "__main__":
    unittest.main()
