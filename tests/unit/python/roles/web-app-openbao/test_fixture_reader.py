from __future__ import annotations

import json
import unittest
from typing import Any

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from .test_policies import ROLE_DIR, effective, parse, planted, render
from .test_workspace_roles import env, workspace_config

FIXTURE_GRANTS = {"platform/data/fixture/*": {"read"}}
FIXTURE_PROBES = {
    "platform/data/fixture/platform/users/platform_administrator": {"read"},
    "platform/data/fixture/platform/apps/web-app-openbao": {"read"},
    "platform/metadata/fixture/platform/users/platform_administrator": set(),
    "platform/data/store/semaphore": set(),
    "platform/data/export/s3": set(),
    "platform/data/workspaces/route53": set(),
    "tenant/data/ws-0a/ssh": set(),
    "infinito/data/x": set(),
    "auth/jwt/role/workspace-fixture": set(),
}
IDENTITY = {"project_id": 3, "template_id": 30}
MEMBERS_TEMPLATE = 31


def fixture_findings(grants: dict[str, set[str]]) -> list[str]:
    """
    Args:
        grants: the capabilities of the ``fixture`` policy per path pattern.

    Returns:
        Every way the policy strays from read on ``platform/data/fixture/*``
        and nothing else.
    """
    findings = [
        f"{pattern}: {sorted(caps)}"
        for pattern, caps in grants.items()
        if FIXTURE_GRANTS.get(pattern) != caps
    ]
    findings.extend(
        f"{pattern}: missing" for pattern in FIXTURE_GRANTS if pattern not in grants
    )
    findings.extend(
        f"{path}: {sorted(effective(grants, path))}"
        for path, expected in FIXTURE_PROBES.items()
        if effective(grants, path) != expected
    )
    return findings


def reader_role(identity: dict[str, Any]) -> dict[str, Any]:
    config = workspace_config()
    rendered = (
        env()
        .get_template("fixture_reader_role.json.j2")
        .render(
            semaphore_fixture_reader_identity=identity,
            OPENBAO_JWT_AUDIENCE=config["audience"],
            OPENBAO_JWT_TOKEN_TTL=config["token_ttl"],
            OPENBAO_FIXTURE_POLICY=role_vars()["OPENBAO_FIXTURE_POLICY"],
        )
    )
    return json.loads(rendered)


def role_vars() -> dict[str, Any]:
    return load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))


def admits(body: dict[str, Any], claims: dict[str, Any]) -> bool:
    """
    Args:
        body: a jwt role as OpenBao stores it.
        claims: the claims of a task token.

    Returns:
        Whether OpenBao logs the token in to the role: its audience is bound
        and every bound claim holds one of the bound values.
    """
    if claims.get("aud") not in body["bound_audiences"]:
        return False
    for claim, bound in body["bound_claims"].items():
        allowed = bound if isinstance(bound, list) else [bound]
        if claims.get(claim) not in allowed:
            return False
    return True


def binding_block() -> dict[str, Any]:
    tasks = load_yaml_any(str(ROLE_DIR / "tasks/07_workspaces.yml"))
    return next(
        task
        for task in tasks
        if task.get("when") == "semaphore_fixture_reader_identity is defined"
    )


class TestTheFixtureReader(unittest.TestCase):
    def test_the_fixture_policy_reads_the_fixture_folder_only(self) -> None:
        self.assertEqual(fixture_findings(parse(render("fixture"))), [])

    def test_negative_control_a_planted_wider_path_fails(self) -> None:
        for stanza in (
            'path "platform/data/*" {\n  capabilities = ["read"]\n}',
            'path "platform/metadata/fixture/*" {\n  capabilities = ["list"]\n}',
            'path "platform/data/fixture/+/apps/*" {\n  capabilities = ["update"]\n}',
        ):
            with self.subTest(stanza=stanza):
                self.assertNotEqual(fixture_findings(planted("fixture", stanza)), [])

    def test_the_reader_role_binds_the_workspace_template(self) -> None:
        body = reader_role(IDENTITY)
        self.assertEqual(body["bound_claims"], {"project_id": 3, "template_id": [30]})
        self.assertEqual(body["token_policies"], ["fixture"])
        self.assertEqual(body["bound_audiences"], [workspace_config()["audience"]])
        self.assertEqual(body["user_claim"], "sub")
        self.assertTrue(
            admits(body, {"aud": "openbao", "project_id": 3, "template_id": 30})
        )

    def test_negative_control_a_jwt_of_another_template_is_refused(self) -> None:
        body = reader_role(IDENTITY)
        for name, claims in (
            ("members template", {"project_id": 3, "template_id": MEMBERS_TEMPLATE}),
            ("other project", {"project_id": 4, "template_id": 30}),
            ("string ids", {"project_id": "3", "template_id": "30"}),
        ):
            with self.subTest(name):
                self.assertFalse(admits(body, {"aud": "openbao", **claims}))
        self.assertFalse(
            admits(body, {"aud": "store", "project_id": 3, "template_id": 30})
        )

    def test_the_binding_waits_for_the_identity_semaphore_hands_over(self) -> None:
        block = binding_block()["block"]
        conditions = block[0]["ansible.builtin.assert"]["that"]
        environment = env()
        for identity, accepted in (
            (IDENTITY, True),
            ({"project_id": "3", "template_id": 30}, False),
            ({"project_id": 3, "template_id": "30"}, False),
        ):
            with self.subTest(identity=identity):
                environment.tests["integer"] = lambda value: isinstance(value, int)
                self.assertEqual(
                    all(
                        environment.compile_expression(condition)(
                            semaphore_fixture_reader_identity=identity
                        )
                        for condition in conditions
                    ),
                    accepted,
                )
        written = " ".join(str(task) for task in block[1:])
        self.assertIn("OPENBAO_FIXTURE_POLICY", written)
        self.assertIn("OPENBAO_FIXTURE_ROLE", written)
        self.assertIn("fixture_reader_role.json.j2", written)

    def test_the_names_are_the_ones_127_fixes(self) -> None:
        values = role_vars()
        self.assertEqual(values["OPENBAO_FIXTURE_POLICY"], "fixture")
        self.assertEqual(values["OPENBAO_FIXTURE_ROLE"], "workspace-fixture")
        self.assertEqual(values["OPENBAO_FIXTURE_PREFIX"], "fixture")


if __name__ == "__main__":
    unittest.main()
