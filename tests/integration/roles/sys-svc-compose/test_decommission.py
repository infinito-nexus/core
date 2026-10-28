from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml, load_yaml_any

from . import PROJECT_ROOT

LAYOUT = (".env", "config", "services", "volumes")

FAKE_COMPOSE = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_COMPOSE_LOG"
"""

FAKE_CONTAINER = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_CONTAINER_LOG"
case "$3" in
--quiet)
  if grep -qxF -- "${5#label=}" "$FAKE_CONTAINER_LEFTOVERS"; then
    echo 0123456789ab
  fi
  ;;
--filter)
  name=$(printf '%s' "$4" | sed -e 's/^name=^\\/?//' -e 's/\\$$//')
  grep -E "^$name " "$FAKE_CONTAINER_NAMESAKES"
  ;;
esac
exit 0
"""

_RECAP = re.compile(
    r"^(?P<host>\S+)\s*:\s*ok=\d+\s+changed=(?P<changed>\d+)\s+"
    r"unreachable=\d+\s+failed=(?P<failed>\d+)",
    re.MULTILINE,
)


def _includes(tasks: list[dict], tasks_from: str) -> bool:
    return any(
        isinstance(task.get("include_role"), dict)
        and task["include_role"].get("tasks_from") == tasks_from
        for task in tasks
    )


def _destructor_block() -> dict:
    stage = load_yaml_any(str(PROJECT_ROOT / "tasks" / "stages" / "03_destructor.yml"))
    return next(
        task
        for task in stage
        if "block" in task and _includes(task["block"], "decommission.yml")
    )


def _destructor_task() -> dict:
    return next(
        task
        for task in _destructor_block()["block"]
        if _includes([task], "decommission.yml")
    )


def _prepared_tasks() -> list[dict]:
    prep = load_yaml_any(
        str(
            PROJECT_ROOT
            / "roles"
            / "sys-svc-compose"
            / "tasks"
            / "02_stack_host_prep.yml"
        )
    )
    record = next(task for task in prep if "ansible.builtin.set_fact" in task)
    return [
        dict(
            record,
            vars={
                "application_id": "web-app-prepared",
                "compose_prepared_application_ids": [],
            },
        ),
        dict(record, vars={"application_id": "web-app-alsoprepared"}),
    ]


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines()  # nocheck: cache-read tempdir log


