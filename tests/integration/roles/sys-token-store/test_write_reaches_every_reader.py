from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.yaml import dump_yaml, load_yaml_any

from . import PROJECT_ROOT

WRITE_MANY = PROJECT_ROOT / "roles" / "sys-token-store" / "tasks" / "write_many.yml"
MERGE = "🔨 Build merged structure"
CHANGED = "🧮 Note whether the merge changed the store"
WRITES = (
    "💾 Persist store (idempotent, single-writer via STACK_HOST)",
    "🪞 Mirror the store onto the controller, where every users lookup reads",
)

LOADED = {"no-reply": {"tokens": {"web-app-matomo": "loaded"}}}


def _with(app: str, token: str) -> dict:
    return {"no-reply": {"tokens": {"web-app-matomo": "loaded", app: token}}}


def _entries(app: str, token: str) -> list[dict]:
    return [{"user_key": "no-reply", "app": app, "token": token}]


PLAYS = {
    "one_writer": {
        "mgr": ("mgr", LOADED, _entries("web-app-stalwart", "minted")),
        "wrk": ("mgr", LOADED, None),
        "solo": ("solo", LOADED, None),
    },
    "writers_on_two_stack_hosts": {
        "c1": ("c1", LOADED, _entries("web-app-c1", "one")),
        "r1": ("c1", LOADED, None),
        "c2": ("c2", LOADED, _entries("web-app-c2", "two")),
    },
    "unchanged_first_writer": {
        "e1": ("e1", _with("web-app-e", "same"), _entries("web-app-e", "same")),
        "e2": ("e1", LOADED, _entries("web-app-e", "same")),
        "e3": ("e1", LOADED, None),
    },
    "writers_on_one_stack_host": {
        "w1": ("w1", LOADED, _entries("web-app-w1", "one")),
        "w2": ("w1", LOADED, _entries("web-app-w2", "two")),
        "r2": ("w1", LOADED, None),
    },
}


def _writer_tasks() -> list[dict]:
    """Return the merge, the change check and the store-write block of ``write_many.yml``.

    Returns:
        The real merge and change-check tasks, then the block with its own
        ``when`` gate minus the stack host write and the controller mirror.
    """
    tasks = load_yaml_any(str(WRITE_MANY))
    named = {task.get("name"): task for task in tasks}
    blocks = [task for task in tasks if "block" in task]
    if MERGE not in named or CHANGED not in named or len(blocks) != 1:
        raise AssertionError(f"{WRITE_MANY} lost {MERGE!r}, {CHANGED!r} or its block")
    kept = [task for task in blocks[0]["block"] if task.get("name") not in WRITES]
    if len(kept) != len(blocks[0]["block"]) - len(WRITES):
        raise AssertionError(f"{WRITE_MANY} lost one of {WRITES!r}")
    return [named[MERGE], named[CHANGED], {**blocks[0], "block": kept}]


def _host(stack_host: str, loaded: dict, entries: list[dict] | None) -> dict:
    host = {
        "ansible_connection": "local",
        "ansible_python_interpreter": sys.executable,
        "STACK_HOST": stack_host,
        "MASK_CREDENTIALS_IN_LOGS": False,
        "sys_token_store_loaded": loaded,
    }
    if entries is not None:
        host["sys_token_store_entries"] = entries
    return host


def _play(group: str, writer: Path, views: Path) -> dict:
    return {
        "hosts": group,
        "gather_facts": False,
        "tasks": [
            {
                "name": "Load the store on every host",
                "ansible.builtin.set_fact": {
                    "sys_token_store_users": "{{ sys_token_store_loaded }}"
                },
            },
            {
                "name": "Write the tokens of the writers in lockstep",
                "ansible.builtin.include_tasks": str(writer),
                "when": "sys_token_store_entries is defined",
            },
            {
                "name": "Report the store every host resolves",
                "ansible.builtin.copy": {
                    "content": "{{ sys_token_store_users | to_json }}",
                    "dest": f"{views}/{{{{ inventory_hostname }}}}.json",
                    "mode": "0644",
                },
            },
        ],
    }


def _run_plays(workdir: Path) -> dict[str, dict]:
    """Load the store on every host, write on the writers only, report every view.

    Args:
        workdir: an empty directory to build the inventory and the plays in.

    Returns:
        The ``sys_token_store_users`` fact of each host after the write.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    views = workdir / "views"
    views.mkdir()
    writer = workdir / "writer.yml"
    groups = {
        group: {"hosts": {name: _host(*spec) for name, spec in hosts.items()}}
        for group, hosts in PLAYS.items()
    }
    dump_yaml(workdir / "inventory.yml", {"all": {"children": groups}})
    dump_yaml(writer, _writer_tasks())
    dump_yaml(workdir / "play.yml", [_play(group, writer, views) for group in PLAYS])
    env = dict(os.environ)
    env.update(
        {
            "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
            "ANSIBLE_LOCAL_TEMP": str(workdir / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(workdir / "ansible-remote"),
            "ANSIBLE_NOCOLOR": "1",
        }
    )
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            str(workdir / "inventory.yml"),
            str(workdir / "play.yml"),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ansible-playbook failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return {
        name: json.loads((views / f"{name}.json").read_text())
        for hosts in PLAYS.values()
        for name in hosts
    }


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class TestWriteReachesEveryReader(unittest.TestCase):
    views: ClassVar[dict[str, dict]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.views = _run_plays(Path(tmp))

    def test_the_writer_resolves_its_own_write(self) -> None:
        self.assertEqual(self.views["mgr"], _with("web-app-stalwart", "minted"))

    def test_a_reader_of_the_same_stack_host_resolves_the_write(self) -> None:
        self.assertEqual(
            self.views["wrk"],
            _with("web-app-stalwart", "minted"),
            "a swarm worker that loaded the store before the write must not "
            "render the new token empty for the rest of the play",
        )

    def test_a_host_with_its_own_stack_host_keeps_its_store(self) -> None:
        self.assertEqual(self.views["solo"], LOADED)

    def test_lockstep_writers_on_two_stack_hosts_keep_their_own_writes(self) -> None:
        self.assertEqual(self.views["c1"], _with("web-app-c1", "one"))
        self.assertEqual(self.views["c2"], _with("web-app-c2", "two"))

    def test_a_reader_resolves_only_the_writer_of_its_stack_host(self) -> None:
        self.assertEqual(self.views["r1"], _with("web-app-c1", "one"))

    def test_a_changed_writer_behind_an_unchanged_one_still_hands_over(self) -> None:
        for name in ("e1", "e2", "e3"):
            with self.subTest(host=name):
                self.assertEqual(self.views[name], _with("web-app-e", "same"))

    def test_lockstep_writers_on_one_stack_host_keep_their_own_writes(self) -> None:
        self.assertEqual(self.views["w1"], _with("web-app-w1", "one"))
        self.assertEqual(self.views["w2"], _with("web-app-w2", "two"))

    def test_a_reader_of_two_lockstep_writers_resolves_one_write(self) -> None:
        self.assertIn(
            self.views["r2"],
            [_with("web-app-w1", "one"), _with("web-app-w2", "two")],
        )


if __name__ == "__main__":
    unittest.main()
