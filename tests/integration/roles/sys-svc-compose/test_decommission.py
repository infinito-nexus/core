from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.tests.buckets import register

from . import PROJECT_ROOT

LAYOUT = (".env", "config", "services", "volumes")

FAKE_COMPOSE = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_COMPOSE_LOG"
"""

HOST_COMPOSE = """#!/bin/sh
printf '%s\\n' "$*" >> {log}
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

FINALIZE_PHASE_ROLES = frozenset(
    {"sys-svc-compose", "sys-service-terminator", "test-e2e-cli"}
)
FAILING_PHASES = {
    "decommission": ([], "0123456789ab"),
    "finalize": (["finalize"], "finalize failed"),
    "cli": (["finalize", "cli"], "cli failed"),
}
KEPT_LABELS = {
    "project": ("com.docker.compose.project=mailu", False),
    "workdir": ("com.docker.compose.project.working_dir={root}/mailu", False),
    "resolved": ("com.docker.compose.project.working_dir={resolved}/mailu", True),
}


def _logged(label: str, fails: str | None = None) -> list[dict]:
    tasks: list[dict] = [
        {"ansible.builtin.lineinfile": {"path": "{{ STAGE_LOG }}", "line": label}}
    ]
    if fails:
        tasks.append(
            {"ansible.builtin.fail": {"msg": f"{label} failed"}, "when": fails}
        )
    return tasks


STUB_ROLES = {
    ("sys-service-terminator", "main.yml"): [
        {
            "ansible.builtin.stat": {"path": "{{ DIR_COMPOSITIONS }}mailu"},
            "register": "stale_stack",
        },
        *_logged("finalize", "stale_stack.stat.exists or FAILING == 'finalize'"),
    ],
    ("sys-service-terminator", "02_unlock.yml"): _logged("unlock"),
    ("test-e2e-cli", "main.yml"): _logged("cli", "FAILING == 'cli'"),
}


def _includes(tasks: list[dict], tasks_from: str) -> bool:
    return any(
        isinstance(task.get("include_role"), dict)
        and task["include_role"].get("tasks_from") == tasks_from
        for task in tasks
    )


def _walk(tasks: list[dict]):
    for task in tasks:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _walk(task.get(key, []))


def _stage() -> list[dict]:
    return load_yaml_any(str(PROJECT_ROOT / "tasks" / "stages" / "03_destructor.yml"))


def _finalize_phase() -> list[dict]:
    return [
        task
        for task in _stage()
        if any(
            isinstance(nested.get("include_role"), dict)
            and nested["include_role"].get("name") in FINALIZE_PHASE_ROLES
            for nested in _walk([task])
        )
    ]


def _decommissions(task: dict) -> bool:
    return any(_includes([nested], "decommission.yml") for nested in _walk([task]))


def _destructor_block() -> dict:
    return next(task for task in _stage() if "block" in task and _decommissions(task))


def _destructor_task() -> dict:
    return next(task for task in _destructor_block()["block"] if _decommissions(task))


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


def _recap(result: subprocess.CompletedProcess) -> dict:
    return {
        m["host"]: (int(m["changed"]), int(m["failed"]))
        for m in _RECAP.finditer(result.stdout)
    }


