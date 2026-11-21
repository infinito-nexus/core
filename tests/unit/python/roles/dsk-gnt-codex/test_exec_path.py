from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/dsk-gnt-codex"
PATHS = PROJECT_ROOT / "group_vars/all/05_paths.yml"
NPM_GLOBAL_BIN_DIR = "/usr/local/bin"
ROOT_OWNED = ("/usr/", "/sbin", "/bin")


def _yaml(relative):
    return load_yaml_str(read_text(str(ROLE / relative)))


def _exec_path():
    return load_yaml_str(read_text(str(PATHS))).get("EXEC_PATH_SYSTEM")


def _search_path(template):
    templar = Templar(loader=DataLoader(), variables={"EXEC_PATH_SYSTEM": _exec_path()})
    return str(templar.template(_trust_as_template(template))).split(":")


def _codex_user_tasks():
    return [
        task
        for task in _yaml("tasks/01_gateway.yml")
        if task.get("become_user") == "{{ agnt_codex_user }}"
        and "validate_codex.py" in str(task.get("ansible.builtin.command"))
    ]


class TestCodexExecPath(unittest.TestCase):
    def test_the_workstation_user_validation_finds_the_npm_installed_codex(self):
        tasks = _codex_user_tasks()
        self.assertEqual(len(tasks), 1)
        path = (tasks[0].get("environment") or {}).get("PATH")
        self.assertIsNotNone(
            path,
            "the Codex validation runs as the workstation user through sudo, and "
            "CentOS Stream pins secure_path to /sbin:/bin:/usr/sbin:/usr/bin, so "
            f"the codex that npm install -g links into {NPM_GLOBAL_BIN_DIR} on the "
            "RHEL family is not found (run 43777013536 Blender#0 centos: "
            "'Codex validation failed' in 70 ms, no gateway request)",
        )
        segments = _search_path(path)
        self.assertIn(NPM_GLOBAL_BIN_DIR, segments)
        self.assertIn("/usr/bin", segments)

    def test_the_validation_path_holds_only_root_owned_dirs(self):
        segments = str(_exec_path()).split(":")
        self.assertTrue(
            all(segment.startswith(ROOT_OWNED) for segment in segments),
            f"{segments}: a dir the workstation user can write would let a planted "
            "codex answer the validation in place of the installed client",
        )


if __name__ == "__main__":
    unittest.main()
