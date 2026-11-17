from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.packages.sources import FLATPAK_COMMAND_DIR
from utils.templating.ansible import _trust_as_template

ROLE = PROJECT_ROOT / "roles/dsk-blender"
PATHS = PROJECT_ROOT / "group_vars/all/05_paths.yml"
PIPX_BIN_DIR = "/home/alice/.local/bin"
USER_TASKS = ("addons/bonsai.yml", "addons/mcp-for-blender.yml")
ROOT_OWNED = ("/usr/", "/sbin", "/bin")


def _yaml(relative):
    return load_yaml_str(read_text(str(ROLE / relative)))


def _system_exec_path():
    return load_yaml_str(read_text(str(PATHS))).get("EXEC_PATH_SYSTEM")


def _search_path(template):
    templar = Templar(
        loader=DataLoader(),
        variables={
            "EXEC_PATH_SYSTEM": _system_exec_path(),
            "blender_pipx_bin_dir": PIPX_BIN_DIR,
        },
    )
    return str(templar.template(_trust_as_template(template))).split(":")


def _includes():
    return {
        task["ansible.builtin.include_tasks"]["file"]: task
        for task in _yaml("tasks/00_core.yml")
        if "ansible.builtin.include_tasks" in task
    }


def _tasks(relative):
    for task in _yaml(f"tasks/{relative}"):
        yield task
        yield from task.get("block", [])


class TestBlenderExecPath(unittest.TestCase):
    def test_every_workstation_user_include_searches_the_command_dirs(self):
        includes = _includes()
        self.assertEqual(sorted(includes), list(USER_TASKS))
        for relative, include in includes.items():
            apply = include["ansible.builtin.include_tasks"]["apply"]
            path = (apply.get("environment") or {}).get("PATH")
            with self.subTest(include=relative):
                self.assertIsNotNone(
                    path,
                    f"{relative} runs as the workstation user through sudo, and "
                    f"CentOS Stream pins secure_path to /sbin:/bin:/usr/sbin:/usr/bin, "
                    f"so the flatpak launcher package_install links into "
                    f"{FLATPAK_COMMAND_DIR} is not found ([Errno 2] No such file "
                    f"or directory: b'blender', run 43288523728)",
                )
                segments = _search_path(path)
                self.assertIn(FLATPAK_COMMAND_DIR, segments)
                self.assertIn("/usr/bin", segments)

    def test_the_include_path_holds_only_root_owned_dirs(self):
        segments = str(_system_exec_path()).split(":")
        self.assertTrue(
            all(segment.startswith(ROOT_OWNED) for segment in segments),
            f"{segments}: the include PATH also reaches the package_install of "
            f"pipx, which runs as root, so a dir the workstation user can write "
            f"would let that user plant a binary root executes",
        )

    def test_a_task_level_path_keeps_the_command_dirs(self):
        for relative in USER_TASKS:
            for task in _tasks(relative):
                path = (task.get("environment") or {}).get("PATH")
                if path is None:
                    continue
                with self.subTest(task=task["name"]):
                    segments = _search_path(path)
                    self.assertIn(FLATPAK_COMMAND_DIR, segments)
                    self.assertIn("/usr/bin", segments)


if __name__ == "__main__":
    unittest.main()
