from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from ._fake_bao import install, read_state, run, write_access, write_state

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
PRUNE = ROLE_DIR / "files/shell/prune-provider-access.sh"
DROP = ROLE_DIR / "files/shell/drop-shared-provision.sh"
A = "ws-0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
B = "ws-9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f"
C = "ws-5c4b3a29-1807-4f6e-9d5c-4b3a29180706"
SHARED = "provision-shared"
UNLOCK_AND_DNS = {"project_id": 7, "template_id": [73, 74]}
EVERY_TEMPLATE = {"project_id": 7, "template_id": [71, 72, 73, 74]}


def held(*policies: str) -> dict[str, Any]:
    return {"token_policies": list(policies)}


def provision(bound: dict[str, Any], *policies: str) -> dict[str, Any]:
    return {**held(*policies), "bound_claims": bound}


def child(*allowed: str) -> dict[str, Any]:
    return {"allowed_policies": list(allowed)}


ROLES = {
    f"auth/jwt/role/{A}": held("tenant"),
    f"auth/jwt/role/{A}-provision": provision(EVERY_TEMPLATE, "tenant", SHARED),
    f"auth/jwt/role/{A}-provision-hetzner": held(f"{A}-provision-hetzner"),
    f"auth/jwt/role/{A}-provision-retired": held(f"{A}-provision-retired"),
    f"auth/jwt/role/{A}-zone": held(f"{A}-zone"),
    f"auth/jwt/role/{B}-provision": provision(UNLOCK_AND_DNS, f"{B}-provision"),
    f"auth/jwt/role/{B}-provision-retired": held(f"{B}-provision-retired"),
    f"auth/jwt/role/{C}-provision": provision(EVERY_TEMPLATE, f"{C}-provision"),
    "auth/jwt/role/members": held("members"),
    f"auth/token/roles/{A}-transit-child": child(f"{A}-transit", f"{A}-provision"),
    f"auth/token/roles/{B}-transit-child": child(f"{B}-transit"),
    "auth/token/roles/store": child("store-credentials"),
}
POLICIES = [
    "default",
    "root",
    "tenant",
    SHARED,
    f"{A}-provision",
    f"{A}-provision-hetzner",
    f"{A}-provision-retired",
    f"{A}-zone",
    f"{B}-provision",
    f"{B}-provision-retired",
]


def task_of(path: Path, register: str) -> dict[str, Any]:
    return next(
        task for task in load_yaml_any(str(path)) if task.get("register") == register
    )


def orphans(state: dict[str, Any], workspace: str) -> list[str]:
    """
    Args:
        state: the fake OpenBao state after a prune.
        workspace: ``ws-<id>``.

    Returns:
        Every provider role and policy of the workspace still held.
    """
    prefix = f"{workspace}-provision-"
    roles = [
        path for path in state["roles"] if path.startswith("auth/jwt/role/" + prefix)
    ]
    return roles + [name for name in state["policies"] if name.startswith(prefix)]


def shared_findings(state: dict[str, Any]) -> list[str]:
    """
    Args:
        state: the fake OpenBao state after the deploy step.

    Returns:
        One finding for the shared policy if it is still held, one per
        ``ws-<id>-provision`` role whose policies are not exactly its own or
        that binds other than two templates, and one per
        ``ws-<id>-transit-child`` token role that allows other than
        ``ws-<id>-transit``.
    """
    findings = [f"policy {SHARED} remains"] if SHARED in state["policies"] else []
    for path, role in state["roles"].items():
        name = path.rsplit("/", 1)[1]
        if name.endswith("-transit-child"):
            allowed = [name.removesuffix("-child")]
            if role["allowed_policies"] != allowed:
                findings.append(f"{name} allows {role['allowed_policies']}")
        if not name.endswith("-provision"):
            continue
        if role["token_policies"] != [name]:
            findings.append(f"{name} names {role['token_policies']}")
        elif len(role["bound_claims"]["template_id"]) != 2:
            findings.append(f"{name} binds {role['bound_claims']['template_id']}")
    return findings


class AccessCase(unittest.TestCase):
    def setUp(self) -> None:
        self._scratch = tempfile.TemporaryDirectory()
        self.scratch = Path(self._scratch.name)
        install(self.scratch)
        write_state(self.scratch, {})
        write_access(self.scratch, ROLES, POLICIES)

    def tearDown(self) -> None:
        self._scratch.cleanup()

    def run_script(self, script: Path, *args: str, **env: str) -> Any:
        return run(["sh", str(script), *args], {**install(self.scratch), **env})

    def planted(self, script: Path, old: str, new: str) -> Path:
        source = read_text(str(script))
        text = source.replace(old, new)
        self.assertNotEqual(text, source)
        path = self.scratch / script.name
        path.write_text(text, encoding="utf-8")
        return path

    def removed(self) -> list[str]:
        return read_state(self.scratch).get("removed", [])


