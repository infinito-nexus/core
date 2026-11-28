from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml, load_yaml_any

from . import PROJECT_ROOT

PRODUCER = PROJECT_ROOT / "roles" / "web-app-openpost" / "tasks" / "netns.yml"
PLAYBOOK = Path(sys.executable).with_name("ansible-playbook")
WAIT = "⏳ Wait until the OpenPost container reports healthy"
FAKE = """\
#!{python}
import sys
from pathlib import Path

calls = Path(__file__).resolve().parent.parent / "calls"
log = calls.read_text().split() if calls.exists() else []
kind = "health" if "Health" in sys.argv[sys.argv.index("--format") + 1] else "pid"
log.append(kind)
calls.write_text(" ".join(log))
if kind == "health":
    print("starting" if log.count("health") == 1 else "healthy")
else:
    print(2222 if log.count("health") > 1 else 1111)
"""


def _run(root: Path, producer: Path, run: str) -> dict:
    """Args:
        root: the directory holding ``play.yml`` and ``roles``.
        producer: the OpenPost netns tasks file to include.
        run: name of this run's directory.

    Returns:
        ``rc``, the combined ``output``, the ``python`` argv the producer set,
        and the ``calls`` the fake container CLI answered, in order.
    """
    base = root / run
    (base / "bin").mkdir(parents=True)
    fake = base / "bin" / "container"
    fake.write_text(FAKE.replace("{python}", sys.executable), encoding="utf-8")
    fake.chmod(0o755)
    out = base / "facts.json"
    extra = {
        "producer": str(producer),
        "out": str(out),
        "IS_SWARM_MODE": False,
        "STACK_HOST": "localhost",
        "application_id": "web-app-openpost",
        "OPENPOST_NAME": "openpost",
        "ansible_become": False,
        "ansible_python_interpreter": sys.executable,
    }
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{base / 'bin'}{os.pathsep}{env.get('PATH', '')}",
            "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
            "ANSIBLE_HOME": str(base / "ansible-home"),
            "ANSIBLE_LOCAL_TEMP": str(base / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(base / "ansible-remote"),
            "ANSIBLE_NOCOLOR": "1",
        }
    )
    result = subprocess.run(
        [
            str(PLAYBOOK),
            "-i",
            "localhost,",
            str(root / "play.yml"),
            "-e",
            json.dumps(extra),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = base / "calls"
    return {
        "rc": result.returncode,
        "output": result.stdout + result.stderr,
        "python": json.loads(read_text(str(out))) if out.is_file() else [],
        "calls": read_text(str(calls)).split() if calls.is_file() else [],
    }


@unittest.skipUnless(PLAYBOOK.is_file(), f"{PLAYBOOK} is required")
class TestOpenPostNetnsWaitsHealthy(unittest.TestCase):
    fixed: ClassVar[dict] = {}
    unguarded: ClassVar[dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "roles").symlink_to(PROJECT_ROOT / "roles")
            dump_yaml(
                root / "play.yml",
                [
                    {
                        "hosts": "localhost",
                        "connection": "local",
                        "gather_facts": False,
                        "tasks": [
                            {"ansible.builtin.include_tasks": "{{ producer }}"},
                            {
                                "ansible.builtin.copy": {
                                    "dest": "{{ out }}",
                                    "mode": "0644",
                                    "content": "{{ OPENPOST_NETNS_PYTHON | to_json }}",
                                }
                            },
                        ],
                    }
                ],
            )
            tasks = load_yaml_any(str(PRODUCER))
            if WAIT not in [task.get("name") for task in tasks]:
                raise AssertionError(f"{PRODUCER} lost its health wait")
            unguarded = root / "netns_unguarded.yml"
            dump_yaml(unguarded, [task for task in tasks if task.get("name") != WAIT])
            cls.fixed = _run(root, PRODUCER, "fixed")
            cls.unguarded = _run(root, unguarded, "unguarded")

    def test_the_play_completes(self) -> None:
        self.assertEqual(0, self.fixed["rc"], self.fixed["output"])

    def test_the_pid_is_read_once_the_container_is_healthy(self) -> None:
        self.assertEqual(["health", "health", "pid"], self.fixed["calls"])
        self.assertIn("2222", self.fixed["python"])

    def test_negative_control_without_the_wait_the_pid_of_the_starting_container_sticks(
        self,
    ) -> None:
        self.assertEqual(0, self.unguarded["rc"], self.unguarded["output"])
        self.assertEqual(["pid"], self.unguarded["calls"])
        self.assertIn("1111", self.unguarded["python"])


if __name__ == "__main__":
    unittest.main()
