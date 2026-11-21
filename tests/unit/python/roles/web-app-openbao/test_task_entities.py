from __future__ import annotations

import json
import unittest
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from .test_policies import ROLE_DIR, effective, parse, planted, render

IDENTITY = {"project_id": 3, "template_id": 37}
GRANTS = {
    "identity/entity/id": {"list"},
    "identity/entity/id/+": {"read", "delete"},
}
PROBES = {
    "identity/entity/id": {"list"},
    "identity/entity/id/0a1b2c3d": {"read", "delete"},
    "identity/entity/id/0a1b2c3d/extra": set(),
    "identity/entity/name/task:42": set(),
    "identity/entity/batch-delete": set(),
    "identity/entity/merge": set(),
    "identity/entity-alias/id/0a1b2c3d": set(),
    "identity/group/id/0a1b2c3d": set(),
    "auth/jwt/role/ws-0a": set(),
    "tenant/data/ws-0a/x": set(),
    "sys/policies/acl/task-entities": set(),
}


def findings(grants: dict[str, set[str]]) -> list[str]:
    found = [] if grants == GRANTS else [f"grants {grants}"]
    found.extend(
        f"{path}: {sorted(effective(grants, path))} != {sorted(expected)}"
        for path, expected in PROBES.items()
        if effective(grants, path) != expected
    )
    return found


def role_body(identity: dict[str, Any]) -> dict[str, Any]:
    values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
    environment = Environment(
        loader=FileSystemLoader(str(ROLE_DIR / "templates")),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["to_json"] = json.dumps
    rendered = environment.get_template("task_entities_role.json.j2").render(
        semaphore_task_entities_identity=identity,
        OPENBAO_TASK_ENTITIES_ROLE=values["OPENBAO_TASK_ENTITIES_ROLE"],
        OPENBAO_JWT_AUDIENCE=services["openbao"]["workspaces"]["audience"],
        OPENBAO_JWT_TOKEN_TTL=services["openbao"]["workspaces"]["token_ttl"],
    )
    return json.loads(rendered)


class TestTheTaskEntityPolicy(unittest.TestCase):
    def test_the_policy_lists_reads_and_deletes_entities_only(self) -> None:
        self.assertEqual(findings(parse(render("task-entities"))), [])

    def test_control_a_group_grant_fails(self) -> None:
        grants = planted(
            "task-entities",
            'path "identity/group/id/+" {\n  capabilities = ["delete"]\n}',
        )
        self.assertNotEqual(findings(grants), [])

    def test_control_a_widened_identity_grant_fails(self) -> None:
        grants = planted(
            "task-entities",
            'path "identity/*" {\n  capabilities = ["delete"]\n}',
        )
        self.assertNotEqual(findings(grants), [])

    def test_the_deploy_writes_the_policy(self) -> None:
        values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertIn(
            values["OPENBAO_TASK_ENTITIES_ROLE"], values["OPENBAO_TENANCY_POLICIES"]
        )


class TestTheTaskEntityRole(unittest.TestCase):
    def test_the_role_binds_the_cleanup_template_as_numbers(self) -> None:
        body = role_body(IDENTITY)
        self.assertEqual(body["bound_claims"], {"project_id": 3, "template_id": [37]})
        self.assertEqual(body["bound_audiences"], ["openbao"])
        self.assertEqual(body["user_claim"], "sub")
        self.assertEqual(body["token_policies"], ["task-entities"])

    def test_control_a_string_template_id_is_no_number(self) -> None:
        body = role_body({**IDENTITY, "template_id": "37"})
        self.assertNotEqual(body["bound_claims"]["template_id"], [37])

    def test_the_binding_asserts_integer_ids(self) -> None:
        tasks = load_yaml_any(str(ROLE_DIR / "tasks/07_workspaces.yml"))
        block = next(
            task
            for task in tasks
            if task.get("when") == "semaphore_task_entities_identity is defined"
        )
        self.assertEqual(
            block["block"][0]["ansible.builtin.assert"]["that"],
            [
                "semaphore_task_entities_identity.project_id is integer",
                "semaphore_task_entities_identity.template_id is integer",
            ],
        )


if __name__ == "__main__":
    unittest.main()
