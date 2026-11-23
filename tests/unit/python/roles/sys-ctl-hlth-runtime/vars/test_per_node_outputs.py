from __future__ import annotations

import unittest
from pathlib import PurePosixPath
from typing import Any

from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN
from utils.security.pipeline import pipeline

from . import PROJECT_ROOT
from .test_host_excludes import (
    _GROUP_PATHS,
    _context,
    _nfs_mount_paths,
    _render,
    _tasks,
)

_ROLE = PROJECT_ROOT / "roles" / "sys-ctl-hlth-runtime"
_ROLE_VARS = _ROLE / ROLE_FILE_VARS_MAIN
_CORE_TASKS = _ROLE / "tasks" / "00_core.yml"
_HOST_FLAG = "--host '{{ HEALTH_RUNTIME_HOST }}'"
_NODES = ("wrk-01", "wrk-02")
SCRIPT = pipeline()


def _outputs(node: str) -> dict[str, Any]:
    """
    Args:
        node: the inventory hostname the role renders for.

    Returns:
        The rendered report directory, metrics file, shared outputs the role
        removes, and NFS mount paths of that node.
    """
    paths = load_yaml(str(_GROUP_PATHS))
    role_vars = load_yaml(str(_ROLE_VARS))
    context = {**_context(), "inventory_hostname": node}
    for key in ("DIR_METRICS_TEXTFILE", "DIR_HEALTH_RUNTIME_REPORT"):
        context[key] = _render(paths[key], context)
    context["HEALTH_RUNTIME_HOST"] = _render(role_vars["HEALTH_RUNTIME_HOST"], context)
    return {
        "host": context["HEALTH_RUNTIME_HOST"],
        "report": PurePosixPath(context["DIR_HEALTH_RUNTIME_REPORT"]),
        "textfile": PurePosixPath(context["DIR_METRICS_TEXTFILE"]),
        "metrics": PurePosixPath(
            _render(role_vars["HEALTH_RUNTIME_METRICS_FILE"], context)
        ),
        "shared": [
            PurePosixPath(_render(entry, context))
            for entry in role_vars["HEALTH_RUNTIME_SHARED_OUTPUTS"]
        ],
        "nfs": [PurePosixPath(path) for path in _nfs_mount_paths(context)],
    }


def _on(path: PurePosixPath, mounts: list[PurePosixPath]) -> bool:
    return any(path == mount or mount in path.parents for mount in mounts)


class TestPerNodeOutputs(unittest.TestCase):
    def setUp(self) -> None:
        self.nodes = {node: _outputs(node) for node in _NODES}

    def test_the_report_stays_off_the_shared_state(self) -> None:
        for node, outputs in self.nodes.items():
            with self.subTest(node=node):
                self.assertTrue(outputs["nfs"])
                self.assertFalse(
                    _on(outputs["report"], outputs["nfs"]),
                    f"{outputs['report']} lies on the NFS export every swarm "
                    "node mounts, so the nodes overwrite one report",
                )

    def test_every_node_writes_its_own_textfile(self) -> None:
        metrics = {outputs["metrics"] for outputs in self.nodes.values()}
        self.assertEqual(len(metrics), len(_NODES))
        for node, outputs in self.nodes.items():
            with self.subTest(node=node):
                self.assertEqual(
                    (outputs["metrics"].parent, outputs["metrics"].suffix),
                    (outputs["textfile"], ".prom"),
                )

    def test_the_textfile_and_the_label_name_the_same_inventory_host(self) -> None:
        exec_starts = [
            str(task["vars"]["system_service_tpl_exec_start"])
            for task in _tasks(load_yaml_any(str(_CORE_TASKS)))
            if "system_service_tpl_exec_start" in (task.get("vars") or {})
        ]
        self.assertEqual(
            [_HOST_FLAG in exec_start for exec_start in exec_starts], [True]
        )
        for node, outputs in self.nodes.items():
            with self.subTest(node=node):
                self.assertEqual(
                    (outputs["host"], outputs["metrics"].name),
                    (node, f"{SCRIPT.METRIC}.{node}.prom"),
                )

    def test_the_cleanup_removes_only_shared_leftovers(self) -> None:
        for node, outputs in self.nodes.items():
            live = {outputs["report"] / SCRIPT.REPORT, outputs["metrics"]}
            for path in outputs["shared"]:
                with self.subTest(node=node, path=str(path)):
                    self.assertNotIn(path, live)
                    self.assertTrue(_on(path, outputs["nfs"]))


if __name__ == "__main__":
    unittest.main()
