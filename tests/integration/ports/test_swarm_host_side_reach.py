"""Integration test: host-side provisioning reaches no published local port in swarm.

Swarm publishes no ``ports.local`` port of a term bound to ``DOCKER_BIND_HOST``
(074), so a host-side task that dials one there reaches nothing. For the
central Postgres and MariaDB init, the RBAC directory searches and the Synapse
RBAC hook, the task that dials the local port runs only in compose, and in
swarm a sibling reaches the app inside its container or, for OpenLDAP, through
the ldapi socket the role binds into its volumes directory. Each check
evaluates the real ``when:`` and value expressions in both modes.
"""

from __future__ import annotations

import unittest
from itertools import product

from ansible.plugins.filter.core import path_join
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.rbac.members import rbac_ldap_members
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_ENV = NativeEnvironment()
_ENV.filters.update(
    {
        "bool": bool,
        "path_join": path_join,
        "rbac_ldap_members": rbac_ldap_members,
    }
)
MODES = {
    "compose": {"IS_COMPOSE_MODE": True, "IS_SWARM_MODE": False},
    "swarm": {"IS_COMPOSE_MODE": False, "IS_SWARM_MODE": True},
}
LDAP_VARS = {
    "LDAP": {
        "USER": {
            "ATTRIBUTES": {
                "ID": "uid",
                "MAIL": "mail",
                "FULLNAME": "cn",
                "UUID": "entryUUID",
            }
        }
    },
    "group_names": ["svc-db-openldap"],
}


def _value(text: object, variables: dict) -> object:
    return _ENV.from_string(str(text)).render(**variables)


def _runs(task: dict, variables: dict) -> bool:
    conditions = task.get("when", [])
    conditions = conditions if isinstance(conditions, list) else [conditions]
    return all(
        _value("{{ " + str(condition) + " }}", variables) for condition in conditions
    )


def _tasks(rel: str) -> list[dict]:
    return load_yaml_any(str(PROJECT_ROOT / rel))


def _including(tasks: list[dict], target: str) -> dict:
    return next(
        task for task in tasks if task.get("ansible.builtin.include_tasks") == target
    )


def _with(tasks: list[dict], key: str, needle: str = "") -> list[dict]:
    found = []
    for task in tasks:
        body = [task, *task.get("block", [])]
        if any(key in item and needle in str(item[key]) for item in body):
            found.append(task)
    return found


class TestPostgresInit(unittest.TestCase):
    def test_swarm_provisions_inside_the_container_even_when_exposed(self) -> None:
        tasks = _tasks("roles/svc-db-postgres/tasks/01_init.yml")
        published = _including(tasks, "01_init/published.yml")
        container = _including(tasks, "01_init/container.yml")
        for mode, exposed in product(MODES, (True, False)):
            variables = {**MODES[mode], "POSTGRES_EXPOSE_LOCAL": exposed}
            through_port = mode == "compose" and exposed
            with self.subTest(mode=mode, exposed=exposed):
                self.assertEqual(through_port, _runs(published, variables))
                self.assertEqual(not through_port, _runs(container, variables))


class TestMariadbInit(unittest.TestCase):
    def test_swarm_never_dials_the_local_port(self) -> None:
        waits = _with(
            _tasks("roles/svc-db-mariadb/tasks/00_core.yml"),
            "ansible.mariadb.mariadb_db",
        )
        init = _tasks("roles/svc-db-mariadb/tasks/01_init.yml")
        host = _with(init, "ansible.mariadb.mariadb_db")
        cli = _with(init, "ansible.builtin.shell", "container exec")
        self.assertEqual((1, 1, 1), (len(waits), len(host), len(cli)))
        for mode, exposed in product(MODES, (True, False)):
            variables = {**MODES[mode], "MARIADB_EXPOSE_LOCAL": exposed}
            through_port = mode == "compose" and exposed
            with self.subTest(mode=mode, exposed=exposed):
                self.assertEqual(through_port, _runs(waits[0], variables))
                self.assertEqual(through_port, _runs(host[0], variables))
                self.assertEqual(not through_port, _runs(cli[0], variables))


