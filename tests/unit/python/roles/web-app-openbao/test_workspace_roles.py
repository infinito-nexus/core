from __future__ import annotations

import json
import re
import unittest
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
WORKSPACE = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
OWNER_GROUP = "5f6e7d8c-9b0a-4c1d-8e2f-3a4b5c6d7e8f"
IDS = {
    "project_id": 42,
    "provision_project_id": 7,
    "provision_templates": {"provision": 71, "destroy": 72, "unlock": 73},
    "dns_template_id": 74,
    "export_project_id": 9,
    "export_template_id": 91,
    "workspaces_project_id": 3,
    "members_template_id": 31,
}


def env() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(str(ROLE_DIR / "templates")),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["to_json"] = json.dumps
    environment.tests["match"] = lambda value, pattern: (
        re.match(pattern, value) is not None
    )
    environment.tests["string"] = lambda value: isinstance(value, str)
    return environment


def workspace_config() -> dict[str, Any]:
    services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
    return services["openbao"]["workspaces"]


def roles(ids: dict[str, Any], source: str | None = None) -> list[dict[str, Any]]:
    """
    Args:
        ids: the ``workspace_semaphore`` mapping ``workspace apply`` receives.
        source: a replacement template source, for the negative controls.

    Returns:
        The role entries the apply step writes, each with mount, name and body.
    """
    config = workspace_config()
    environment = env()
    template = (
        environment.get_template("workspace/jwt_roles.json.j2")
        if source is None
        else environment.from_string(source)
    )
    rendered = template.render(
        WORKSPACE=WORKSPACE,
        workspace_semaphore=ids,
        OPENBAO_JWT_MOUNT="jwt",
        OPENBAO_JWT_EXPORT_MOUNT="jwt-export",
        OPENBAO_JWT_AUDIENCE=config["audience"],
        OPENBAO_JWT_TOKEN_TTL=config["token_ttl"],
    )
    return json.loads(rendered)


def is_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def body_findings(entry: dict[str, Any]) -> list[str]:
    body = entry["body"]
    where = f"{entry['mount']}/{entry['name']}"
    findings = []
    if body.get("bound_audiences") != ["openbao"]:
        findings.append(f"{where}: bound_audiences {body.get('bound_audiences')!r}")
    if body.get("user_claim") != "sub":
        findings.append(f"{where}: user_claim {body.get('user_claim')!r}")
    claims = body.get("bound_claims", {})
    if not is_number(claims.get("project_id")):
        findings.append(f"{where}: project_id {claims.get('project_id')!r}")
    template_ids = claims.get("template_id")
    if template_ids is not None and not (
        isinstance(template_ids, list)
        and template_ids
        and all(is_number(value) for value in template_ids)
    ):
        findings.append(f"{where}: template_id {template_ids!r}")
    return findings


def apply_assertions() -> list[str]:
    tasks = load_yaml_any(str(ROLE_DIR / "tasks/workspace/apply.yml"))
    return tasks[0]["ansible.builtin.assert"]["that"]


def apply_accepts(ids: dict[str, Any], owner_group: str = OWNER_GROUP) -> bool:
    environment = env()
    return all(
        environment.compile_expression(condition)(
            workspace_semaphore=ids, workspace_owner_group=owner_group
        )
        for condition in apply_assertions()
    )


