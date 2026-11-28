from __future__ import annotations

import ast
import datetime as dt
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from ._fake_provision import FILES
from ._tofu_case import (
    READY_BOUND,
    READY_POLL,
    RUNNER,
    TEST_BUDGET,
    TofuCase,
    opentofu,
    provision,
    sandbox,
)

PYTHON = FILES / "python"
SPAWN_CALLS = {
    "subprocess": {"Popen", "run", "call", "check_call", "check_output"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
    "os": {
        "system",
        "popen",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "posix_spawn",
        "posix_spawnp",
    },
}
BARE_SPAWN_NAMES = {
    "Popen",
    "check_call",
    "check_output",
    "posix_spawn",
    "posix_spawnp",
}
PLANTED_SPAWN = '        subprocess.Popen(["tofu", "apply"])\n'
PLANTED_CHDIR = '        self.run("init", "-chdir=/")\n'
PLANT_ANCHOR = "    def run(self, *arguments, capture=False):\n"
SAMPLE_TASK = Path("/run/provision/63801/task")
TASK_FILE = "backend.tfbackend"
BARE_VAR_FILE = ["apply", "-var-file", "-auto-approve"]
SAMPLE_LOCK_ID = "0f6e5c3a-2b1d-4e8f-9a7b-6c5d4e3f2a1b"
SURVIVOR_REPLY = b'{"error": "a process of the sandbox 63801 survived"}\n'
SURVIVOR_BOUND = 5
DISGUISED_SPAWNS = (
    "from subprocess import Popen as P\nP(['tofu', 'apply'])\n",
    "from subprocess import run\nrun(['tofu', 'apply'])\n",
    "import subprocess as sp\nsp.run(['tofu', 'apply'])\n",
    "import subprocess\nARGV = ['tofu', 'apply']\nsubprocess.Popen(ARGV)\n",
    "import asyncio\nasyncio.create_subprocess_exec('tofu', 'apply')\n",
    "import os\nos.execvp('tofu', ['tofu', 'apply'])\n",
)


def modules():
    """Returns:
    ``{path below files/python: source}`` of every module there.
    """
    prefix = f"{PYTHON}{os.sep}"
    return {
        str(Path(path).relative_to(PYTHON)): read_text(path)
        for path in sorted(iter_project_files(extensions=(".py",)))
        if path.startswith(prefix)
    }


def _imports(tree):
    """Args:
        tree: a parsed module.

    Returns:
        ``({alias: module}, {name: (module, function)})`` of its ``import x
        as y`` and ``from x import f as g`` statements.
    """
    modules, functions = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                functions[alias.asname or alias.name] = (node.module, alias.name)
    return modules, functions


def _spawns(function, modules, functions):
    if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
        module = modules.get(function.value.id, function.value.id)
        return function.attr in SPAWN_CALLS.get(module, set())
    if not isinstance(function, ast.Name):
        return False
    module, name = functions.get(function.id, (None, function.id))
    return name in SPAWN_CALLS.get(module, set()) or name in BARE_SPAWN_NAMES


def _is_tofu(value):
    return value == "tofu" or value.startswith("tofu ") or value.endswith("/tofu")


def _constants_tofu(node):
    return any(
        isinstance(part, ast.Constant)
        and isinstance(part.value, str)
        and _is_tofu(part.value)
        for part in ast.walk(node)
    )


def _bound_tofu(tree):
    """Args:
        tree: a parsed module.

    Returns:
        Every name an assignment binds to a value naming ``tofu``.
    """
    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and _constants_tofu(node.value)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _names_tofu(node, bound):
    return _constants_tofu(node) or any(
        isinstance(part, ast.Name) and part.id in bound for part in ast.walk(node)
    )


def direct_tofu_findings(sources):
    """Args:
        sources: :func:`modules`, possibly planted.

    Returns:
        One finding per call that starts a process naming ``tofu`` itself,
        directly, through an import alias or a name bound to its argv,
        instead of handing it to the run's sandbox.
    """
    findings = []
    for name, source in sorted(sources.items()):
        tree = ast.parse(source)
        modules, functions = _imports(tree)
        bound = _bound_tofu(tree)
        findings += [
            f"{name}:{node.lineno} starts tofu outside the run's sandbox"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _spawns(node.func, modules, functions)
            and _names_tofu(node, bound)
        ]
    return findings


class TestTheOneSpawnPoint(unittest.TestCase):
    def test_every_tofu_call_runs_in_the_run_sandbox(self):
        sources = modules()
        self.assertIn("provision/opentofu.py", sources)
        self.assertEqual(direct_tofu_findings(sources), [])
        with self.assertRaisesRegex(sandbox.SandboxError, "task directory of no"):
            opentofu.tofu(Path("/nonexistent"), {}, "version")

    def test_negative_control_a_direct_tofu_spawn_is_caught(self):
        sources = modules()
        session = sources["provision/session.py"]
        planted = session.replace(PLANT_ANCHOR, PLANT_ANCHOR + PLANTED_SPAWN)
        self.assertNotEqual(planted, session)
        findings = direct_tofu_findings(sources | {"provision/session.py": planted})
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith("provision/session.py:"), findings)

    def test_negative_control_an_aliased_or_bound_tofu_spawn_is_caught(self):
        for planted in DISGUISED_SPAWNS:
            with self.subTest(planted=planted):
                findings = direct_tofu_findings({"planted.py": planted})
                self.assertEqual(len(findings), 1, findings)


