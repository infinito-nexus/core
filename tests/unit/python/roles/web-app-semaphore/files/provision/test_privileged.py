from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from ._fake_provision import FILES, harness_directory, load

privileged = load("provision.privileged")
DEEP_NAME = "d" * 200
DEEP_LEVELS = 30
REAP_TIMEOUT = 60
REAPER = """
import contextlib
import json
import os
import subprocess
import sys

from provision import privileged

ENDED = os.WEXITED | os.WNOWAIT


def gone(process):
    try:
        os.waitid(os.P_PID, process.pid, ENDED | os.WNOHANG)
    except ChildProcessError:
        return True
    return False


def orphan():
    return subprocess.Popen([sys.executable, "-c", ""])


def kept():
    return privileged.spawned([sys.executable, "-c", "raise SystemExit(7)"])


def stopping_at_a_known_zombie():
    with privileged.CHILDREN_LOCK, contextlib.suppress(ChildProcessError):
        while True:
            info = os.waitid(os.P_ALL, 0, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if info is None or info.si_pid in privileged.CHILDREN:
                break
            os.waitpid(info.si_pid, 0)


mode, order = sys.argv[1:]
spawns = (orphan, kept) if order == "orphan-first" else (kept, orphan)
started = {}
for spawn in spawns:
    started[spawn.__name__] = spawn()
for process in started.values():
    os.waitid(os.P_PID, process.pid, ENDED)
if mode == "blind":
    privileged.CHILDREN.clear()
if mode == "first-known":
    stopping_at_a_known_zombie()
else:
    privileged.reap_round()
result = {
    "orphan_reaped": gone(started["orphan"]),
    "code": privileged.waited(started["kept"]),
}
print(json.dumps(result))
"""
ORDERS = ("orphan-first", "kept-first")
GUARDED = {"orphan_reaped": True, "code": 7}


def reaped(mode, order):
    """Args:
        mode: ``guarded`` for the reaper as it is, ``blind`` for one that no
            longer knows the children the spawner waits for, ``first-known``
            for one that stops at the first exited child it knows.
        order: one of :data:`ORDERS`, which of the two children starts
            first.

    Returns:
        ``{"orphan_reaped", "code"}`` of one round of the reaper in a process
        of its own, as PID 1 of the provision runner, after an orphan and a
        child the spawner waits for, with exit code 7, both exited.
    """
    result = subprocess.run(
        [sys.executable, "-c", REAPER, mode, order],
        env={"PYTHONPATH": str(FILES / "python")},
        capture_output=True,
        text=True,
        check=True,
        timeout=REAP_TIMEOUT,
    )
    return json.loads(result.stdout)


class TestReaper(unittest.TestCase):
    def test_a_spawned_child_is_known_to_the_reaper_until_it_is_waited(self):
        process = privileged.spawned([sys.executable, "-c", "raise SystemExit(3)"])
        self.assertIn(process.pid, privileged.CHILDREN)
        self.assertEqual(privileged.waited(process), 3)
        self.assertNotIn(process.pid, privileged.CHILDREN)

    def test_the_reaper_takes_an_orphan_and_leaves_a_waited_child_its_code(self):
        for order in ORDERS:
            with self.subTest(order=order):
                self.assertEqual(reaped("guarded", order), GUARDED)

    def test_negative_control_a_reaper_blind_to_the_children_takes_their_code(self):
        for order in ORDERS:
            with self.subTest(order=order):
                expected = {"orphan_reaped": True, "code": 0}
                self.assertEqual(reaped("blind", order), expected)

    def test_negative_control_a_reaper_stopping_at_a_known_child_keeps_an_orphan(self):
        results = [reaped("first-known", order) for order in ORDERS]
        self.assertIn({"orphan_reaped": False, "code": 7}, results)


class TestDeepPurge(unittest.TestCase):
    def setUp(self):
        self.base = harness_directory()
        self.addCleanup(shutil.rmtree, self.base)

    def deep_findings(self, remove):
        """Args:
            remove: :func:`privileged.remove_owned`, possibly planted.

        Returns:
            A finding when an entry of a tree deeper than ``PATH_MAX`` is
            left, as a sandbox can build one so a path walk fails on it.
        """
        top = self.base / "deep"
        top.mkdir()
        current = os.open(top, os.O_RDONLY | os.O_DIRECTORY)
        for _level in range(DEEP_LEVELS):
            os.mkdir(DEEP_NAME, dir_fd=current)
            inner = os.open(DEEP_NAME, os.O_RDONLY | os.O_DIRECTORY, dir_fd=current)
            os.close(current)
            current = inner
        os.close(current)
        with contextlib.suppress(OSError):
            remove(str(top))
        return [f"{top} keeps entries"] if os.listdir(top) else []

    def test_the_purge_walks_a_tree_beyond_path_max(self):
        self.assertEqual(self.deep_findings(privileged.remove_owned), [])

    def test_negative_control_a_walk_by_path_leaves_the_deep_tree(self):
        def by_path(*tops):
            for top in tops:
                walk = os.walk(top, topdown=False)  # nocheck: project-walk
                for directory, names, files in walk:
                    for name in [*files, *names]:
                        path = Path(directory) / name
                        if path.is_dir():
                            path.rmdir()
                        else:
                            path.unlink()

        self.assertEqual(
            self.deep_findings(by_path), [f"{self.base / 'deep'} keeps entries"]
        )


if __name__ == "__main__":
    unittest.main()
