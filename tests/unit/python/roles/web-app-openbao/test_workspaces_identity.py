from __future__ import annotations

import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
ENTRY = {
    "project_id": 2,
    "template_id": 21,
    "git_url": "ssh://git@gitea.example.test/infinito/core.git",
    "git_branch": "main",
    "ssh_key_id": 4,
    "runner_tag": "workspaces",
}
IDENTITY = {
    "project_id": 2,
    "templates": {
        "workspace": ENTRY,
        "members": {**ENTRY, "template_id": 22},
        "user": {**ENTRY, "template_id": 23},
    },
}
UNWRAP = ".data | default({})).data | default({})"


def tasks() -> list[dict[str, Any]]:
    """Returns:
    The leaf tasks of the workspace file, each child of a block with the
    condition of the block ahead of its own.
    """
    leaves: list[dict[str, Any]] = []
    for task in load_yaml_any(str(ROLE_DIR / "tasks" / "07_workspaces.yml")):
        if "block" not in task:
            leaves.append(task)
            continue
        for child in task["block"]:
            own = child.get("when", [])
            when = [task["when"], *(own if isinstance(own, list) else [own])]
            leaves.append({**child, "when": when})
    return leaves


def task_named(fragment: str) -> dict[str, Any]:
    return next(task for task in tasks() if fragment in task.get("name", ""))


def stored(entry: dict[str, Any] | None) -> str:
    """Args:
        entry: the fields OpenBao holds at the path, None for no version.

    Returns:
        What ``bao kv get -format=json`` prints for it.
    """
    if entry is None:
        return ""
    return json.dumps({"data": {"data": entry, "metadata": {"version": 3}}})


def writes(entry: dict[str, Any] | None, condition: str | None = None) -> bool:
    """Args:
        entry: the fields OpenBao holds before the deploy.
        condition: the publish condition, the role's own by default.

    Returns:
        Whether the publish task runs.
    """
    condition = (
        condition or task_named("Publish the Workspaces project identity")["when"][1]
    )
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["from_json"] = json.loads
    rendered = environment.from_string("{{ " + condition + " }}").render(
        openbao_store_workspaces_read={"stdout": stored(entry)},
        semaphore_workspaces_identity=IDENTITY,
    )
    return rendered == "True"


def rotation_role(identity: dict[str, Any]) -> dict[str, Any]:
    """Args:
        identity: the fact ``semaphore_store_rotation_identity``.

    Returns:
        The body the deploy writes to ``auth/jwt/role/store-credentials``.
    """
    values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["to_json"] = json.dumps
    source = read_text(str(ROLE_DIR / "templates" / "store_credentials_role.json.j2"))
    return json.loads(
        environment.from_string(source).render(
            OPENBAO_JWT_AUDIENCE="openbao",
            OPENBAO_JWT_TOKEN_TTL={"deploy": "4h"},
            OPENBAO_STORE_CREDENTIALS_ROLE=values["OPENBAO_STORE_CREDENTIALS_ROLE"],
            semaphore_store_rotation_identity=identity,
        )
    )


def rotation_role_findings(body: dict[str, Any]) -> list[str]:
    claims = body["bound_claims"]
    findings = []
    if not isinstance(claims["project_id"], int):
        findings.append("project_id is no JSON number")
    if not all(isinstance(value, int) for value in claims["template_id"]):
        findings.append("template_id is no list of JSON numbers")
    if body["token_policies"] != ["store-credentials"] or body["user_claim"] != "sub":
        findings.append(
            "the role grants more than the rotation policy or shares an alias"
        )
    if body["bound_audiences"] != ["openbao"]:
        findings.append("the role binds no audience")
    return findings


class TestTheStoreRotationRole(unittest.TestCase):
    def test_the_role_binds_the_rotation_template_by_number(self) -> None:
        body = rotation_role({"project_id": 2, "template_id": 24})
        self.assertEqual(rotation_role_findings(body), [])
        self.assertEqual(body["bound_claims"], {"project_id": 2, "template_id": [24]})

    def test_control_a_string_template_id_fails(self) -> None:
        body = rotation_role({"project_id": 2, "template_id": "24"})
        self.assertEqual(
            rotation_role_findings(body), ["template_id is no list of JSON numbers"]
        )

    def test_the_deploy_writes_the_role_only_beside_the_fact_of_semaphore(self) -> None:
        for fragment in (
            "Require integer Semaphore ids of rotate",
            "Bind the task token role of rotate",
        ):
            with self.subTest(task=fragment):
                self.assertEqual(
                    task_named(fragment)["when"],
                    ["semaphore_store_rotation_identity is defined"],
                )
        self.assertIn(
            "store-credentials",
            load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))[
                "OPENBAO_TENANCY_POLICIES"
            ],
        )


