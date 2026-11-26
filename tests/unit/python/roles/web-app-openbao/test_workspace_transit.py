from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT
from ._fake_bao import install, read_state, run

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


def snapshot(
    scratch: Path, mode: str, keep: int, older: list[str]
) -> tuple[dict[str, Any], bool]:
    """
    Args:
        scratch: the directory the fakes and the snapshot directory live in.
        mode: what the fake ``bao operator raft snapshot save`` does: ``ok``,
            ``fail`` or ``empty``.
        keep: the ``OPENBAO_RAFT_SNAPSHOT_KEEP`` the task renders with.
        older: names of snapshots already in the directory, oldest first.

    Returns:
        What the snapshot task registers, and whether its ``failed_when`` holds.
    """
    task = block_task("openbao_workspace_snapshot")
    command = (
        environment()
        .from_string(task["ansible.builtin.shell"])
        .render(
            OPENBAO_RAFT_SNAPSHOT_DIR=str(scratch / "raft"),
            OPENBAO_RAFT_SNAPSHOT_KEEP=str(keep),
            OPENBAO_LOCAL_CID="openbao-cid",
            WORKSPACE=WORKSPACE,
        )
    )
    (scratch / "raft").mkdir(exist_ok=True)
    for age, name in enumerate(reversed(older), start=1):
        path = scratch / "raft" / name
        path.write_bytes(b"older-snapshot")
        os.utime(path, (path.stat().st_atime - 60 * age,) * 2)
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
                _, failed = snapshot(Path(scratch), mode, 3, [])
                self.assertTrue(failed)
                self.assertEqual(list((Path(scratch) / "raft").iterdir()), [])

    def test_a_written_snapshot_lands_in_the_backup_directory(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            result, failed = snapshot(Path(scratch), "ok", 3, [])
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

    def test_only_the_newest_snapshots_stay(self) -> None:
        older = [f"ws-other-2026010{day}T000000Z.snap" for day in range(1, 5)]
        with tempfile.TemporaryDirectory() as scratch:
            result, failed = snapshot(Path(scratch), "ok", 2, older)
            self.assertFalse(failed, result)
            kept = sorted(path.name for path in (Path(scratch) / "raft").iterdir())
            self.assertEqual(len(kept), 2)
            self.assertIn(older[-1], kept)
            self.assertTrue(any(name.startswith(f"ws-{WORKSPACE}-") for name in kept))

    def test_a_directory_named_like_a_snapshot_is_not_listed_by_content(self) -> None:
        older = [f"ws-other-2026010{day}T000000Z.snap" for day in range(1, 4)]
        with tempfile.TemporaryDirectory() as scratch:
            nested = Path(scratch) / "raft" / "ws-nested.snap"
            nested.mkdir(parents=True)
            (nested / "inner").write_bytes(b"inner")
            os.utime(nested, (nested.stat().st_atime - 30,) * 2)
            result, failed = snapshot(Path(scratch), "ok", 2, older)
            self.assertFalse(failed, result)
            kept = sorted(path.name for path in (Path(scratch) / "raft").iterdir())
            self.assertEqual(len(kept), 2)
            self.assertIn("ws-nested.snap", kept)
            self.assertTrue((nested / "inner").exists())

    def test_fewer_snapshots_than_kept_are_all_left(self) -> None:
        older = ["ws-other-20260101T000000Z.snap"]
        with tempfile.TemporaryDirectory() as scratch:
            result, failed = snapshot(Path(scratch), "ok", 3, older)
            self.assertFalse(failed, result)
            self.assertEqual(len(list((Path(scratch) / "raft").iterdir())), 2)

    def test_only_a_whole_number_above_zero_reaches_the_prune(self) -> None:
        guard = next(
            task
            for task in apply_tasks()
            if "OPENBAO_RAFT_SNAPSHOT_KEEP" in str(task.get("ansible.builtin.assert"))
        )
        registers = [task.get("register") for task in apply_tasks()]
        self.assertLess(
            apply_tasks().index(guard),
            apply_tasks().index(backup_block()),
            registers,
        )
        checks = [
            environment().compile_expression(check)
            for check in guard["ansible.builtin.assert"]["that"]
        ]
        for keep, accepted in ((3, True), (1, True), (0, False), ("three", False)):
            with self.subTest(keep=keep):
                self.assertIs(
                    all(check(OPENBAO_RAFT_SNAPSHOT_KEEP=keep) for check in checks),
                    accepted,
                )

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
        command = (
            environment()
            .from_string(task["ansible.builtin.shell"])
            .render(
                OPENBAO_LOCAL_CID="openbao-cid",
                OPENBAO_TRANSIT_MOUNT="transit",
                WORKSPACE=WORKSPACE,
            )
        )
        key = f"transit/keys/ws-{WORKSPACE}-provision"
        with tempfile.TemporaryDirectory() as scratch:
            completed = run(["sh", "-c", command], install(Path(scratch)))
            state = read_state(Path(scratch))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.split(), ["OPENBAO_CHANGED"])
        self.assertEqual(state["writes"], [key])
        self.assertEqual(
            {
                field: state["config"][key][field]
                for field in ("type", "exportable", "allow_plaintext_backup")
            },
            {
                "type": "aes256-gcm96",
                "exportable": "false",
                "allow_plaintext_backup": "false",
            },
        )
        statements = [part.strip() for part in shlex.split(command)[-1].split(";")]
        self.assertEqual(statements[1], "bao read $k >/dev/null 2>&1 && exit 0")

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
