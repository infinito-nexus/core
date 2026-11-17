"""Every node keeps its own torrc and Tor data directory.

Tor runs on every node (a global service in swarm), and swarm nodes mount
DIR_VAR_LIB from one NFS export. CI run 43777013536 (legal #1) kept both under
DIR_VAR_LIB: the worker's torrc render overwrote the stack host's, so the
hidden service vanished ("No more HSDir available to query"), and the tasks
then fought over one data directory ("another Tor process is running with the
same data directory"). Compose runs one node without NFS, where the same
paths are local anyway.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import PurePosixPath

import jinja2
from jinja2.nativetypes import NativeEnvironment

from plugins.lookup.node_hosts import node_hosts
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "svc-net-tor"
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
VOLUMES = load_yaml_any(str(ROLE / "meta" / "volumes.yml"))
CORE = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"), default_if_missing=[])
TORRC = (ROLE / "templates" / "torrc.j2").read_text(encoding="utf-8")
PATHS = load_yaml_any(str(PROJECT_ROOT / "group_vars" / "all" / "05_paths.yml"))
NFS_CLIENT = load_yaml_any(
    str(PROJECT_ROOT / "roles" / "svc-storage-nfs-client" / "tasks" / "main.yml"),
    default_if_missing=[],
)
SERVER_STAGE = load_yaml_any(
    str(PROJECT_ROOT / "tasks" / "stages" / "02_server.yml"), default_if_missing=[]
)
ENVIRONMENT = jinja2.Environment(
    undefined=jinja2.StrictUndefined,
    autoescape=jinja2.select_autoescape(default_for_string=False),
)
ENVIRONMENT.filters["path_join"] = lambda parts: str(PurePosixPath(*parts))


def _render(expression: str, **overrides: str) -> str:
    """Render a path expression the way Ansible resolves nested variables.

    Args:
        expression: a Jinja string over the DIR_VAR_LIB* paths and the role's
            path variables.
        overrides: variables that replace the group_vars or role values.

    Returns:
        The concrete path.
    """
    context = {
        "application_id": "svc-net-tor",
        **{key: value for key, value in PATHS.items() if key.startswith("DIR_VAR_LIB")},
        **{
            key: value
            for key, value in VARS.items()
            if key in ("TOR_DATA_DIR", "TOR_CONFIG_DIR", "TOR_TORRC_HOST")
        },
        **overrides,
    }
    rendered = expression
    for _ in range(6):
        if "{{" not in rendered:
            return rendered
        rendered = ENVIRONMENT.from_string(rendered).render(**context)
    raise AssertionError(f"unresolved: {expression}")


def _shared_root() -> PurePosixPath:
    """The path svc-storage-nfs-client mounts from the cluster's NFS export."""
    (path,) = {
        mount["path"]
        for mount in (task.get("ansible.posix.mount") or {} for task in NFS_CLIENT)
        if mount.get("src") == "{{ STORAGE_NFS_CLIENT_SRC }}"
        and mount.get("boot", True)
    }
    return PurePosixPath(_render(path))


def _shared(path: str) -> bool:
    return PurePosixPath(path).is_relative_to(_shared_root())


def _source(name: str, **overrides: str) -> str:
    return _render(VOLUMES[name]["source"], **overrides)


def _task(predicate) -> tuple[int, dict]:
    (found,) = [(index, task) for index, task in enumerate(CORE) if predicate(task)]
    return found


class TestNodeLocalState(unittest.TestCase):
    def test_negative_control_the_old_paths_count_as_shared(self) -> None:
        self.assertTrue(_shared("/var/lib/infinito/svc-net-tor/data"))
        self.assertTrue(_shared("/var/lib/infinito/svc-net-tor/config/torrc"))

    def test_the_container_binds_stay_off_the_shared_root(self) -> None:
        for name in ("tor_data", "tor_torrc"):
            for root in ("/var/lib/infinito", "/var/lib/infinito/"):
                with self.subTest(volume=name, DIR_VAR_LIB=root):
                    source = _source(name, DIR_VAR_LIB=root)
                    self.assertFalse(_shared(source), source)

    def test_negative_control_a_bare_suffix_lands_inside_the_mount(self) -> None:
        bare = _render("{{ DIR_VAR_LIB ~ '-node' }}", DIR_VAR_LIB="/var/lib/infinito/")
        self.assertTrue(_shared(bare), bare)

    def test_the_role_writes_the_paths_the_container_binds(self) -> None:
        self.assertEqual(_render(VARS["TOR_DATA_DIR"]), _source("tor_data"))
        self.assertEqual(_render(VARS["TOR_TORRC_HOST"]), _source("tor_torrc"))

    def test_each_node_creates_its_own_directories_and_torrc(self) -> None:
        for variable in ("TOR_CONFIG_DIR", "TOR_DATA_DIR"):
            (task,) = [
                task
                for task in CORE
                if (task.get("ansible.builtin.file") or {}).get("path")
                == f"{{{{ {variable} }}}}"
            ]
            with self.subTest(directory=variable):
                self.assertEqual(task["loop"], "{{ query('node_hosts') }}")
                self.assertEqual(task["delegate_to"], "{{ item }}")
        (render,) = [task for task in CORE if task.get("register") == "_tor_torrc"]
        self.assertEqual(
            render["ansible.builtin.template"]["dest"], "{{ TOR_TORRC_HOST }}"
        )
        self.assertEqual(render["loop"], "{{ query('node_hosts') }}")
        self.assertEqual(render["delegate_to"], "{{ tor_node }}")