class _Sandbox:
    """
    Args:
        work: the empty directory everything lives in.
    """

    def __init__(self, work: Path) -> None:
        self.work = work
        self.bin = work / "bin"
        self.bin.mkdir()
        self.fake_compose = self.bin / "compose"
        _executable(self.fake_compose, FAKE_COMPOSE)
        _executable(self.bin / "container", FAKE_CONTAINER)
        self.compose_log = work / "compose.log"
        self.container_log = work / "container.log"
        self.leftovers = work / "leftovers"
        self.namesakes = work / "namesakes"
        for path in (
            self.compose_log,
            self.container_log,
            self.leftovers,
            self.namesakes,
        ):
            path.write_text("")
        self.playbook = work / "playbook.yml"
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

    def host(
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
            "DIR_GARBAGE_COLLECTOR_MANIFESTS": f"{self.work / name / 'garbage-collector'}/",
            "BIN_COMPOSE": str(self.fake_compose),
            "CLEANUP": True,
            "DEPLOYMENT_MODE": "compose",
            "IS_COMPOSE_MODE": True,
            "APPLICATIONS_WHITELIST": [],
            "CURRENT_PLAY_APPLICATIONS": {"web-app-closure": {}},
        }
        values.update(overrides)
        return root, values

    def inventory(self, hosts: dict, elsewhere: dict | None = None) -> Path:
        inventory = self.work / "inventory.yml"
        children = {"web-app-grouped": {"hosts": {name: {} for name in hosts}}}
        for group, members in (elsewhere or {}).items():
            children[group] = {"hosts": {name: {} for name in members}}
        dump_yaml(inventory, {"all": {"hosts": hosts, "children": children}})
        return inventory

    def play(self, inventory: Path, *args: str) -> subprocess.CompletedProcess:
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

    def open_host(self) -> tuple[Path, dict]:
        root, values = self.host("open")
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

    def guard_queries(self) -> list[str]:
        return [
            line
            for line in _lines(self.container_log)
            if line.startswith("ps --all --quiet")
        ]

    def stage_log(self, host: str) -> Path:
        return self.work / f"stage-{host}.log"

    def stage_play(
        self, failing: dict[str, str]
    ) -> tuple[dict[str, Path], subprocess.CompletedProcess]:
        """
        Args:
            failing: per inventory host, the phase that fails on it, or ``""``.
                ``playbook.yml`` makes every error fatal, so hosts batched into
                one run must all succeed or the first failure ends the others.

        Returns:
            The compositions root per host, and the run. Each host's compose
            calls and stage markers land in :meth:`stage_log` in the order
            they ran.
        """
        for (role, name), tasks in STUB_ROLES.items():
            path = self.work / "roles" / role / "tasks" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            dump_yaml(path, tasks)
        play = load_yaml_any(str(PROJECT_ROOT / "playbook.yml"))[0]
        dump_yaml(
            self.playbook,
            [
                {
                    "hosts": "all",
                    "gather_facts": False,
                    "any_errors_fatal": play["any_errors_fatal"],
                    "tasks": _finalize_phase(),
                }
            ],
        )
        self.leftovers.write_text(
            "com.docker.compose.project=mailu\n"
            if "decommission" in failing.values()
            else ""
        )
        roots: dict[str, Path] = {}
        hosts: dict[str, dict] = {}
        for host, phase in failing.items():
            log = self.stage_log(host)
            log.write_text("")
            compose = self.bin / f"compose-{host}"
            _executable(compose, HOST_COMPOSE.format(log=shlex.quote(str(log))))
            roots[host], hosts[host] = self.host(
                host,
                RUNTIME="dev",
                STAGE_LOG=str(log),
                FAILING=phase,
                BIN_COMPOSE=str(compose),
            )
            _instance(roots[host], "mailu")
            _instance(roots[host], "grouped")
        return roots, self.play(self.inventory(hosts))


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class _PerTest:
    box: _Sandbox

    def setUp(self) -> None:
        work = Path(tempfile.mkdtemp(prefix="compose-decommission-"))
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        self.box = _Sandbox(work)

    def _assert_ok(self, result: subprocess.CompletedProcess) -> dict:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return _recap(result)


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class TestTheStagePlay(unittest.TestCase):
    box: ClassVar[_Sandbox]
    roots: ClassVar[dict[str, Path]]
    result: ClassVar[subprocess.CompletedProcess]

    @classmethod
    def setUpClass(cls) -> None:
        work = Path(tempfile.mkdtemp(prefix="compose-decommission-"))
        cls.addClassCleanup(shutil.rmtree, work, ignore_errors=True)
        cls.box = _Sandbox(work)
        cls.manifests = work / "garbage-collector-host" / "garbage-collector"
        for application_id in ("web-app-mailu", "web-app-grouped", "web-app-closure"):
            (cls.manifests / application_id).mkdir(parents=True)
        cls.roots, cls.result = cls.box.stage_play(
            {"open": "", "garbage-collector-host": ""}
        )

    def test_the_run_succeeds_on_every_host(self) -> None:
        self.assertEqual(self.result.returncode, 0, self.result.stdout)
        self.assertEqual(
            {host: failed for host, (_, failed) in _recap(self.result).items()},
            {"open": 0, "garbage-collector-host": 0},
        )

    def test_the_decommission_stops_a_stale_stack_before_the_services_start(self):
        root = self.roots["open"]
        self.assertEqual(self.result.returncode, 0, self.result.stdout)
        self.assertEqual(
            _lines(self.box.stage_log("open")),
            [
                f"--chdir {root}/mailu down --remove-orphans",
                "finalize",
                "cli",
                "unlock",
            ],
            "the finalized health checks flag every running container, so a "
            "stale stack must be down before the terminator starts them",
        )
        self.assertFalse((root / "mailu").exists())

    def test_the_stage_drops_the_garbage_collector_manifests_of_inactive_roles(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout)
        self.assertEqual(
            sorted(entry.name for entry in self.manifests.iterdir()),
            ["web-app-closure", "web-app-grouped"],
        )


