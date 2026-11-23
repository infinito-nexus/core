from __future__ import annotations

import socket
import tempfile
import types
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

RBAC_VARS = PROJECT_ROOT / "roles/sys-ctl-mtn-rbac-sync" / ROLE_FILE_VARS_MAIN
RBAC_CORE = PROJECT_ROOT / "roles/sys-ctl-mtn-rbac-sync/tasks/00_core.yml"
OPENLDAP_VARS = PROJECT_ROOT / "roles/svc-db-openldap" / ROLE_FILE_VARS_MAIN
LDAP_VARS = PROJECT_ROOT / "group_vars/all/12_ldap.yml"
SWARM_VARS = PROJECT_ROOT / "group_vars/all/18_swarm.yml"
CLIENT = PROJECT_ROOT / "roles/svc-db-openldap/files/python/ldap/client.py"
VOLUMES_LOOKUP = "lookup('container', 'svc-db-openldap', 'directories.volumes')"
SOCKET_URI = "ldapi://%2Fsocket"
MAINTENANCE_FILE = "/run/infinito/maintenance/backup.json"
RBAC_SYNC_DIR = "/shared/rbac-sync"
SCRIPT_EXEC = "python3 /scripts/script.py"
MANAGER = "swarm-mgr-01"
WORKER = "swarm-wrk-01"
CLUSTER = {
    "svc-swarm-manager": [MANAGER],
    "svc-swarm-node": [MANAGER, WORKER],
    "svc-db-openldap": [MANAGER],
    "web-app-nextcloud": [MANAGER, WORKER],
}


def _render(expression: object, variables: dict) -> object:
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(expression))


def _socket_uri(volumes: str) -> str:
    """Render the real ``LDAP.SERVER.SOCKET_URI`` for a volumes directory.

    Args:
      volumes: the directory ``directories.volumes`` of svc-db-openldap resolves to.
    """
    expression = load_yaml_any(str(LDAP_VARS))["LDAP"]["SERVER"]["SOCKET_URI"]
    if VOLUMES_LOOKUP not in expression:
        raise AssertionError(f"{LDAP_VARS} SOCKET_URI no longer reads {VOLUMES_LOOKUP}")
    return _render(expression.replace(VOLUMES_LOOKUP, "volumes"), {"volumes": volumes})


def _trusted(value: object) -> object:
    if isinstance(value, dict):
        return {key: _trusted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_trusted(item) for item in value]
    return _trust_as_template(value)


def _sync(
    key: str,
    host: str,
    *,
    swarm: bool = True,
    socket_uri: str = SOCKET_URI,
) -> object:
    """Render one key of the real ``vars/main.yml`` of the sync for one host of ``CLUSTER``.

    Args:
      key: the variable to render.
      host: the inventory_hostname the role runs on.
      swarm: the value IS_SWARM_MODE and the negation IS_COMPOSE_MODE render to.
      socket_uri: the value LDAP.SERVER.SOCKET_URI renders to.
    """
    return _sync_template("{{ " + key + " }}", host, swarm=swarm, socket_uri=socket_uri)


def _sync_template(
    template: str,
    host: str,
    *,
    swarm: bool = True,
    socket_uri: str = SOCKET_URI,
) -> object:
    """Render a template against the real ``vars/main.yml`` of the sync for one host of ``CLUSTER``.

    Args:
      template: the Jinja template to render, such as a task argument of the role.
      host: the inventory_hostname the role runs on.
      swarm: the value IS_SWARM_MODE and the negation IS_COMPOSE_MODE render to.
      socket_uri: the value LDAP.SERVER.SOCKET_URI renders to.
    """
    rbac = load_yaml_str(read_text(str(RBAC_VARS)))
    variables = {
        "inventory_hostname": host,
        "groups": CLUSTER,
        "group_names": [name for name, hosts in CLUSTER.items() if host in hosts],
        "IS_SWARM_MODE": swarm,
        "IS_COMPOSE_MODE": not swarm,
        "STACK_HOST": _trust_as_template(load_yaml_any(str(SWARM_VARS))["STACK_HOST"]),
        "BIN_CONTAINER": "/usr/bin/container",
        "DIR_RBAC_SYNC": RBAC_SYNC_DIR,
        "system_service_script_exec": SCRIPT_EXEC,
        "FILE_MAINTENANCE_BACKUP": MAINTENANCE_FILE,
        "LDAP": {
            "SERVER": {"SOCKET_URI": socket_uri},
            "DN": {"OU": {"USERS": "ou=users", "ROLES": "ou=roles"}},
            "USER": {
                "ATTRIBUTES": {
                    "ID": "uid",
                    "MAIL": "mail",
                    "FULLNAME": "cn",
                    "MEMBER_OF": "memberOf",
                    "UUID": "entryUUID",
                }
            },
        },
    }
    variables.update(
        {name: _trusted(value) for name, value in rbac.items() if name.isupper()}
    )
    return _render(template, variables)


