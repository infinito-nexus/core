from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from ansible.plugins.filter.core import to_bool
from jinja2 import Environment, StrictUndefined, UndefinedError, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT
from ._fake_bao import install, read_state, run, write_state

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
SCRIPT = ROLE_DIR / "files/shell/erase-tree.sh"
A = "ws-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
B = "ws-9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f"
SEEDED = {
    "tenant": {
        f"{A}/ssh": ["v1", "v2", "v3"],
        f"{A}/apps/nextcloud/admin": ["v1"],
        f"{A}/apps/nextcloud/db": ["v1", "v2"],
        f"{A}-provision/dns": ["v1"],
        f"{B}/ssh": ["v1"],
        f"{B}-provision/dns": ["v1", "v2"],
    },
    "platform": {"store/hostkeys/" + A + "/host/22": ["v1"]},
}


def erase(scratch: Path, prefix: str, **env: str) -> Any:
    return run(
        ["sh", str(SCRIPT), "tenant", prefix],
        {**install(scratch), **env},
    )


def destroy_tasks() -> list[dict[str, Any]]:
    return load_yaml_any(str(ROLE_DIR / "tasks/workspace/destroy.yml"))


def guard_passes(**facts: Any) -> bool:
    """Args:
    facts: the facts the guard of ``tasks/workspace/destroy.yml`` sees.

    Returns:
        Whether every condition of the guard holds; an undefined fact fails it
        as Ansible's ``assert`` does.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    try:
        return all(
            env.compile_expression(condition)(**facts)
            for condition in destroy_tasks()[0]["ansible.builtin.assert"]["that"]
        )
    except UndefinedError:
        return False


def state_objects_task() -> dict[str, Any]:
    return next(
        task
        for task in load_yaml_any(
            str(
                PROJECT_ROOT
                / "roles/web-svc-seaweedfs/tasks/utils/workspace/destroy.yml"
            )
        )
        if "workspace_state_objects" in task.get("ansible.builtin.set_fact", {})
    )


def produced_state_objects(present: bool, state_files: list[str]) -> Any:
    """Args:
    present: whether the workspace bucket is still there.
    state_files: what ``seaweedfs_bucket_state_files`` finds in the listing.

    Returns:
        ``workspace_state_objects`` as the SeaweedFS destroy renders it, with
        native types as ansible-core renders a lone expression.
    """
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters["seaweedfs_bucket_state_files"] = lambda _listing: state_files
    env.filters["bool"] = to_bool
    return env.from_string(
        state_objects_task()["ansible.builtin.set_fact"]["workspace_state_objects"]
    ).render(
        _seaweedfs_ws_bucket_present=present,
        _seaweedfs_ws_objects={"stdout": ""},
    )


class TestDestroyErasesTheWorkspaceSecrets(unittest.TestCase):
    def setUp(self) -> None:
        self._scratch = tempfile.TemporaryDirectory()
        self.scratch = Path(self._scratch.name)
        install(self.scratch)
        write_state(self.scratch, SEEDED)

    def tearDown(self) -> None:
        self._scratch.cleanup()

    def test_destroy_erases_every_version_below_both_prefixes(self) -> None:
        for prefix in (f"{A}/", f"{A}-provision/"):
            completed = erase(self.scratch, prefix)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("OPENBAO_CHANGED", completed.stdout)
        remaining = read_state(self.scratch)["kv"]["tenant"]
        self.assertEqual(
            remaining,
            {f"{B}/ssh": ["v1"], f"{B}-provision/dns": ["v1", "v2"]},
        )

    def test_every_key_goes_through_its_metadata(self) -> None:
        erase(self.scratch, f"{A}/")
        self.assertEqual(
            sorted(read_state(self.scratch)["deleted"]),
            sorted(
                f"tenant/{key}" for key in SEEDED["tenant"] if key.startswith(f"{A}/")
            ),
        )

    def test_the_prefix_of_one_workspace_never_reaches_a_longer_id(self) -> None:
        erase(self.scratch, f"{A}/")
        self.assertIn(f"{A}-provision/dns", read_state(self.scratch)["kv"]["tenant"])

    def test_an_erased_workspace_erases_again_without_change(self) -> None:
        erase(self.scratch, f"{A}/")
        completed = erase(self.scratch, f"{A}/")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("OPENBAO_CHANGED", completed.stdout)

    def test_a_refused_listing_fails_the_destroy(self) -> None:
        completed = erase(self.scratch, f"{A}/", FAKE_BAO_DENY="1")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(f"{A}/ssh", read_state(self.scratch)["kv"]["tenant"])

    def test_a_prefix_without_its_slash_is_refused(self) -> None:
        completed = erase(self.scratch, A)
        self.assertEqual(completed.returncode, 64)
        self.assertEqual(read_state(self.scratch)["deleted"], [])

    def test_no_secret_value_reaches_the_output(self) -> None:
        completed = erase(self.scratch, f"{A}/")
        for version in ("v1", "v2", "v3"):
            self.assertNotIn(version, completed.stdout + completed.stderr)


class TestTheDestroyOrder(unittest.TestCase):
    def test_destroy_removes_nothing_while_state_remains(self) -> None:
        tasks = destroy_tasks()
        guard = tasks[0]["ansible.builtin.assert"]["that"]
        env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        for count, accepted in ((0, True), (1, False), ("0", False)):
            with self.subTest(count=count):
                self.assertEqual(
                    all(
                        env.compile_expression(condition)(workspace_state_objects=count)
                        for condition in guard
                    ),
                    accepted,
                )

    def test_the_guard_takes_only_the_integer_the_seaweedfs_destroy_produces(
        self,
    ) -> None:
        task = state_objects_task()
        self.assertIs(task["delegate_facts"], True)
        self.assertEqual(task["loop"], "{{ ansible_play_hosts_all }}")
        for present, files, accepted in (
            (False, ["x.tfstate"], True),
            (True, [], True),
            (True, ["x.tfstate"], False),
        ):
            with self.subTest(present=present, files=files):
                produced = produced_state_objects(present, files)
                self.assertIsInstance(produced, int)
                self.assertEqual(
                    guard_passes(workspace_state_objects=produced), accepted
                )
        self.assertFalse(guard_passes(), "an undefined count must refuse")
        self.assertFalse(guard_passes(workspace_state_objects="0"))

    def test_the_key_goes_after_the_roles_and_the_secrets(self) -> None:
        registers = [task.get("register") for task in destroy_tasks()]
        key = registers.index("openbao_workspace_key_delete")
        self.assertLess(registers.index("openbao_workspace_role_delete"), key)
        self.assertLess(registers.index("openbao_workspace_erase"), key)

    def test_the_erasure_covers_every_prefix_of_the_workspace(self) -> None:
        task = next(
            task
            for task in destroy_tasks()
            if task.get("register") == "openbao_workspace_erase"
        )
        self.assertEqual(
            task["loop"],
            ["ws-{{ WORKSPACE }}/", "ws-{{ WORKSPACE }}-provision/"],
        )
        self.assertEqual(
            task["args"]["stdin"], "{{ lookup('file', 'shell/erase-tree.sh') }}"
        )

    def test_destroy_deletes_every_role_of_the_workspace(self) -> None:
        task = next(
            task
            for task in destroy_tasks()
            if task.get("register") == "openbao_workspace_role_delete"
        )
        self.assertEqual(
            task["loop"],
            [
                "{{ OPENBAO_JWT_MOUNT }}/role/ws-{{ WORKSPACE }}",
                "{{ OPENBAO_JWT_MOUNT }}/role/ws-{{ WORKSPACE }}-provision",
                "{{ OPENBAO_JWT_EXPORT_MOUNT }}/role/ws-{{ WORKSPACE }}",
            ],
        )


if __name__ == "__main__":
    unittest.main()