class TestTheProviderPrune(AccessCase):
    def test_apply_prunes_only_the_providers_the_table_dropped(self) -> None:
        completed = self.run_script(PRUNE, "jwt", A, "hetzner", "incus")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("OPENBAO_CHANGED", completed.stdout)
        self.assertEqual(
            self.removed(),
            [
                f"auth/jwt/role/{A}-provision-retired",
                f"policy/{A}-provision-retired",
            ],
        )

    def test_a_second_apply_prunes_nothing(self) -> None:
        self.run_script(PRUNE, "jwt", A, "hetzner")
        completed = self.run_script(PRUNE, "jwt", A, "hetzner")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("OPENBAO_CHANGED", completed.stdout)

    def test_destroy_removes_every_provider_role_and_policy_of_its_workspace(
        self,
    ) -> None:
        completed = self.run_script(PRUNE, "jwt", A)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        state = read_state(self.scratch)
        self.assertEqual(orphans(state, A), [])
        self.assertEqual(
            sorted(orphans(state, B)),
            [f"auth/jwt/role/{B}-provision-retired", f"{B}-provision-retired"],
        )
        for kept in (f"{A}-provision", f"{A}-zone", "members"):
            with self.subTest(kept=kept):
                self.assertIn(f"auth/jwt/role/{kept}", state["roles"])
        self.assertIn(f"{A}-provision", state["policies"])

    def test_negative_control_a_prune_by_the_table_leaves_a_retired_provider(
        self,
    ) -> None:
        script = self.planted(PRUNE, '"$prefix"*) ;;', '"$prefix"hetzner) ;;')
        completed = self.run_script(script, "jwt", A)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotEqual(orphans(read_state(self.scratch), A), [])

    def test_negative_control_a_prune_without_its_deletes_leaves_orphans(
        self,
    ) -> None:
        for old in (
            'bao delete "auth/$mount/role/$role"',
            'bao policy delete "$policy"',
        ):
            with self.subTest(planted=old):
                write_access(self.scratch, ROLES, POLICIES)
                script = self.planted(PRUNE, old, "true")
                completed = self.run_script(script, "jwt", A)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertNotEqual(orphans(read_state(self.scratch), A), [])

    def test_a_refused_listing_fails_the_prune(self) -> None:
        completed = self.run_script(PRUNE, "jwt", A, FAKE_BAO_DENY="1")
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(self.removed(), [])

    def test_a_call_without_a_workspace_is_refused(self) -> None:
        for args in (("jwt",), ("jwt", A.removeprefix("ws-")), ("jwt", "ws-")):
            with self.subTest(args=args):
                completed = self.run_script(PRUNE, *args)
                self.assertEqual(completed.returncode, 64)
                self.assertEqual(self.removed(), [])


