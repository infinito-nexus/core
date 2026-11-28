from __future__ import annotations

import ast
import itertools
import sys
import unittest
from pathlib import Path, PurePosixPath

import jinja2
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.get.service_script_path import get_service_script_path
from plugins.lookup.node_hosts import node_hosts
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

SERVICE = "sys-ctl-mtn-rbac-sync"
ROLE = PROJECT_ROOT / "roles" / SERVICE
CORE = ROLE / "tasks/00_core.yml"
SCRIPT = ROLE / "files/python/script.py"
RECONCILED = PurePosixPath(get_service_script_path(SERVICE, "py"))
MANAGER = "swarm-mgr-01"
NODES = (MANAGER, "swarm-wrk-01", "swarm-wrk-02")
PLAY = {
    "inventory_hostname": MANAGER,
    "groups": {"svc-swarm-manager": [MANAGER], "svc-swarm-node": list(NODES)},
    "RBAC_SYNC_SCRIPT_DIR": str(RECONCILED.parent),
}
COPY = ("ansible.builtin.copy", "copy")
FILE = ("ansible.builtin.file", "file")
INCLUDE_ROLE = ("ansible.builtin.include_role", "include_role")


def _lookup(name: str, *terms: str) -> str:
    if name != "path_absolute":
        raise AssertionError(f"unexpected lookup {name!r}")
    return str(PROJECT_ROOT.joinpath(*terms))


def _query(name: str) -> list[str]:
    if name != "node_hosts":
        raise AssertionError(f"unexpected query {name!r}")
    return node_hosts(PLAY)


def _render(expression: object, **scope: object) -> object:
    """Args:
        expression: a task value, rendered when it is a string.
        scope: the loop variable of the task.

    Returns:
        The native value of the expression in a swarm play on the manager.
    """
    if not isinstance(expression, str):
        return expression
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters["product"] = lambda left, *right: list(
        itertools.product(left, *right)
    )
    environment.filters["path_join"] = lambda parts: str(PurePosixPath(*parts))
    environment.globals.update(lookup=_lookup, query=_query)
    variables = {**load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN)), **PLAY, **scope}
    return environment.from_string(expression).render(**variables)


def _placements(modules: tuple[str, ...], key: str) -> list[tuple[str, dict]]:
    """Args:
        modules: the module names of the tasks to read.
        key: the argument that names the target path.

    Returns:
        ``(node, rendered src and key)`` per loop item of every such task of
        tasks/00_core.yml whose target lies in the script directory.
    """
    placements = []
    for task in load_yaml_any(str(CORE)):
        arguments = next((task[name] for name in modules if name in task), None)
        if not isinstance(arguments, dict):
            continue
        if "RBAC_SYNC_SCRIPT_DIR" not in str(arguments.get(key)):
            continue
        loop_var = (task.get("loop_control") or {}).get("loop_var", "item")
        for item in _render(task.get("loop", [None])):
            scope = {loop_var: item}
            node = _render(task.get("delegate_to", "{{ inventory_hostname }}"), **scope)
            rendered = {
                name: _render(arguments[name], **scope)
                for name in ("src", key)
                if name in arguments
            }
            placements.append((node, rendered))
    return placements


def _sys_service_copies_the_script() -> bool:
    for task in load_yaml_any(str(CORE)):
        include = next((task[name] for name in INCLUDE_ROLE if name in task), None)
        if isinstance(include, dict) and include.get("name") == "sys-service":
            copy_files = (task.get("vars") or {}).get("system_service_copy_files")
            return copy_files is not False
    raise AssertionError(f"{CORE} includes no sys-service unit")


def _directories() -> set[str]:
    nodes = {
        node
        for node, arguments in _placements(FILE, "path")
        if arguments["path"] == str(RECONCILED.parent)
    }
    return nodes | ({MANAGER} if _sys_service_copies_the_script() else set())


def _installed() -> dict[str, dict[str, str]]:
    """
    Returns:
        ``{node: {file name: source}}`` of every file the role places beside
        the script the deploy-time reconcile runs.
    """
    installed: dict[str, dict[str, str]] = {}
    for node, arguments in _placements(COPY, "dest"):
        dest = PurePosixPath(arguments["dest"])
        if dest.parent == RECONCILED.parent:
            installed.setdefault(node, {})[dest.name] = arguments["src"]
    if _sys_service_copies_the_script():
        installed.setdefault(MANAGER, {})[RECONCILED.name] = str(SCRIPT)
    return installed


def _local_imports(source: str) -> set[str]:
    """Args:
        source: path of a runner file.

    Returns:
        The top-level names it imports that the standard library does not provide.
    """
    names = set()
    for node in ast.walk(ast.parse(read_text(source))):
        if isinstance(node, ast.Import):
            names.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module.partition(".")[0])
    return names - sys.stdlib_module_names


def _needed(sources: dict[str, str]) -> set[str]:
    """Args:
        sources: ``{file name: source}`` of every runner file installed anywhere.

    Returns:
        The script and every module it imports, directly or through another one.
    """
    needed: set[str] = set()
    pending = [RECONCILED.name]
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        needed.add(name)
        source = str(SCRIPT) if name == RECONCILED.name else sources.get(name)
        if source:
            pending.extend(f"{module}.py" for module in _local_imports(source))
    return needed


class TestTheReconcileFindsItsRunnerOnTheNodeOfTheContainer(unittest.TestCase):
    def test_every_swarm_node_holds_the_script_directory(self):
        self.assertEqual(_directories(), set(NODES))

    def test_every_swarm_node_holds_the_script_and_every_module_it_imports(self):
        installed = _installed()
        sources = {
            name: source
            for files in installed.values()
            for name, source in files.items()
        }
        needed = _needed(sources)

        self.assertIn("ldap_mailbox.py", needed)
        for node in NODES:
            with self.subTest(node=node):
                self.assertEqual(needed - set(installed.get(node, {})), set())

    def test_every_node_runs_the_script_of_the_role(self):
        for node, files in _installed().items():
            with self.subTest(node=node):
                self.assertEqual(files[RECONCILED.name], str(SCRIPT))
                for source in files.values():
                    self.assertTrue(Path(source).is_file(), source)


if __name__ == "__main__":
    unittest.main()