def provision_calls(sources):
    """Args:
        sources: :func:`modules`, possibly planted.

    Returns:
        ``[(module, line, arguments)]`` of every ``run`` call of a session
        whose arguments are literals; an f-string stands for its literal head
        and a file inside the task, a name for a lock id.
    """
    calls = []
    for name in ("provision/session.py", "provision/zone.py", "provision.py"):
        for node in ast.walk(ast.parse(sources[name])):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                continue
            arguments = []
            for argument in node.args:
                if isinstance(argument, ast.Constant):
                    arguments.append(argument.value)
                elif isinstance(argument, ast.JoinedStr):
                    arguments.append(f"{argument.values[0].value}{TASK_FILE}")
                else:
                    arguments.append(SAMPLE_LOCK_ID)
            calls.append((name, node.lineno, arguments))
    return calls


def refused_calls(sources):
    """Returns:
    One finding per :func:`provision_calls` entry the spawner's argument
    check refuses, the commands :data:`opentofu.COMMANDS` names being the
    one list both sides use.
    """
    findings = []
    for name, line, arguments in provision_calls(sources):
        try:
            opentofu.admitted_arguments(arguments, SAMPLE_TASK)
        except sandbox.SandboxError as refusal:
            findings.append(f"{name}:{line} {refusal}")
    return findings


class TestTheTofuCommands(unittest.TestCase):
    def test_every_tofu_call_of_provision_is_admitted(self):
        sources = modules()
        self.assertGreaterEqual(len(provision_calls(sources)), len(opentofu.COMMANDS))
        self.assertEqual(refused_calls(sources), [])

    def test_negative_control_a_planted_chdir_is_refused(self):
        sources = modules()
        session = sources["provision/session.py"]
        planted = session.replace(PLANT_ANCHOR, PLANT_ANCHOR + PLANTED_CHDIR)
        self.assertNotEqual(planted, session)
        findings = refused_calls(sources | {"provision/session.py": planted})
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("takes no -chdir", findings[0])

    def test_a_task_file_flag_without_its_file_is_refused(self):
        with self.assertRaisesRegex(sandbox.SandboxError, "takes no -var-file"):
            opentofu.admitted_arguments(BARE_VAR_FILE, SAMPLE_TASK)

    def test_negative_control_a_check_of_bare_flags_admits_it(self):
        with mock.patch.object(opentofu, "TASK_FILE_FLAGS", frozenset()):
            admitted = opentofu.admitted_arguments(BARE_VAR_FILE, SAMPLE_TASK)
        self.assertEqual(admitted, (BARE_VAR_FILE, []))


class TestASurvivorEndsTheCall(unittest.TestCase):
    def setUp(self):
        self.peer, connection = socket.socketpair()
        self.addCleanup(self.peer.close)
        self.addCleanup(connection.close)
        box = sandbox.Sandbox(sandbox.Channel(connection), 63801, SAMPLE_TASK)
        sandbox._OPEN[str(SAMPLE_TASK)] = box
        self.addCleanup(sandbox._OPEN.pop, str(SAMPLE_TASK))
        self.peer.sendall(SURVIVOR_REPLY)

    def outcome(self, capture):
        """Args:
            capture: whether ``tofu`` captures stdout, whose pipe the
                unread request to the spawner keeps open like a survivor.

        Returns:
            The refusal ``tofu`` ended with within :data:`SURVIVOR_BOUND`
            seconds, ``None`` while it still waits.
        """
        outcome = []

        def call():
            try:
                opentofu.tofu(SAMPLE_TASK, {}, "apply", capture=capture)
            except Exception as error:
                outcome.append(str(error))

        thread = threading.Thread(target=call, daemon=True)
        thread.start()
        thread.join(SURVIVOR_BOUND)
        return outcome[0] if outcome else None

    def test_the_error_reply_ends_the_call_at_once(self):
        self.assertIn("survived", self.outcome(False) or "still waits")

    def test_the_error_reply_ends_a_capturing_call_at_once(self):
        self.assertIn("survived", self.outcome(True) or "still waits")

    def test_negative_control_a_drain_to_the_end_of_the_pipe_still_waits(self):
        def to_the_end(reader, box):
            chunks = []
            while chunk := os.read(reader, opentofu.READ_BYTES):
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8"), box.ended()

        with mock.patch.object(opentofu, "_drained", to_the_end):
            self.assertIsNone(self.outcome(True))


