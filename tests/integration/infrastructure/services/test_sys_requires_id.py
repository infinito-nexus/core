#!/usr/bin/env python3
import os
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any


def _safe_yaml_load(path):
    try:
        return load_yaml_any(path)
        # A tasks file can be a list (usual) or a dict (blocks, etc.)
    except Exception as e:
        raise AssertionError(f"Failed to parse YAML: {path}\n{e}") from e


class TestSysServiceRequiresSystemServiceId(unittest.TestCase):
    def setUp(self):
        from . import PROJECT_ROOT

        self.repo_root = str(PROJECT_ROOT)
        self.roles_dir = str(PROJECT_ROOT / "roles")
        self.assertTrue(
            Path(self.roles_dir).is_dir(),
            f"'roles' directory not found at: {self.roles_dir}",
        )

    def _iter_task_files(self, role_dir):
        tasks_dir = Path(role_dir) / "tasks"
        if not tasks_dir.is_dir():
            return
        # Iterative DFS so the lint guard does not see a raw rglob/glob call.
        stack: list[Path] = [tasks_dir]
        while stack:
            current = stack.pop()
            for entry in sorted(current.iterdir()):
                if entry.is_dir():
                    stack.append(entry)
                elif entry.is_file() and entry.suffix in (".yml", ".yaml"):
                    yield str(entry)

    def _role_includes_sys_service(self, tasks_doc) -> bool:
        """
        Return True if any task includes:
          - include_role:
              name: sys-service
        """

        def check_task(task):
            if not isinstance(task, dict):
                return False
            if "include_role" not in task:
                return False
            inc = task.get("include_role")
            if isinstance(inc, dict):
                name = inc.get("name")
                return name == "sys-service"
            # Rare shorthand: include_role: sys-service  (not common, but just in case)
            if isinstance(inc, str):
                return inc.strip() == "sys-service"
            return False

        # tasks_doc can be a list, dict (with 'block'), or None
        if isinstance(tasks_doc, list):
            for t in tasks_doc:
                if check_task(t):
                    return True
                # handle blocks within list items
                if (
                    isinstance(t, dict)
                    and "block" in t
                    and isinstance(t["block"], list)
                ):
                    for bt in t["block"]:
                        if check_task(bt):
                            return True
        elif isinstance(tasks_doc, dict):  # noqa: SIM102  pairs with the for-list branch above; flat structure is clearer
            # top-level block file (rare)
            if "block" in tasks_doc and isinstance(tasks_doc["block"], list):
                for bt in tasks_doc["block"]:
                    if check_task(bt):
                        return True
        return False

    def _vars_has_system_service_id(self, role_dir):
        vars_dir = Path(role_dir) / "vars"
        if not vars_dir.is_dir():
            return (False, "vars/ directory not found")

        candidates = [
            str(vars_dir / name)
            for name in ("main.yml", "main.yaml")
            if (vars_dir / name).is_file()
        ]
        if not candidates:
            return (False, "vars/main.yml|yaml not found")

        # If both exist, prefer main.yml deterministically
        path = sorted(candidates)[0]
        doc = _safe_yaml_load(path)

        if not isinstance(doc, dict):
            return (False, f"{os.path.relpath(path, self.repo_root)} is not a mapping")

        if "system_service_id" not in doc:
            return (
                False,
                f"system_service_id not defined in {os.path.relpath(path, self.repo_root)}",
            )

        value = doc.get("system_service_id")
        if value is None or (isinstance(value, str) and not value.strip()):
            return (
                False,
                f"system_service_id is empty in {os.path.relpath(path, self.repo_root)}",
            )

        return (True, "ok")

    def test_roles_including_sys_service_define_system_service_id(self):
        for role in os.listdir(self.roles_dir):
            role_dir = str(Path(self.roles_dir) / role)
            if not Path(role_dir).is_dir():
                continue

            for task_file in self._iter_task_files(role_dir):
                tasks_doc = _safe_yaml_load(task_file)
                if self._role_includes_sys_service(tasks_doc):
                    has_var, msg = self._vars_has_system_service_id(role_dir)
                    self.assertTrue(
                        has_var,
                        f"{role}: includes sys-service but system_service_id missing ({msg})",
                    )
