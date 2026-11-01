"""The guard that stops a deploy before Stalwart 1.x opens a store from before 1.0.

The marker a finished 1.x deploy leaves on the stack host passes the guard
without touching the store. Without the marker the guard reads every store
that exists, stops when a dedicated database is not running, and lets a fresh
install through.
"""

from __future__ import annotations

import base64
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-stalwart"
GUARD = ROLE / "tasks" / "store_guard.yml"
MANAGER_OPS = ROLE / "tasks" / "manager_ops.yml"
VARS = ROLE / ROLE_FILE_VARS_MAIN

PASS = "pass"
ENGINE_DOWN = "Ensure the dedicated store database runs"
PRE_1_0 = "Ensure Stalwart opens no store from before 1.0"

SKIPPED = {"skipped": True, "changed": False}
NO_MARKER = {
    "stalwart_store_marker_file": {"changed": False, "stat": {"exists": False}}
}


def _render(template: str, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _holds(condition: str, facts: dict) -> bool:
    return _render("{{ (" + condition + ") | bool }}", **facts)


def _module(task: dict, name: str) -> dict | None:
    return task.get(f"ansible.builtin.{name}") or task.get(name)


def _layout_version() -> str:
    return load_yaml_any(str(VARS), default_if_missing={})[
        "STALWART_STORE_LAYOUT_VERSION"
    ]


def _written_marker() -> str:
    tasks = load_yaml_any(str(MANAGER_OPS), default_if_missing=[])
    copy = next(
        t["stack_host_copy"]
        for t in tasks
        if t.get("stack_host_copy", {}).get("dest")
        == "{{ STALWART_STORE_MARKER_FILE }}"
    )
    return _render(copy["content"], STALWART_STORE_LAYOUT_VERSION=_layout_version())


def _guard(results: dict[str, dict], *, shared: bool) -> str:
    """Walk store_guard.yml in task order, the way Ansible runs it.

    Args:
      results: the result of every task that runs, keyed by its register name;
        a task that runs without an entry fails the test with a KeyError.
      shared: whether the store lives on the shared PostgreSQL.

    Returns:
      the name of the first assert that fails, or PASS.
    """
    facts = {
        "STALWART_DATABASE_SHARED": shared,
        "STALWART_STORE_LAYOUT_VERSION": _layout_version(),
    }
    for task in load_yaml_any(str(GUARD), default_if_missing=[]):
        when = task.get("when", [])
        if not all(
            _holds(c, facts) for c in (when if isinstance(when, list) else [when])
        ):
            if "register" in task:
                facts[task["register"]] = SKIPPED
            continue
        set_fact = _module(task, "set_fact")
        assertion = _module(task, "assert")
        if set_fact is not None:
            facts.update({k: _render(v, **facts) for k, v in set_fact.items()})
        elif assertion is not None:
            if not all(_holds(c, facts) for c in assertion["that"]):
                return task["name"]
        else:
            facts[task["register"]] = results[task["register"]]
    return PASS


def _marker(content: str) -> dict:
    return {
        "stalwart_store_marker_file": {"changed": False, "stat": {"exists": True}},
        "stalwart_store_marker": {
            "changed": False,
            "content": base64.b64encode(content.encode()).decode(),
        },
    }


def _rows(value: str) -> dict:
    return {"changed": False, "rows": [[value]]}


def _stdout(value: str) -> dict:
    return {"changed": False, "stdout": value}


def _shared(layout: str) -> dict:
    return {
        **NO_MARKER,
        "stalwart_store_database": _rows("1"),
        "stalwart_store_layout": _rows(layout),
    }


def _dedicated(engine: str, layout: str | None = None) -> dict:
    results = {
        **NO_MARKER,
        "stalwart_store_volume": _stdout("stalwart_database\n"),
        "stalwart_store_engine": _stdout(engine),
    }
    if layout is not None:
        results["stalwart_store_layout"] = _rows(layout)
    return results


class TestTheMarkerOfA1xDeployPassesWithoutTheStore(unittest.TestCase):
    def test_a_marked_dedicated_store_passes_with_its_database_down(self):
        self.assertEqual(_guard(_marker(_written_marker()), shared=False), PASS)

    def test_a_marked_shared_store_passes_without_a_query(self):
        self.assertEqual(_guard(_marker(_written_marker()), shared=True), PASS)

    def test_a_marker_of_another_layout_leaves_the_store_to_be_read(self):
        results = {**_dedicated(""), **_marker("0\n")}
        self.assertIn(ENGINE_DOWN, _guard(results, shared=False))


class TestAHostWithoutAStoreIsAFreshInstall(unittest.TestCase):
    def test_no_store_database_on_the_shared_postgres_passes(self):
        results = {**NO_MARKER, "stalwart_store_database": _rows("0")}
        self.assertEqual(_guard(results, shared=True), PASS)

    def test_no_dedicated_volume_passes(self):
        results = {**NO_MARKER, "stalwart_store_volume": _stdout("")}
        self.assertEqual(_guard(results, shared=False), PASS)


class TestASharedStoreIsRead(unittest.TestCase):
    def test_a_store_from_before_1_0_stops_the_deploy(self):
        self.assertIn(PRE_1_0, _guard(_shared("bigint"), shared=True))

    def test_a_1_x_store_passes(self):
        self.assertEqual(_guard(_shared("bytea"), shared=True), PASS)

    def test_a_database_without_a_store_passes(self):
        self.assertEqual(_guard(_shared("absent"), shared=True), PASS)


class TestADedicatedStoreIsReadInItsRunningDatabase(unittest.TestCase):
    def test_a_stopped_database_stops_the_deploy_before_any_query(self):
        self.assertIn(ENGINE_DOWN, _guard(_dedicated(""), shared=False))

    def test_a_store_from_before_1_0_stops_the_deploy(self):
        self.assertIn(
            PRE_1_0, _guard(_dedicated("4f2a9c1e7b3d\n", "bigint"), shared=False)
        )

    def test_a_1_x_store_passes(self):
        self.assertEqual(
            _guard(_dedicated("4f2a9c1e7b3d\n", "bytea"), shared=False), PASS
        )


if __name__ == "__main__":
    unittest.main()