class TestHiddenServiceKeys(unittest.TestCase):
    def test_the_keys_land_where_the_torrc_points_tor(self) -> None:
        (line,) = [
            line for line in TORRC.splitlines() if line.startswith("HiddenServiceDir ")
        ]
        in_container = PurePosixPath(line.split(" ", 1)[1].rstrip("/"))
        target = PurePosixPath(VOLUMES["tor_data"]["mounts"][0]["target"])
        on_host = PurePosixPath(_render(VARS["TOR_HS_DIR"]))
        self.assertEqual(
            on_host.relative_to(_render(VARS["TOR_DATA_DIR"])),
            in_container.relative_to(target),
        )

    def test_every_deploy_reinstalls_the_minted_keys(self) -> None:
        (task,) = [task for task in CORE if task.get("register") == "_tor_hs_keys"]
        copy = task["ansible.builtin.copy"]
        self.assertTrue(copy["force"])
        self.assertTrue(copy["src"].startswith("{{ [ TOR_HS_SRC_DIR,"))
        self.assertTrue(copy["dest"].startswith("{{ [ TOR_HS_DIR,"))
        self.assertNotIn("when", task)
        self.assertEqual(
            {item["name"] for item in task["loop"]},
            {"hostname", "hs_ed25519_public_key", "hs_ed25519_secret_key"},
        )


def _cleanup() -> tuple[int, dict]:
    return _task(
        lambda task: (
            (task.get("ansible.builtin.file") or {}).get("path")
            == "{{ TOR_LEGACY_DIR }}"
        )
    )


NODES = ["manager-1", "manager-2", "worker-1"]
STACK_HOST = "manager-2"
SWARM = "svc-swarm-node"
CLIENTS = "svc-storage-nfs-client"
SERVERS = "svc-storage-nfs-server"
LEGACY = {"exists": True, "isdir": True, "dev": 41, "inode": 7}
LIVE = {"exists": True, "isdir": True, "dev": 2049, "inode": 99}
RESOLVED = ["/var/lib/infinito/svc-net-tor", "/var/lib/infinito-node/svc-net-tor/data"]


