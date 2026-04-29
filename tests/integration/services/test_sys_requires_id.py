#!/usr/bin/env python3
import os
import glob
import unittest
import yaml

from utils.cache.files import read_text


def _safe_yaml_load(path):
    try:
        doc = yaml.safe_load(read_text(path))
        # A tasks file can be a list (usual) or a dict (blocks, etc.)
        return doc
    except Exception as e:
        raise AssertionError(f"Failed to parse YAML: {path}\n{e}") from e


class TestSysServiceRequiresSystemServiceId(unittest.TestCase):
    def setUp(self):
        # Repo root = three levels up from this file: tests/integration/<cluster>/<this_file>.py
        self.repo_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        self.roles_dir = os.path.join(self.repo_root, "roles")
        self.assertTrue(
            os.path.isdir(self.roles_dir),
            f"'roles' directory not found at: {self.roles_dir}",
        )

    def _iter_task_files(self, role_dir):
        tasks_dir = os.path.join(role_dir, "tasks")
        if not os.path.isdir(tasks_dir):
            return
        patterns = ["*.yml", "*.yaml"]
        for pattern in patterns:
            for path in glob.glob(os.path.join(tasks_dir, pattern)):
                yield path

        # also scan nested includes like tasks/**/*.yml
        for pattern in patterns:
            for path in glob.glob(
                os.path.join(tasks_dir, "**", pattern), recursive=True
            ):
                yield path

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
        elif isinstance(tasks_doc, dict):
            # top-level block file (rare)
            if "block" in tasks_doc and isinstance(tasks_doc["block"], list):
                for bt in tasks_doc["block"]:
                    if check_task(bt):
                        return True
        return False

    def _vars_has_system_service_id(self, role_dir):
        vars_dir = os.path.join(role_dir, "vars")
        if not os.path.isdir(vars_dir):
            return (False, "vars/ directory not found")

        candidates = []
        candidates.extend(glob.glob(os.path.join(vars_dir, "main.yml")))
        candidates.extend(glob.glob(os.path.join(vars_dir, "main.yaml")))
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
            role_dir = os.path.join(self.roles_dir, role)
            if not os.path.isdir(role_dir):
                continue

            for task_file in self._iter_task_files(role_dir):
                tasks_doc = _safe_yaml_load(task_file)
                if self._role_includes_sys_service(tasks_doc):
                    has_var, msg = self._vars_has_system_service_id(role_dir)
                    self.assertTrue(
                        has_var,
                        f"{role}: includes sys-service but system_service_id missing ({msg})",
                    )
