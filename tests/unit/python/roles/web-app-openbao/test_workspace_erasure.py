from __future__ import annotations

import re
import shlex
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
TOKEN_ROLE = {
    "allowed_policies": "$p",
    "disallowed_policies": "default",
    "orphan": "false",
    "renewable": "false",
    "token_explicit_max_ttl": "{{ OPENBAO_JWT_TOKEN_TTL.provision }}",
    "token_no_default_policy": "true",
}
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


CHILD_POLICY = "p=ws-{{ WORKSPACE }}-{{ item.suffix }};"


def task_of(tasks: list[dict[str, Any]], register: str) -> dict[str, Any]:
    return next(task for task in tasks if task.get("register") == register)


def apply_task(register: str) -> dict[str, Any]:
    return task_of(load_yaml_any(str(ROLE_DIR / "tasks/workspace/apply.yml")), register)


def apply_task_shell(register: str) -> str:
    return apply_task(register)["ansible.builtin.shell"]


def child_task_shell() -> str:
    return apply_task_shell("openbao_workspace_child_policy")


def policy_script(shell: str, **facts: Any) -> tuple[str, list[str]]:
    """
    Args:
        shell: the command of a policy task, rendered for workspace ``A``.
        facts: the loop variables the command reads.

    Returns:
        The policy name its script sets ``p`` to, and the script's statements.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["quote"] = shlex.quote
    rendered = env.from_string(shell).render(
        OPENBAO_LOCAL_CID="openbao", WORKSPACE=A.removeprefix("ws-"), **facts
    )
    statements = [part.strip() for part in shlex.split(rendered)[-1].split(";")]
    (name,) = [part.removeprefix("p=") for part in statements if part.startswith("p=")]
    return name, statements


def token_role_findings(shell: str) -> list[str]:
    """
    Args:
        shell: the command of the apply task that writes the transit policy and
            the DNS broker caller policy.

    Returns:
        A missing write of the token role ``$p-child`` of that policy, and each
        field of it that differs from ``TOKEN_ROLE`` or that it adds.
    """
    if "r=auth/token/roles/$p-child;" not in shell:
        return ["no token role $p-child"]
    written = shell.split("bao write $r ", 1)[1].split(" >/dev/null", 1)[0]
    fields = dict(re.findall(r"(\w+)=(\{\{ [^}]+ \}\}|\S+)", written))
    differing = [
        f"{key}={fields.get(key)}"
        for key, value in TOKEN_ROLE.items()
        if fields.get(key) != value
    ]
    return differing + [f"{key} added" for key in fields if key not in TOKEN_ROLE]


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

    def test_destroy_erases_the_monitoring_tree_with_its_tombstones_and_hosts(
        self,
    ) -> None:
        write_state(
            self.scratch,
            {
                "monitoring": {
                    f"{A}/released/203.0.113.10": ["v1"],
                    f"{A}/federation/203.0.113.10": ["v1"],
                    f"{A}/labels/wiki": ["v1"],
                    f"{B}/released/203.0.113.11": ["v1"],
                },
                "platform": {
                    f"monitoring/federation/{A}/203.0.113.10": ["v1"],
                    f"monitoring/federation/{B}/203.0.113.11": ["v1"],
                    f"monitoring/inventory/{A}/hosts/203.0.113.10": ["v1"],
                    f"monitoring/inventory/{B}/hosts/203.0.113.11": ["v1"],
                    f"monitoring/inventory/{A}": ["v1"],
                },
            },
        )
        task = task_of(destroy_tasks(), "openbao_workspace_monitoring_erase")
        self.assertEqual(
            task["args"]["stdin"], "{{ lookup('file', 'shell/erase-tree.sh') }}"
        )
        self.assertIn(
            "{{ item.mount | quote }} {{ item.prefix | quote }}",
            task["ansible.builtin.shell"],
        )
        variables = {
            "OPENBAO_MONITORING_MOUNT": "monitoring",
            "OPENBAO_PLATFORM_MOUNT": "platform",
            "OPENBAO_MONITORING_PREFIX": "monitoring",
            "WORKSPACE": A.removeprefix("ws-"),
        }
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        for item in task["loop"]:
            mount, prefix = (
                environment.from_string(item[name]).render(variables)
                for name in ("mount", "prefix")
            )
            completed = run(["sh", str(SCRIPT), mount, prefix], install(self.scratch))
            self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            read_state(self.scratch)["kv"],
            {
                "monitoring": {f"{B}/released/203.0.113.11": ["v1"]},
                "platform": {
                    f"monitoring/federation/{B}/203.0.113.11": ["v1"],
                    f"monitoring/inventory/{B}/hosts/203.0.113.11": ["v1"],
                    f"monitoring/inventory/{A}": ["v1"],
                },
            },
        )

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
                "{{ OPENBAO_JWT_MOUNT }}/role/ws-{{ WORKSPACE }}-zone",
                "{{ OPENBAO_JWT_EXPORT_MOUNT }}/role/ws-{{ WORKSPACE }}",
                "token/roles/ws-{{ WORKSPACE }}-transit-child",
                "token/roles/ws-{{ WORKSPACE }}-dns-child",
            ],
        )

    def test_apply_writes_the_token_roles_that_alone_mint_each_child(self) -> None:
        task = apply_task("openbao_workspace_child_policy")
        self.assertEqual(
            [(item["suffix"], item["policy"]) for item in task["loop"]],
            [
                ("transit", "workspace/transit_policy.hcl.j2"),
                ("dns", "workspace/dns_policy.hcl.j2"),
            ],
        )
        self.assertIn(CHILD_POLICY, task["ansible.builtin.shell"])
        self.assertEqual(token_role_findings(task["ansible.builtin.shell"]), [])

    def test_control_a_child_role_that_keeps_default_is_found(self) -> None:
        shell = child_task_shell()
        planted = shell.replace(
            "token_no_default_policy=true", "token_no_default_policy=false"
        )
        self.assertNotEqual(planted, shell)
        self.assertEqual(
            token_role_findings(planted), ["token_no_default_policy=false"]
        )

    def test_destroy_drops_the_platform_records_apply_pins_after_the_key(
        self,
    ) -> None:
        self.assertIn(
            "p={{ OPENBAO_DNS_SCOPE_PREFIX }}/ws-{{ WORKSPACE }};",
            apply_task_shell("openbao_workspace_dns_scope"),
        )
        dropped = task_of(destroy_tasks(), "openbao_workspace_record_delete")
        self.assertEqual(
            dropped["loop"],
            [
                "{{ OPENBAO_OWNER_RECORD_PREFIX }}",
                "{{ OPENBAO_DNS_SCOPE_PREFIX }}",
                "{{ OPENBAO_TRANSIT_RECORD_PREFIX }}",
            ],
        )
        registers = [task.get("register") for task in destroy_tasks()]
        self.assertEqual(registers.count("openbao_workspace_record_delete"), 1)
        self.assertLess(
            registers.index("openbao_workspace_key_delete"),
            registers.index("openbao_workspace_record_delete"),
        )
        self.assertIn(
            "p={{ item }}/ws-{{ WORKSPACE }};", dropped["ansible.builtin.shell"]
        )
        self.assertIn("bao kv metadata delete", dropped["ansible.builtin.shell"])

    def test_control_a_renewable_token_role_is_found(self) -> None:
        shell = child_task_shell()
        planted = shell.replace("renewable=false", "renewable=true")
        self.assertNotEqual(planted, shell)
        self.assertEqual(token_role_findings(planted), ["renewable=true"])

    def test_destroy_deletes_the_zone_transit_and_dns_policies_apply_writes(
        self,
    ) -> None:
        self.assertIn(
            "p=ws-{{ WORKSPACE }}-zone;",
            apply_task_shell("openbao_workspace_zone_policy"),
        )
        child = apply_task("openbao_workspace_child_policy")
        self.assertIn(CHILD_POLICY, child["ansible.builtin.shell"])
        self.assertEqual([item["suffix"] for item in child["loop"]], ["transit", "dns"])
        deleted = task_of(destroy_tasks(), "openbao_workspace_zone_policy_delete")
        self.assertEqual(deleted["loop"], ["zone", "transit", "dns"])
        self.assertIn(
            "p=ws-{{ WORKSPACE }}-{{ item }};", deleted["ansible.builtin.shell"]
        )
        self.assertIn("bao policy delete $p", deleted["ansible.builtin.shell"])

    def test_destroy_deletes_the_provision_policy_apply_writes(self) -> None:
        written, _ = policy_script(
            apply_task_shell("openbao_workspace_provision_policy"), openbao_provider=""
        )
        deleted, statements = policy_script(
            task_of(destroy_tasks(), "openbao_workspace_provision_policy_delete")[
                "ansible.builtin.shell"
            ]
        )
        self.assertEqual((written, deleted), (f"{A}-provision", f"{A}-provision"))
        self.assertIn("bao policy delete $p >/dev/null", statements)

    def test_the_key_goes_after_the_provider_roles(self) -> None:
        registers = [task.get("register") for task in destroy_tasks()]
        self.assertLess(
            registers.index("openbao_workspace_provider_role_delete"),
            registers.index("openbao_workspace_key_delete"),
        )


if __name__ == "__main__":
    unittest.main()