class TestTheWorkspaceRoles(unittest.TestCase):
    def test_the_workspace_roles_bind_numbers_and_audience(self) -> None:
        entries = roles(IDS)
        self.assertEqual(
            [(entry["mount"], entry["name"]) for entry in entries],
            [
                ("jwt", f"ws-{WORKSPACE}"),
                ("jwt", f"ws-{WORKSPACE}-provision"),
                ("jwt-export", f"ws-{WORKSPACE}"),
                ("jwt", "members"),
            ],
        )
        for entry in entries:
            with self.subTest(role=f"{entry['mount']}/{entry['name']}"):
                self.assertEqual(body_findings(entry), [])

    def test_the_deploy_role_binds_the_workspace_project_only(self) -> None:
        body = roles(IDS)[0]["body"]
        self.assertEqual(body["bound_claims"], {"project_id": 42})
        self.assertEqual(body["token_policies"], ["tenant"])

    def test_the_provision_role_binds_its_three_templates_and_the_dns_template(
        self,
    ) -> None:
        body = roles(IDS)[1]["body"]
        self.assertEqual(
            body["bound_claims"], {"project_id": 7, "template_id": [71, 72, 73, 74]}
        )
        self.assertEqual(body["token_policies"], ["tenant", "provision-shared"])

    def test_control_a_provision_role_without_the_dns_template_fails(self) -> None:
        source = read_text(str(ROLE_DIR / "templates/workspace/jwt_roles.json.j2"))
        dropped = source.replace(
            "unlock | to_json }},\n"
            "          {{ workspace_semaphore.dns_template_id | to_json }}",
            "unlock | to_json }}",
        )
        self.assertNotEqual(dropped, source)
        body = roles(IDS, dropped)[1]["body"]
        self.assertNotIn(IDS["dns_template_id"], body["bound_claims"]["template_id"])

    def test_control_a_string_dns_template_id_fails(self) -> None:
        entries = roles({**IDS, "dns_template_id": "74"})
        self.assertNotEqual(body_findings(entries[1]), [])

    def test_the_export_role_binds_its_export_template(self) -> None:
        body = roles(IDS)[2]["body"]
        self.assertEqual(body["bound_claims"], {"project_id": 9, "template_id": [91]})
        self.assertEqual(body["token_policies"], ["tenant-export", "export-shared"])

    def test_the_members_role_binds_the_members_template_only(self) -> None:
        body = roles(IDS)[3]["body"]
        self.assertEqual(body["bound_claims"], {"project_id": 3, "template_id": [31]})
        self.assertEqual(body["token_policies"], ["members"])

    def test_each_token_lives_as_long_as_its_longest_template_run(self) -> None:
        ttl = workspace_config()["token_ttl"]
        for entry, kind in zip(
            roles(IDS), ("deploy", "provision", "export", "deploy"), strict=True
        ):
            with self.subTest(role=entry["name"], kind=kind):
                self.assertEqual(entry["body"]["token_ttl"], ttl[kind])
                self.assertEqual(entry["body"]["token_max_ttl"], ttl[kind])

    def test_control_a_string_project_id_fails(self) -> None:
        entries = roles({**IDS, "project_id": "42"})
        self.assertNotEqual(body_findings(entries[0]), [])

    def test_control_a_string_template_id_fails(self) -> None:
        templates = {**IDS["provision_templates"], "destroy": "72"}
        entries = roles({**IDS, "provision_templates": templates})
        self.assertNotEqual(body_findings(entries[1]), [])


class TestTheApplyInputs(unittest.TestCase):
    def test_apply_accepts_integer_ids_and_a_uuid_owner_group(self) -> None:
        self.assertTrue(apply_accepts(IDS))

    def test_apply_refuses_a_string_project_id(self) -> None:
        self.assertFalse(apply_accepts({**IDS, "project_id": "42"}))

    def test_apply_refuses_a_boolean_id(self) -> None:
        self.assertFalse(apply_accepts({**IDS, "export_project_id": True}))

    def test_apply_refuses_a_string_members_template_id(self) -> None:
        self.assertFalse(apply_accepts({**IDS, "members_template_id": "31"}))

    def test_apply_refuses_a_string_template_id(self) -> None:
        templates = {**IDS["provision_templates"], "unlock": "73"}
        self.assertFalse(apply_accepts({**IDS, "provision_templates": templates}))

    def test_apply_refuses_a_string_dns_template_id(self) -> None:
        self.assertFalse(apply_accepts({**IDS, "dns_template_id": "74"}))

    def test_apply_refuses_a_missing_dns_template_id(self) -> None:
        ids = {key: value for key, value in IDS.items() if key != "dns_template_id"}
        self.assertFalse(apply_accepts(ids))

    def test_apply_refuses_a_template_set_other_than_the_three(self) -> None:
        templates = {"provision": 71, "destroy": 72}
        self.assertFalse(apply_accepts({**IDS, "provision_templates": templates}))

    def test_apply_refuses_an_owner_group_that_is_no_uuid(self) -> None:
        self.assertFalse(apply_accepts(IDS, owner_group="Owner'; true #"))


if __name__ == "__main__":
    unittest.main()