def _executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _instance(root: Path, name: str, *, layout: bool = True, compose: bool = True):
    instance = root / name
    instance.mkdir(parents=True)
    if layout:
        for directory in LAYOUT:
            (instance / directory).mkdir()
    if compose:
        (instance / "compose.yml").write_text("services: {}\n")
    return instance


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class TestComposeDecommission(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="compose-decommission-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        self.fake_compose = self.bin / "compose"
        _executable(self.fake_compose, FAKE_COMPOSE)
        _executable(self.bin / "container", FAKE_CONTAINER)
        self.compose_log = self.work / "compose.log"
        self.container_log = self.work / "container.log"
        self.leftovers = self.work / "leftovers"
        self.namesakes = self.work / "namesakes"
        for path in (
            self.compose_log,
            self.container_log,
            self.leftovers,
            self.namesakes,
        ):
            path.write_text("")
        self.playbook = self.work / "playbook.yml"
        dump_yaml(
            self.playbook,
            [
                {
                    "hosts": "all",
                    "gather_facts": False,
                    "tasks": [*_prepared_tasks(), _destructor_task()],
                }
            ],
        )

    def _host(
        self, name: str, *, symlinked: bool = False, **overrides
    ) -> tuple[Path, dict]:
        root = self.work / name / "compose"
        if symlinked:
            target = self.work / name / "real-compose"
            target.mkdir(parents=True)
            root.symlink_to(target)
        else:
            root.mkdir(parents=True)
        values = {
            "ansible_connection": "local",
            "ansible_python_interpreter": sys.executable,
            "DIR_COMPOSITIONS": f"{root}/",
            "BIN_COMPOSE": str(self.fake_compose),
            "MODE_CLEANUP": True,
            "DEPLOYMENT_MODE": "compose",
            "APPLICATIONS_WHITELIST": [],
            "CURRENT_PLAY_APPLICATIONS": {"web-app-closure": {}},
        }
        values.update(overrides)
        return root, values

    def _inventory(self, hosts: dict, elsewhere: dict | None = None) -> Path:
        inventory = self.work / "inventory.yml"
        children = {"web-app-grouped": {"hosts": {name: {} for name in hosts}}}
        for group, members in (elsewhere or {}).items():
            children[group] = {"hosts": {name: {} for name in members}}
        dump_yaml(inventory, {"all": {"hosts": hosts, "children": children}})
        return inventory

    def _play(self, inventory: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.update(
            {
                "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
                "ANSIBLE_LOCAL_TEMP": str(self.work / "ansible-local"),
                "ANSIBLE_REMOTE_TEMP": str(self.work / "ansible-remote"),
                "ANSIBLE_NOCOLOR": "1",
                "PATH": f"{self.bin}{os.pathsep}{env['PATH']}",
                "FAKE_COMPOSE_LOG": str(self.compose_log),
                "FAKE_CONTAINER_LOG": str(self.container_log),
                "FAKE_CONTAINER_LEFTOVERS": str(self.leftovers),
                "FAKE_CONTAINER_NAMESAKES": str(self.namesakes),
            }
        )
        return subprocess.run(
            ["ansible-playbook", "-i", str(inventory), str(self.playbook), *args],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def _open_host(self) -> tuple[Path, dict]:
        root, values = self._host("open")
        stale = _instance(root, "mailu")
        (stale / "volumes" / "data.txt").write_text("bind data\n")
        for name in (
            "grouped",
            "closure",
            "prepared",
            "alsoprepared",
            "baserow",
            "discourse",
        ):
            _instance(root, name)
        (
            _instance(root, "handmade", layout=False, compose=False) / "notes.txt"
        ).write_text("operator notes\n")
        _instance(root, "partial", layout=False)
        _instance(root, "nextcloud-old")
        _instance(root, ".hidden")
        (root / "linked").symlink_to(_instance(self.work, "elsewhere"))
        self.namesakes.write_text("mailu mailu\ndiscourse \n")
        return root, values

    def _assert_ok(self, result: subprocess.CompletedProcess) -> dict:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return {
            m["host"]: (int(m["changed"]), int(m["failed"]))
            for m in _RECAP.finditer(result.stdout)
        }

    def _guard_queries(self) -> list[str]:
        return [
            line
            for line in _lines(self.container_log)
            if line.startswith("ps --all --quiet")
        ]

    def test_the_timers_unlock_even_when_the_decommission_fails(self):
        stage = load_yaml_any(
            str(PROJECT_ROOT / "tasks" / "stages" / "03_destructor.yml")
        )
        block = _destructor_block()
        self.assertIs(stage[-1], block)
        self.assertTrue(_includes(block["always"], "02_unlock.yml"))
        self.assertFalse(
            _includes([task for task in stage if task is not block], "02_unlock.yml")
        )

    def test_check_mode_reports_the_decommission_and_changes_nothing(self):
        root, values = self._open_host()
        before = sorted(p.name for p in root.iterdir())

        recap = self._assert_ok(
            self._play(self._inventory({"open": values}), "--check")
        )

        self.assertGreater(recap["open"][0], 0)
        self.assertEqual(sorted(p.name for p in root.iterdir()), before)
        self.assertEqual(_lines(self.compose_log), [])
        self.assertEqual(self._guard_queries(), [])

    def test_only_an_unrestricted_cleanup_deploy_decommissions_and_a_rerun_is_idle(
        self,
    ):
        root, open_values = self._open_host()
        gated = {
            "whitelisted": {"APPLICATIONS_WHITELIST": ["web-app-grouped"]},
            "cleanup_off": {"MODE_CLEANUP": False},
            "swarm": {"DEPLOYMENT_MODE": "swarm"},
        }
        hosts = {"open": open_values}
        gated_roots = {}
        for name, overrides in gated.items():
            gated_roots[name], hosts[name] = self._host(name, **overrides)
            _instance(gated_roots[name], "mailu")
        _, hosts["absent"] = self._host(
            "absent", DIR_COMPOSITIONS=f"{self.work}/absent/missing/"
        )
        inventory = self._inventory(hosts, {"web-app-baserow": ["whitelisted"]})

        result = self._play(inventory)
        recap = self._assert_ok(result)
        output = " ".join(result.stdout.split())

        self.assertEqual(
            sorted(p.name for p in root.iterdir()),
            [
                ".hidden",
                "alsoprepared",
                "baserow",
                "closure",
                "discourse",
                "grouped",
                "handmade",
                "linked",
                "nextcloud-old",
                "partial",
                "prepared",
            ],
        )
        self.assertTrue((root / "handmade" / "notes.txt").is_file())
        self.assertTrue((self.work / "elsewhere" / "compose.yml").is_file())
        for gated_root in gated_roots.values():
            self.assertTrue((gated_root / "mailu" / "compose.yml").is_file())
        self.assertEqual(
            _lines(self.compose_log),
            [f"--chdir {root}/mailu down --remove-orphans"],
        )
        self.assertEqual(
            self._guard_queries(),
            [
                "ps --all --quiet --filter label=com.docker.compose.project=mailu",
                (
                    "ps --all --quiet --filter "
                    f"label=com.docker.compose.project.working_dir={root}/mailu"
                ),
            ],
        )
        self.assertIn(
            f"No active role owns {root}/handmade, {root}/nextcloud-old, "
            f"{root}/partial, but",
            output,
        )
        self.assertIn(f"No active role owns {root}/discourse, but a container", output)
        self.assertGreater(recap["open"][0], 0)
        for name in (*gated, "absent"):
            self.assertEqual(recap[name], (0, 0))

        rerun = self._assert_ok(self._play(inventory))

        self.assertEqual(set(rerun.values()), {(0, 0)})
        self.assertEqual(len(_lines(self.compose_log)), 1)

    def test_a_stack_that_keeps_containers_fails_and_keeps_its_directory(self):
        cases = (
            ("project", "com.docker.compose.project=mailu", False),
            ("workdir", "com.docker.compose.project.working_dir={root}/mailu", False),
            (
                "resolved",
                "com.docker.compose.project.working_dir={resolved}/mailu",
                True,
            ),
        )
        for name, label, symlinked in cases:
            with self.subTest(case=name):
                root, values = self._host(name, symlinked=symlinked)
                _instance(root, "mailu")
                self.leftovers.write_text(
                    label.format(root=root, resolved=root.resolve()) + "\n"
                )

                result = self._play(self._inventory({"open": values}))

                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("0123456789ab", result.stdout)
                self.assertTrue((root / "mailu" / "compose.yml").is_file())
                self.assertIn(
                    f"--chdir {root}/mailu down --remove-orphans",
                    _lines(self.compose_log),
                )


if __name__ == "__main__":
    unittest.main()