class _AFailingPhase(_PerTest):
    """
    Args:
        phase: the key of ``FAILING_PHASES`` that fails.
    """

    phase: ClassVar[str]

    def test_a_failing_phase_still_unlocks_the_timers_and_fails_the_play(self):
        ran, message = FAILING_PHASES[self.phase]
        roots, result = self.box.stage_play({self.phase: self.phase})

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stdout)
        self.assertEqual(
            _lines(self.box.stage_log(self.phase)),
            [
                f"--chdir {roots[self.phase]}/mailu down --remove-orphans",
                *ran,
                "unlock",
            ],
        )


class TestTheTimersUnlock(unittest.TestCase):
    def test_the_timers_unlock_even_when_the_decommission_fails(self):
        stage = _stage()
        block = _destructor_block()
        position = next(index for index, task in enumerate(stage) if task is block)
        self.assertEqual(
            [task["include_role"]["name"] for task in stage[position + 1 :]],
            ["sys-svc-app-control", "web-app-semaphore"],
        )
        self.assertTrue(_includes(block["always"], "02_unlock.yml"))
        self.assertFalse(
            _includes([task for task in stage if task is not block], "02_unlock.yml")
        )


class TestCheckMode(_PerTest, unittest.TestCase):
    def test_check_mode_reports_the_decommission_and_changes_nothing(self):
        root, values = self.box.open_host()
        before = sorted(p.name for p in root.iterdir())

        recap = self._assert_ok(
            self.box.play(self.box.inventory({"open": values}), "--check")
        )

        self.assertGreater(recap["open"][0], 0)
        self.assertEqual(sorted(p.name for p in root.iterdir()), before)
        self.assertEqual(_lines(self.box.compose_log), [])
        self.assertEqual(self.box.guard_queries(), [])


class TestComposeDecommission(_PerTest, unittest.TestCase):
    def test_only_an_unrestricted_cleanup_deploy_decommissions_and_a_rerun_is_idle(
        self,
    ):
        root, open_values = self.box.open_host()
        gated = {
            "whitelisted": {"APPLICATIONS_WHITELIST": ["web-app-grouped"]},
            "cleanup_off": {"CLEANUP": False},
            "swarm": {"DEPLOYMENT_MODE": "swarm", "IS_COMPOSE_MODE": False},
        }
        hosts = {"open": open_values}
        gated_roots = {}
        for name, overrides in gated.items():
            gated_roots[name], hosts[name] = self.box.host(name, **overrides)
            _instance(gated_roots[name], "mailu")
        _, hosts["absent"] = self.box.host(
            "absent", DIR_COMPOSITIONS=f"{self.box.work}/absent/missing/"
        )
        inventory = self.box.inventory(hosts, {"web-app-baserow": ["whitelisted"]})

        result = self.box.play(inventory)
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
        self.assertTrue((self.box.work / "elsewhere" / "compose.yml").is_file())
        for gated_root in gated_roots.values():
            self.assertTrue((gated_root / "mailu" / "compose.yml").is_file())
        self.assertEqual(
            _lines(self.box.compose_log),
            [f"--chdir {root}/mailu down --remove-orphans"],
        )
        self.assertEqual(
            self.box.guard_queries(),
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

        rerun = self._assert_ok(self.box.play(inventory))

        self.assertEqual(set(rerun.values()), {(0, 0)})
        self.assertEqual(len(_lines(self.box.compose_log)), 1)


class TestAStackThatKeepsContainers(_PerTest, unittest.TestCase):
    def test_a_stack_that_keeps_containers_fails_and_keeps_its_directory(self):
        for batch in (("project",), ("workdir", "resolved")):
            hosts, roots, labels = {}, {}, {}
            for name in batch:
                label, symlinked = KEPT_LABELS[name]
                roots[name], hosts[name] = self.box.host(name, symlinked=symlinked)
                _instance(roots[name], "mailu")
                labels[name] = label.format(
                    root=roots[name], resolved=roots[name].resolve()
                )
            self.box.leftovers.write_text("".join(f"{labels[n]}\n" for n in batch))

            result = self.box.play(self.box.inventory(hosts))
            recap = _recap(result)

            for name in batch:
                with self.subTest(case=name):
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("0123456789ab", result.stdout)
                    self.assertGreater(recap[name][1], 0, result.stdout)
                    self.assertIn(
                        f"failed: [{name}] (item={labels[name]})", result.stdout
                    )
                    self.assertTrue((roots[name] / "mailu" / "compose.yml").is_file())
                    self.assertIn(
                        f"--chdir {roots[name]}/mailu down --remove-orphans",
                        _lines(self.box.compose_log),
                    )


for _phase in FAILING_PHASES:
    register(
        globals(),
        f"TestAFailingPhase_{_phase}",
        _AFailingPhase,
        phase=_phase,
    )


if __name__ == "__main__":
    unittest.main()