def _filters() -> dict:
    spec = importlib.util.spec_from_file_location(
        "tor_legacy_filters", ROLE / "filter_plugins" / "tor_legacy.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


def _removable(resolved: list[str], legacy: dict, live: dict) -> bool:
    return _filters()["tor_legacy_removable"](resolved, legacy, live)


def _removers(groups: dict) -> list[str]:
    """Evaluate TOR_LEGACY_NODES for one inventory.

    Args:
        groups: the inventory groups; an NFS export backs DIR_VAR_LIB in each.

    Returns:
        The hosts the legacy tree is removed on, in removal order.
    """

    def query(name: str) -> list[str]:
        if name != "node_hosts":
            raise AssertionError(name)
        return node_hosts({"groups": groups, "inventory_hostname": STACK_HOST})

    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters.update(_filters())
    return environment.from_string(VARS["TOR_LEGACY_NODES"]).render(
        IS_SWARM_MODE=bool(groups.get(SWARM)),
        STACK_HOST=STACK_HOST,
        storage={"backend": "nfs"},
        groups=groups,
        query=query,
    )


class TestLegacyCleanup(unittest.TestCase):
    def test_it_removes_the_old_tree_on_the_shared_root(self) -> None:
        legacy = _render(VARS["TOR_LEGACY_DIR"])
        self.assertEqual(legacy, "/var/lib/infinito/svc-net-tor")
        self.assertTrue(_shared(legacy))
        for name in ("tor_data", "tor_torrc"):
            with self.subTest(volume=name):
                self.assertFalse(PurePosixPath(_source(name)).is_relative_to(legacy))
        _, task = _cleanup()
        self.assertEqual(task["ansible.builtin.file"]["state"], "absent")
        self.assertEqual(task["loop"], "{{ TOR_LEGACY_NODES }}")
        self.assertEqual(task["delegate_to"], "{{ item }}")
        self.assertIn("tor_legacy_removable", task["when"])

    def test_the_checks_run_on_the_same_nodes_before_the_removal(self) -> None:
        index, _ = _cleanup()
        resolve_at, resolve = _task(
            lambda task: task.get("register") == "_tor_legacy_resolved"
        )
        stat_at, stat = _task(lambda task: task.get("register") == "_tor_legacy_stat")
        self.assertLess(max(resolve_at, stat_at), index)
        self.assertEqual(
            resolve["ansible.builtin.command"]["argv"][-2:],
            ["{{ TOR_LEGACY_DIR }}", "{{ TOR_DATA_DIR }}"],
        )
        self.assertEqual(resolve["loop"], "{{ TOR_LEGACY_NODES }}")
        self.assertTrue(stat["loop"].startswith("{{ TOR_LEGACY_NODES | product("))

    def test_mounting_follows_the_server_stage_predicate(self) -> None:
        bootstrap = next(
            task for task in SERVER_STAGE if task.get("loop") == [SWARM, CLIENTS]
        )
        self.assertEqual(
            bootstrap["when"],
            [
                f"'{SWARM}' in group_names",
                f"swarm_bootstrap_role != '{CLIENTS}' or '{CLIENTS}' in group_names",
            ],
        )

    def test_an_external_server_with_clients_in_group_removes_once(self) -> None:
        self.assertEqual(_removers({SWARM: NODES, CLIENTS: NODES}), [STACK_HOST])

    def test_a_shared_tree_is_removed_once_by_a_mounting_host(self) -> None:
        for groups, removers in (
            ({SWARM: NODES, CLIENTS: NODES, SERVERS: ["manager-1"]}, [STACK_HOST]),
            (
                {SWARM: NODES, CLIENTS: ["worker-1", "manager-1"]},
                ["manager-1", STACK_HOST],
            ),
        ):
            with self.subTest(groups=groups):
                self.assertEqual(_removers(groups), removers)

    def test_negative_control_a_node_local_tree_is_removed_on_every_node(
        self,
    ) -> None:
        for groups, removers in (
            ({SWARM: NODES}, NODES),
            ({SWARM: NODES, SERVERS: ["manager-1"]}, NODES),
            ({}, [STACK_HOST]),
        ):
            with self.subTest(groups=groups):
                self.assertEqual(_removers(groups), removers)

    def test_negative_control_a_separate_legacy_tree_is_removable(self) -> None:
        self.assertTrue(_removable(RESOLVED, LEGACY, LIVE))
        self.assertTrue(_removable(RESOLVED, LEGACY, {"exists": False}))

    def test_it_skips_when_the_live_parent_is_the_same_inode(self) -> None:
        self.assertFalse(_removable(RESOLVED, LEGACY, dict(LIVE, dev=41, inode=7)))

    def test_it_skips_when_the_live_data_resolves_under_the_legacy_tree(
        self,
    ) -> None:
        for live_real in (
            "/var/lib/infinito/svc-net-tor",
            "/var/lib/infinito/svc-net-tor/x/svc-net-tor/data",
        ):
            with self.subTest(live=live_real):
                self.assertFalse(_removable([RESOLVED[0], live_real], LEGACY, LIVE))

    def test_it_skips_a_missing_legacy_tree(self) -> None:
        self.assertFalse(_removable(RESOLVED, {"exists": False}, LIVE))

    def test_it_runs_after_the_keys_and_the_new_stack_are_in_place(self) -> None:
        index, _ = _cleanup()
        keys, _ = _task(lambda task: task.get("register") == "_tor_hs_keys")
        stack, _ = _task(
            lambda task: (
                (task.get("include_role") or {}).get("name") == "sys-svc-compose"
            )
        )
        restart, _ = _task(lambda task: task.get("register") == "_tor_node_restart")
        self.assertGreater(index, max(keys, stack, restart))


if __name__ == "__main__":
    unittest.main()