class TestTheSharedPolicyRetirement(AccessCase):
    def test_deploy_retires_the_shared_policy_and_each_role_naming_it(self) -> None:
        completed = self.run_script(DROP, "jwt")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("OPENBAO_CHANGED", completed.stdout)
        state = read_state(self.scratch)
        self.assertEqual(shared_findings(state), [])
        self.assertEqual(
            self.removed(),
            [
                f"policy/{SHARED}",
                f"auth/jwt/role/{A}-provision",
                f"auth/jwt/role/{C}-provision",
                f"auth/token/roles/{A}-transit-child",
            ],
        )
        for kept in (
            f"auth/jwt/role/{B}-provision",
            f"auth/token/roles/{B}-transit-child",
            "auth/token/roles/store",
        ):
            with self.subTest(kept=kept):
                self.assertIn(kept, state["roles"])

    def test_a_second_deploy_changes_nothing(self) -> None:
        self.run_script(DROP, "jwt")
        completed = self.run_script(DROP, "jwt")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("OPENBAO_CHANGED", completed.stdout)

    def test_negative_control_a_kept_role_still_names_the_shared_policy(self) -> None:
        script = self.planted(DROP, 'bao delete "$path"', "true")
        self.run_script(script, "jwt")
        self.assertEqual(
            shared_findings(read_state(self.scratch)),
            [
                f"{A}-provision names ['tenant', '{SHARED}']",
                f"{C}-provision binds [71, 72, 73, 74]",
            ],
        )

    def test_negative_control_a_drop_by_policies_alone_keeps_every_template(
        self,
    ) -> None:
        script = self.planted(DROP, ' || [ "$bound" != 2 ]', "")
        completed = self.run_script(script, "jwt")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            shared_findings(read_state(self.scratch)),
            [f"{C}-provision binds [71, 72, 73, 74]"],
        )

    def test_negative_control_a_kept_token_role_still_allows_more(self) -> None:
        script = self.planted(DROP, 'bao delete "auth/token/roles/$role"', "true")
        completed = self.run_script(script, "jwt")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            shared_findings(read_state(self.scratch)),
            [f"{A}-transit-child allows ['{A}-transit', '{A}-provision']"],
        )

    def test_negative_control_a_kept_policy_is_found(self) -> None:
        script = self.planted(DROP, "bao policy delete provision-shared", "true")
        self.run_script(script, "jwt")
        self.assertIn(
            f"policy {SHARED} remains", shared_findings(read_state(self.scratch))
        )

    def test_a_refused_listing_fails_the_deploy(self) -> None:
        completed = self.run_script(DROP, "jwt", FAKE_BAO_DENY="1")
        self.assertNotEqual(completed.returncode, 0)

    def test_a_refused_policy_read_fails_the_deploy(self) -> None:
        completed = self.run_script(DROP, "jwt", FAKE_BAO_POLICY_DENY="1")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("permission denied", completed.stderr)
        self.assertEqual(self.removed(), [])

    def test_negative_control_a_drop_that_swallows_every_read_error_passes(
        self,
    ) -> None:
        script = self.planted(DROP, '*"No policy named"*) ;;', "*) ;;")
        completed = self.run_script(script, "jwt", FAKE_BAO_POLICY_DENY="1")
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_an_empty_jwt_mount_drops_the_policy_only(self) -> None:
        write_access(self.scratch, {}, ["default", SHARED])
        completed = self.run_script(DROP, "jwt")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self.removed(), [f"policy/{SHARED}"])

    def test_negative_control_an_empty_mount_read_as_an_error_fails(self) -> None:
        write_access(self.scratch, {}, ["default"])
        script = self.planted(
            DROP, '*"No value found"*) return 0 ;;', '*"No value found"*) return 1 ;;'
        )
        completed = self.run_script(script, "jwt")
        self.assertNotEqual(completed.returncode, 0)

    def test_the_deploy_runs_it_after_the_workspace_policies(self) -> None:
        path = ROLE_DIR / "tasks/07_workspaces.yml"
        registers = [task.get("register") for task in load_yaml_any(str(path))]
        self.assertLess(
            registers.index("openbao_tenancy_policy"),
            registers.index("openbao_shared_provision_drop"),
        )
        task = task_of(path, "openbao_shared_provision_drop")
        stdin = "{{ lookup('file', 'shell/drop-shared-provision.sh') }}"
        self.assertEqual(task["args"]["stdin"], stdin)
        self.assertIn(
            "sh -s -- {{ OPENBAO_JWT_MOUNT | quote }}", task["ansible.builtin.shell"]
        )

    def test_no_template_or_policy_list_brings_the_shared_policy_back(self) -> None:
        variables = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertNotIn(SHARED, variables["OPENBAO_TENANCY_POLICIES"])
        self.assertFalse(
            (ROLE_DIR / "templates/policies" / f"{SHARED}.hcl.j2").exists()
        )


class TestListedNamesStayLiteral(AccessCase):
    CASES = (
        (PRUNE, ("jwt", A, "hetzner"), f"{A}-provision-h*", f"{A}-provision-hetzner"),
        (DROP, ("jwt",), "ws-*-provision", "ws-0-provision"),
    )

    def run_globbed(self, script: Path, args: tuple[str, ...], role: str, file: str):
        write_access(
            self.scratch,
            {**ROLES, f"auth/jwt/role/{role}": provision(EVERY_TEMPLATE, "tenant")},
            POLICIES,
        )
        (self.scratch / file).write_text("", encoding="utf-8")
        return run(["sh", str(script), *args], install(self.scratch), cwd=self.scratch)

    def test_a_listed_name_with_a_glob_character_is_never_expanded(self) -> None:
        for script, args, role, file in self.CASES:
            with self.subTest(script=script.name):
                completed = self.run_globbed(script, args, role, file)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn(f"auth/jwt/role/{role}", self.removed())

    def test_negative_control_a_script_without_set_f_expands_the_name(self) -> None:
        for script, args, role, file in self.CASES:
            with self.subTest(script=script.name):
                planted = self.planted(script, "set -euf", "set -eu")
                self.run_globbed(planted, args, role, file)
                self.assertNotIn(f"auth/jwt/role/{role}", self.removed())


class TestThePruneWiring(unittest.TestCase):
    def test_apply_keeps_the_table_and_destroy_keeps_no_provider(self) -> None:
        tasks = ROLE_DIR / "tasks/workspace"
        apply = task_of(tasks / "apply.yml", "openbao_workspace_provider_prune")
        destroy = task_of(
            tasks / "destroy.yml", "openbao_workspace_provider_role_delete"
        )
        stdin = "{{ lookup('file', 'shell/prune-provider-access.sh') }}"
        for task in (apply, destroy):
            with self.subTest(task=task["name"]):
                self.assertEqual(task["args"]["stdin"], stdin)
        table = "{{ OPENBAO_PROVISION_SECRETS | list | map('quote') | join(' ') }}"
        workspace = "ws-{{ WORKSPACE }}"
        applied = apply["ansible.builtin.shell"].rstrip()
        self.assertTrue(applied.endswith(f"{workspace} {table}"))
        self.assertTrue(destroy["ansible.builtin.shell"].rstrip().endswith(workspace))


if __name__ == "__main__":
    unittest.main()