def _unit_exec_start() -> str:
    for task in load_yaml_any(str(RBAC_CORE)):
        include = task.get("include_role") or task.get("ansible.builtin.include_role")
        if isinstance(include, dict) and include.get("name") == "sys-service":
            return task["vars"]["system_service_tpl_exec_start"]
    raise AssertionError(f"{RBAC_CORE} includes no sys-service unit")


def _client() -> types.ModuleType:
    module = types.ModuleType("ldap_client")
    exec(compile(read_text(str(CLIENT)), str(CLIENT), "exec"), module.__dict__)
    return module


class TestTheSyncDialsTheSocketOpenldapProvisionsThrough(unittest.TestCase):
    def test_every_mode_dials_the_socket_uri(self):
        for swarm in (True, False):
            with self.subTest(swarm=swarm):
                self.assertEqual(
                    _sync("RBAC_SYNC_LDAP_URI", MANAGER, swarm=swarm), SOCKET_URI
                )

    def test_the_sync_and_openldap_read_one_uri_key(self):
        openldap = load_yaml_any(str(OPENLDAP_VARS))["OPENLDAP_SERVER_URI"]
        rbac = load_yaml_any(str(RBAC_VARS))["RBAC_SYNC_LDAP_URI"]

        self.assertEqual(rbac, openldap)

    def test_the_uri_reaches_the_socket_svc_db_openldap_mounts(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name, "run", "ldapi")
        path.parent.mkdir()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(str(path))
        server.listen(1)
        uri = _sync(
            "RBAC_SYNC_LDAP_URI", MANAGER, socket_uri=_socket_uri(directory.name + "/")
        )

        connection = _client().Connection(uri)
        self.addCleanup(connection.close)

        self.assertEqual(connection.socket.getpeername(), str(path))


class TestEveryNodeOfAClusterWithADirectoryKnowsIt(unittest.TestCase):
    def test_a_worker_writes_the_directory_block_but_runs_no_timer(self):
        self.assertIs(True, _sync("RBAC_SYNC_LDAP_ENABLED", WORKER))
        self.assertIs(False, _sync("RBAC_SYNC_TIMER_ENABLED", WORKER))

    def test_the_written_config_of_every_mode_carries_the_socket_uri(self):
        for swarm in (True, False):
            with self.subTest(swarm=swarm):
                config = _sync("RBAC_SYNC_CONFIG", MANAGER, swarm=swarm)

                self.assertEqual(config["ldap"]["uri"], SOCKET_URI)

    def test_every_node_writes_the_same_config_to_the_shared_directory(self):
        worker = _sync("RBAC_SYNC_CONFIG", WORKER)
        manager = _sync("RBAC_SYNC_CONFIG", MANAGER)

        self.assertIsNotNone(worker["ldap"])
        self.assertEqual(worker["maintenance_file"], MAINTENANCE_FILE)
        self.assertEqual(worker, manager)

    def test_the_unit_of_each_node_tells_where_slapd_belongs(self):
        self.assertEqual(
            [_sync_template(_unit_exec_start(), host) for host in (MANAGER, WORKER)],
            [
                f"{SCRIPT_EXEC} --directory {RBAC_SYNC_DIR}",
                f"{SCRIPT_EXEC} --directory {RBAC_SYNC_DIR} --remote-directory",
            ],
        )


if __name__ == "__main__":
    unittest.main()
