from __future__ import annotations

import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT
from ._fake_bao import install, run

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
WORKSPACE = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["quote"] = shlex.quote
    env.filters["from_json"] = json.loads
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    return env


def apply_tasks() -> list[dict[str, Any]]:
    return load_yaml_any(str(ROLE_DIR / "tasks/workspace/apply.yml"))


def backup_block() -> dict[str, Any]:
    return next(task for task in apply_tasks() if "block" in task)


def block_task(register: str) -> dict[str, Any]:
    return next(
        task for task in backup_block()["block"] if task.get("register") == register
    )


def snapshot(scratch: Path, mode: str) -> tuple[dict[str, Any], bool]:
    """
    Args:
        scratch: the directory the fakes and the snapshot directory live in.
        mode: what the fake ``bao operator raft snapshot save`` does: ``ok``,
            ``fail`` or ``empty``.

    Returns:
        What the snapshot task registers, and whether its ``failed_when`` holds.
    """
    task = block_task("openbao_workspace_snapshot")
    command = (
        environment()
        .from_string(task["ansible.builtin.shell"])
        .render(
            OPENBAO_RAFT_SNAPSHOT_DIR=str(scratch / "raft"),
            OPENBAO_LOCAL_CID="openbao-cid",
            WORKSPACE=WORKSPACE,
        )
    )
    (scratch / "raft").mkdir(exist_ok=True)
    env = {**install(scratch), "FAKE_BAO_SNAPSHOT": mode}
    completed = run(["sh", "-c", command], env)
    result = {"rc": completed.returncode, "stdout": completed.stdout}
    failed = environment().compile_expression(task["failed_when"])(
        openbao_workspace_snapshot=result
    )
    return result, bool(failed)


class TestTheSnapshotFollowsTheKey(unittest.TestCase):
    def test_apply_fails_without_a_snapshot(self) -> None:
        for mode in ("fail", "empty"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as scratch:
                _, failed = snapshot(Path(scratch), mode)
                self.assertTrue(failed)
                self.assertEqual(list((Path(scratch) / "raft").iterdir()), [])

    def test_a_written_snapshot_lands_in_the_backup_directory(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            result, failed = snapshot(Path(scratch), "ok")
            self.assertFalse(failed, result)
            written = list((Path(scratch) / "raft").iterdir())
            self.assertEqual(len(written), 1)
            self.assertRegex(
                written[0].name, rf"^ws-{WORKSPACE}-\d{{8}}T\d{{6}}Z\.snap$"
            )
            self.assertEqual(
                written[0].read_bytes(),  # nocheck: cache-read tempdir
                b"raft-snapshot-bytes",
            )
            self.assertEqual(written[0].stat().st_mode & 0o077, 0)

    def test_every_new_key_and_every_missing_record_takes_a_snapshot(self) -> None:
        self.assertEqual(
            backup_block()["when"],
            "(openbao_workspace_key is changed) or (openbao_workspace_record.rc != 0)",
        )

    def test_the_record_follows_the_snapshot_and_names_the_newest_key(self) -> None:
        registers = [task.get("register") for task in apply_tasks()]
        self.assertLess(
            registers.index("openbao_workspace_key"),
            registers.index("openbao_workspace_record"),
        )
        names = [task["name"] for task in backup_block()["block"]]
        self.assertEqual(len(names), 3)
        self.assertIn("raft snapshot", names[1])
        self.assertIn("Record", names[2])
        record = backup_block()["block"][2]["ansible.builtin.shell"]
        rendered = (
            environment()
            .from_string(record)
            .render(
                OPENBAO_LOCAL_CID="openbao-cid",
                OPENBAO_PLATFORM_MOUNT="platform",
                OPENBAO_TRANSIT_RECORD_PREFIX="provision/transit",
                WORKSPACE=WORKSPACE,
                openbao_workspace_key_info={
                    "stdout": json.dumps(
                        {"data": {"keys": {"1": 1731500000, "2": 1731600000}}}
                    )
                },
                openbao_workspace_snapshot={"stdout": "1731600005\n"},
            )
        )
        self.assertIn(f"platform provision/transit/ws-{WORKSPACE}", rendered)
        self.assertIn("key_created_at=1731600000", rendered)
        self.assertIn("snapshot_at=1731600005", rendered)


class TestTheTransitKey(unittest.TestCase):
    def test_apply_creates_a_non_exportable_key_once(self) -> None:
        task = next(
            task
            for task in apply_tasks()
            if task.get("register") == "openbao_workspace_key"
        )
        command = task["ansible.builtin.shell"]
        self.assertIn("bao read $k >/dev/null 2>&1 && exit 0", command)
        self.assertIn(
            "type=aes256-gcm96 exportable=false allow_plaintext_backup=false", command
        )

    def test_apply_fails_on_a_key_that_could_leave_openbao(self) -> None:
        task = next(
            task
            for task in apply_tasks()
            if task.get("register") == "openbao_workspace_key_info"
        )
        check = environment().compile_expression(task["failed_when"])
        safe = {"exportable": False, "allow_plaintext_backup": False}
        for flag in ("exportable", "allow_plaintext_backup", "deletion_allowed"):
            with self.subTest(flag=flag):
                data = {**safe, "deletion_allowed": False, flag: True}
                self.assertTrue(
                    check(
                        openbao_workspace_key_info={
                            "rc": 0,
                            "stdout": json.dumps({"data": data}),
                        }
                    )
                )
        data = {**safe, "deletion_allowed": False}
        self.assertFalse(
            check(
                openbao_workspace_key_info={
                    "rc": 0,
                    "stdout": json.dumps({"data": data}),
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