class TestTofuBudget(TofuCase):
    def test_a_budget_end_interrupts_tofu_which_releases_its_lock(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 1)
        self.assertTrue(self.sigint.is_file())
        self.assertFalse(self.lock.exists())
        self.assertIn(f"the run exceeded its time budget of {TEST_BUDGET}", stderr)
        self.assertIn("tofu apply stopped on SIGINT with exit code 130", stderr)
        self.assert_tofu_ended()

    def test_tofu_leads_a_session_of_its_own(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        report = self.tofu_report()
        self.assertEqual(report["group"], report["pid"])
        self.assertNotEqual(report["group"], os.getpgrp())

    def test_the_kill_after_the_grace_takes_the_plugins_of_tofu(self):
        self.plugin = "spawn"
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("ignore", dt.timedelta(milliseconds=200))
        self.assert_ended(self.tofu_report()["plugin"], "the plugin of tofu")
        self.assertEqual(code, 1)
        self.assertIn("ignored SIGINT", stderr)

    def test_the_death_of_the_runner_takes_tofu_and_its_plugins(self):
        self.plugin = "spawn"
        runner = subprocess.Popen(
            [sys.executable, "-c", RUNNER, str(Path(provision.__file__).parent)],
            env=self.environment("trap") | {"TMPDIR": str(self.root)},
        )
        self.addCleanup(runner.wait)
        deadline = time.monotonic() + READY_BOUND
        while not self.ready.exists() and time.monotonic() < deadline:
            time.sleep(READY_POLL)
        runner.kill()
        self.assertTrue(self.ready.exists(), "the fake tofu never got ready")
        report = self.tofu_report()
        self.assert_ended(report["plugin"], "the plugin of tofu")
        self.assert_ended(report["pid"], "the fake tofu")

    def test_a_plugin_outliving_tofu_ends_with_the_run(self):
        self.plugin = "spawn"
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 1)
        self.assertIn("tofu apply stopped on SIGINT with exit code 130", stderr)
        self.assert_ended(self.tofu_report()["plugin"], "the plugin of tofu")

    def kill_tofu(self):
        os.kill(self.tofu_report()["pid"], signal.SIGKILL)

    def test_a_tofu_killed_by_a_signal_fails_the_run_with_its_plugins(self):
        self.plugin = "spawn"
        self.when(self.ready, self.kill_tofu)
        code, stderr = self.run_apply("trap", dt.timedelta(seconds=1))
        self.assertEqual(code, 1)
        self.assertIn(f"tofu apply was killed by signal {int(signal.SIGKILL)}", stderr)
        self.assertIn("may miss resources and keep its lock", stderr)
        report = self.tofu_report()
        self.assert_ended(report["plugin"], "the plugin of tofu")
        self.assert_ended(report["pid"], "the fake tofu")

    def test_negative_control_tofu_ignoring_sigint_is_killed_after_the_grace(self):
        grace = dt.timedelta(milliseconds=200)
        self.when(self.ready, self.send(signal.SIGALRM))
        code, stderr = self.run_apply("ignore", grace)
        self.assertEqual(code, 1)
        self.assertFalse(self.sigint.exists())
        self.assertTrue(self.lock.is_file())
        self.assertIn(f"the run exceeded its time budget of {TEST_BUDGET}", stderr)
        self.assertIn(f"tofu apply ignored SIGINT for {grace} and was killed", stderr)
        self.assert_tofu_ended()

    def test_a_sigterm_interrupts_tofu_which_releases_its_lock(self):
        self.when(self.ready, self.send(signal.SIGTERM))
        code, _ = self.run_apply("trap", dt.timedelta(seconds=READY_BOUND))
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertTrue(self.sigint.is_file())
        self.assertFalse(self.lock.exists())
        self.assert_tofu_ended()

    def test_negative_control_a_sigterm_kills_tofu_ignoring_sigint_after_the_grace(
        self,
    ):
        grace = dt.timedelta(milliseconds=200)
        self.when(self.ready, self.send(signal.SIGTERM))
        code, _ = self.run_apply("ignore", grace)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertFalse(self.sigint.exists())
        self.assertTrue(self.lock.is_file())
        self.assert_tofu_ended()

    def test_a_second_signal_in_the_grace_kills_tofu_at_once(self):
        self.when(self.ready, self.send(signal.SIGALRM))
        self.when(self.sigint, self.send(signal.SIGTERM))
        started = time.monotonic()
        code, _ = self.run_apply("linger", dt.timedelta(seconds=READY_BOUND))
        self.assertLess(time.monotonic() - started, READY_BOUND)
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertTrue(self.lock.is_file())
        self.assert_tofu_ended()

    def test_a_stop_holds_the_budget_off_during_the_grace(self):
        armed = []
        self.when(self.ready, self.send(signal.SIGTERM))
        self.when(
            self.sigint,
            lambda: armed.append(signal.getitimer(signal.ITIMER_REAL)[0]),
        )
        code, _ = self.run_apply("linger", dt.timedelta(seconds=1))
        self.assertEqual(code, 128 + signal.SIGTERM)
        self.assertEqual(armed, [0.0])
        self.assert_tofu_ended()


if __name__ == "__main__":
    unittest.main()