class TestRbacDirectorySearch(unittest.TestCase):
    def _check(self, rel: str, output: str) -> None:
        tasks = _tasks(rel)
        searches = _with(tasks, "community.general.ldap_search")
        assign = _with(tasks, "ansible.builtin.set_fact", output)[0]
        alice = {"uid": "alice", "mail": "alice@example.org", "cn": "Alice"}
        for mode in MODES:
            variables = {**MODES[mode], **LDAP_VARS}
            ran = [task for task in searches if _runs(task, variables)]
            with self.subTest(file=rel, mode=mode):
                self.assertEqual(1, len(ran))
                uri = ran[0]["community.general.ldap_search"]["server_uri"]
                self.assertEqual(mode == "compose", "ports.local." in uri)
                self.assertEqual(mode == "swarm", "LDAP.SERVER.SOCKET_URI" in uri)
                registers = {
                    task["register"]: {"results": [alice]}
                    if task is ran[0]
                    else {"skipped": True}
                    for task in searches
                }
                members = _value(
                    assign["ansible.builtin.set_fact"][output],
                    {**variables, **registers},
                )
                self.assertEqual(["alice"], [m["username"] for m in members])

    def test_members_search_the_socket_in_swarm(self) -> None:
        self._check("tasks/utils/rbac/members.yml", "rbac_members")

    def test_users_search_the_socket_in_swarm(self) -> None:
        self._check("tasks/utils/rbac/users.yml", "rbac_users")

    def test_the_socket_uri_is_the_socket_openldap_binds(self) -> None:
        server = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/12_ldap.yml"))
        role = load_yaml_any(
            str(PROJECT_ROOT / "roles/svc-db-openldap" / ROLE_FILE_VARS_MAIN)
        )
        variables = {
            "application_id": "svc-db-openldap",
            "lookup": lambda *_: "/opt/compose/openldap/volumes/",
        }
        socket = path_join(
            [_value(role["OPENLDAP_SOCKET_PATH_HOST"], variables), "ldapi"]
        )
        self.assertEqual("{{ LDAP.SERVER.SOCKET_URI }}", role["OPENLDAP_SERVER_URI"])
        self.assertEqual(
            "ldapi://" + socket.replace("/", "%2F"),
            _value(server["LDAP"]["SERVER"]["SOCKET_URI"], variables),
        )


class TestMatrixRbacHook(unittest.TestCase):
    def test_the_hook_runs_inside_synapse_in_swarm(self) -> None:
        task = _tasks("roles/web-app-matrix/tasks/01_rbac_administrator.yml")[0]
        hook = task["vars"]
        for flavor_pin, cluster in product(("", "compose"), ("compose", "swarm")):
            variables = {"compose_mode_force": flavor_pin, "DEPLOYMENT_MODE": cluster}
            variables["rbac_sync_mode"] = _value(hook["rbac_sync_mode"], variables)
            variables.update(
                MATRIX_SYNAPSE_LOOPBACK_URL="loopback",
                MATRIX_SYNAPSE_CONTAINER_URL="container",
            )
            inside = variables["rbac_sync_mode"] == "swarm"
            with self.subTest(flavor_pin=flavor_pin, cluster=cluster):
                self.assertEqual(
                    "container" if inside else "host",
                    _value(hook["rbac_sync_kind"], variables),
                )
                self.assertEqual(
                    ["python3", "-"] if inside else [],
                    _value(hook["rbac_sync_argv"], variables),
                )
                self.assertEqual(
                    "container" if inside else "loopback",
                    _value(hook["rbac_sync_env"]["MATRIX_SYNAPSE_URL"], variables),
                )

    def test_the_container_url_is_synapse_s_internal_port(self) -> None:
        matrix = load_yaml_any(
            str(PROJECT_ROOT / "roles/web-app-matrix" / ROLE_FILE_VARS_MAIN)
        )
        self.assertIn(
            "MATRIX_SYNAPSE_CONTAINER_PORT", matrix["MATRIX_SYNAPSE_CONTAINER_URL"]
        )
        self.assertIn("ports.internal.http", matrix["MATRIX_SYNAPSE_CONTAINER_PORT"])


if __name__ == "__main__":
    unittest.main()