SCHEDULE_IDENTITY = {
    "project_id": 9,
    "templates": {"announce owners": 95, "prune exports": 96},
}
SCHEDULE_BINDINGS = {
    "announce-owners": "announce owners",
    "prune-exports": "prune exports",
}
SCHEDULE_POLICIES = '"token_policies": ["export-shared"]'


def schedule_roles(
    identity: dict[str, Any],
    bindings: dict[str, str] | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Args:
        identity: the fact ``semaphore_export_schedule_identity``.
        bindings: ``OPENBAO_EXPORT_SCHEDULE_ROLES`` in place of the role's own.
        source: a template text in place of ``export_schedule_roles.json.j2``.

    Returns:
        The roles the deploy writes to ``auth/jwt-export``, each with name and body.
    """
    values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["to_json"] = json.dumps
    text = source or schedule_source()
    return json.loads(
        environment.from_string(text).render(
            OPENBAO_JWT_AUDIENCE="openbao",
            OPENBAO_JWT_TOKEN_TTL={"export": "1h"},
            OPENBAO_EXPORT_SCHEDULE_ROLES=bindings
            or values["OPENBAO_EXPORT_SCHEDULE_ROLES"],
            semaphore_export_schedule_identity=identity,
        )
    )


def schedule_source() -> str:
    return read_text(str(ROLE_DIR / "templates" / "export_schedule_roles.json.j2"))


def schedule_role_findings(
    entries: list[dict[str, Any]], identity: dict[str, Any]
) -> list[str]:
    """Args:
        entries: as ``schedule_roles`` returns them.
        identity: the fact they were rendered from.

    Returns:
        Every role beyond ``announce-owners`` and ``prune-exports``, and every
        binding of one other than the export project and its own template by
        number, with ``export-shared`` alone, audience ``openbao`` and claim ``sub``.
    """
    names = sorted(entry["name"] for entry in entries)
    findings = [] if names == sorted(SCHEDULE_BINDINGS) else [f"roles {names}"]
    for entry in entries:
        body, name = entry["body"], entry["name"]
        expected = {
            "project_id": identity["project_id"],
            "template_id": [identity["templates"].get(SCHEDULE_BINDINGS.get(name))],
        }
        claims = body["bound_claims"]
        if claims != expected or not all(
            type(value) is int
            for value in [claims["project_id"], *claims["template_id"]]
        ):
            findings.append(f"{name}: bound to {claims}")
        if body["token_policies"] != ["export-shared"]:
            findings.append(f"{name}: policies {body['token_policies']}")
        if body["bound_audiences"] != ["openbao"] or body["user_claim"] != "sub":
            findings.append(f"{name}: audience or claim")
    return findings


def schedule_accepts(identity: dict[str, Any]) -> bool:
    task = task_named("Require integer Semaphore ids of the scheduled export")
    values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return all(
        environment.compile_expression(condition)(
            semaphore_export_schedule_identity=identity,
            OPENBAO_EXPORT_SCHEDULE_ROLES=values["OPENBAO_EXPORT_SCHEDULE_ROLES"],
        )
        for condition in task["ansible.builtin.assert"]["that"]
    )


class TestTheExportScheduleRoles(unittest.TestCase):
    def test_each_role_binds_its_own_template_with_export_shared_alone(self) -> None:
        entries = schedule_roles(SCHEDULE_IDENTITY)
        self.assertEqual(schedule_role_findings(entries, SCHEDULE_IDENTITY), [])
        self.assertEqual(
            {e["name"]: e["body"]["bound_claims"]["template_id"] for e in entries},
            {"announce-owners": [95], "prune-exports": [96]},
        )

    def test_the_roles_name_the_templates_semaphore_schedules(self) -> None:
        spec = spec_from_file_location(
            "semaphore_project_schedule",
            str(PROJECT_ROOT / "roles/web-app-semaphore/files/python/project.py"),
        )
        project = module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(project)
        values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertEqual(values["OPENBAO_EXPORT_SCHEDULE_ROLES"], SCHEDULE_BINDINGS)
        self.assertEqual(
            sorted(SCHEDULE_BINDINGS.values()),
            sorted(e["name"] for e in project.EXPORT_SCHEDULED_TEMPLATES),
        )

    def test_control_a_role_bound_to_the_other_template_fails(self) -> None:
        swapped = {
            "announce-owners": "prune exports",
            "prune-exports": "announce owners",
        }
        entries = schedule_roles(SCHEDULE_IDENTITY, bindings=swapped)
        self.assertEqual(
            schedule_role_findings(entries, SCHEDULE_IDENTITY),
            [
                "announce-owners: bound to {'project_id': 9, 'template_id': [96]}",
                "prune-exports: bound to {'project_id': 9, 'template_id': [95]}",
            ],
        )

    def test_control_a_second_policy_fails(self) -> None:
        source = schedule_source().replace(
            SCHEDULE_POLICIES, '"token_policies": ["export-shared", "tenant-export"]'
        )
        self.assertNotEqual(source, schedule_source())
        findings = schedule_role_findings(
            schedule_roles(SCHEDULE_IDENTITY, source=source), SCHEDULE_IDENTITY
        )
        self.assertEqual(
            findings,
            [
                "announce-owners: policies ['export-shared', 'tenant-export']",
                "prune-exports: policies ['export-shared', 'tenant-export']",
            ],
        )

    def test_control_a_string_template_id_fails(self) -> None:
        identity = {
            **SCHEDULE_IDENTITY,
            "templates": {"announce owners": "95", "prune exports": 96},
        }
        self.assertEqual(
            schedule_role_findings(schedule_roles(identity), identity),
            ["announce-owners: bound to {'project_id': 9, 'template_id': ['95']}"],
        )

    def test_the_deploy_requires_integer_ids_of_both_templates(self) -> None:
        self.assertTrue(schedule_accepts(SCHEDULE_IDENTITY))
        for name, identity in (
            ("string project", {**SCHEDULE_IDENTITY, "project_id": "9"}),
            (
                "boolean template",
                {
                    **SCHEDULE_IDENTITY,
                    "templates": {"announce owners": True, "prune exports": 96},
                },
            ),
            (
                "string template",
                {
                    **SCHEDULE_IDENTITY,
                    "templates": {"announce owners": 95, "prune exports": "96"},
                },
            ),
            (
                "missing template",
                {**SCHEDULE_IDENTITY, "templates": {"announce owners": 95}},
            ),
        ):
            with self.subTest(name):
                self.assertFalse(schedule_accepts(identity))

    def test_the_deploy_writes_the_roles_only_beside_the_fact_of_semaphore(
        self,
    ) -> None:
        check = task_named("Require integer Semaphore ids of the scheduled export")
        self.assertEqual(check["when"], "semaphore_export_schedule_identity is defined")
        write = task_named("Bind the task token roles of the scheduled export")
        self.assertIn(
            "auth/{{ OPENBAO_JWT_EXPORT_MOUNT }}/role/{{ item.name }}",
            write["ansible.builtin.shell"],
        )
        self.assertIn(
            "lookup('template', 'export_schedule_roles.json.j2')", write["loop"]
        )
        self.assertIn(
            "if semaphore_export_schedule_identity is defined else []", write["loop"]
        )
        self.assertLess(
            [t.get("name", "") for t in tasks()].index(check["name"]),
            [t.get("name", "") for t in tasks()].index(write["name"]),
        )


class TestTheWorkspacesIdentity(unittest.TestCase):
    def test_an_unchanged_identity_is_not_written_again(self) -> None:
        self.assertFalse(writes(IDENTITY))

    def test_a_changed_template_id_is_written(self) -> None:
        changed = json.loads(json.dumps(IDENTITY))
        changed["templates"]["members"]["template_id"] = 99
        self.assertTrue(writes(changed))

    def test_a_missing_entry_is_written(self) -> None:
        self.assertTrue(writes(None))

    def test_both_tasks_need_the_fact_of_semaphore(self) -> None:
        read = task_named("Read the Workspaces project identity")
        publish = task_named("Publish the Workspaces project identity")
        self.assertEqual(read["when"], ["semaphore_workspaces_identity is defined"])
        self.assertEqual(publish["when"][0], "semaphore_workspaces_identity is defined")
        self.assertEqual(
            publish["args"]["stdin"], "{{ semaphore_workspaces_identity | to_json }}"
        )

    def test_the_entry_lives_where_the_store_reads_it(self) -> None:
        values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            values["OPENBAO_STORE_WORKSPACES_PATH"], "store/semaphore/workspaces"
        )
        for fragment in ("Read the Workspaces", "Publish the Workspaces"):
            with self.subTest(task=fragment):
                shell = task_named(fragment)["ansible.builtin.shell"]
                self.assertIn("-mount={{ OPENBAO_PLATFORM_MOUNT | quote }}", shell)
                self.assertIn("{{ OPENBAO_STORE_WORKSPACES_PATH | quote }}", shell)

    def test_openbao_runs_after_semaphore(self) -> None:
        services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
        self.assertIn("web-app-semaphore", services["openbao"]["run_after"])

    def test_control_a_read_that_keeps_the_kv_envelope_writes_every_deploy(
        self,
    ) -> None:
        condition = task_named("Publish the Workspaces project identity")["when"][1]
        self.assertIn(UNWRAP, condition)
        planted = condition.replace(UNWRAP, ")")
        self.assertTrue(writes(IDENTITY, planted))


if __name__ == "__main__":
    unittest.main()
