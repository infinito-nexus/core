from __future__ import annotations

import json
import re
import unittest
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
WORKSPACE = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
TRANSIT = f"ws-{WORKSPACE}-transit"
ZONE_POLICIES = "[{{ (openbao_workspace ~ '-zone') | to_json }}"
TRANSIT_ON_THE_ZONE_ROLE = (
    f"{ZONE_POLICIES}]",
    f"{ZONE_POLICIES}, {{{{ (openbao_workspace ~ '-transit') | to_json }}}}]",
)
OWNER_GROUP = "5f6e7d8c-9b0a-4c1d-8e2f-3a4b5c6d7e8f"
DNS = {"zone": "ws.example.org", "zone_id": ""}
APPLY_INPUTS = {"workspace_dns": DNS, "WORKSPACE_PLATFORM_TOKENS": False}
PROVIDERS = list(
    load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))["OPENBAO_PROVISION_SECRETS"]
)
FIXED_ROLES = 5
PROVIDER_IDS = {
    provider: {"provision": 100 + 2 * index, "destroy": 101 + 2 * index}
    for index, provider in enumerate(PROVIDERS)
}
IDS = {
    "project_id": 42,
    "provision_project_id": 7,
    "provider_templates": PROVIDER_IDS,
    "unlock_template_id": 73,
    "dns_template_id": 74,
    "zone_template_id": 75,
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
        OPENBAO_PROVISION_SECRETS=dict.fromkeys(PROVIDERS),
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


def zone_template_holders(entries: list[dict[str, Any]]) -> list[str]:
    return [
        entry["name"]
        for entry in entries
        if IDS["zone_template_id"]
        in entry["body"]["bound_claims"].get("template_id", [])
    ]


def transit_holders(entries: list[dict[str, Any]]) -> list[str]:
    return [
        entry["name"] for entry in entries if TRANSIT in entry["body"]["token_policies"]
    ]


def string_destroy(provider: str) -> dict[str, dict[str, Any]]:
    """
    Args:
        provider: the provider whose destroy template id turns into a string.

    Returns:
        ``provider_templates`` with that one id as a string.
    """
    own = PROVIDER_IDS[provider]
    return {**PROVIDER_IDS, provider: {**own, "destroy": str(own["destroy"])}}


def shared_template_ids(entries: list[dict[str, Any]]) -> dict[int, list[str]]:
    """
    Args:
        entries: the role entries the apply step writes.

    Returns:
        Each template id of the provision project that more than one task
        token role binds, with the names of those roles.
    """
    holders: dict[int, list[str]] = {}
    for entry in entries:
        claims = entry["body"]["bound_claims"]
        if claims["project_id"] == IDS["provision_project_id"]:
            for template_id in claims.get("template_id", []):
                holders.setdefault(template_id, []).append(entry["name"])
    return {key: names for key, names in holders.items() if len(names) > 1}


def apply_assertions() -> list[str]:
    tasks = load_yaml_any(str(ROLE_DIR / "tasks/workspace/apply.yml"))
    return tasks[0]["ansible.builtin.assert"]["that"]


def apply_accepts(
    ids: dict[str, Any], owner_group: str = OWNER_GROUP, **inputs: Any
) -> bool:
    """
    Args:
        ids: the ``workspace_semaphore`` mapping ``workspace apply`` receives.
        owner_group: ``workspace_owner_group``.
        inputs: further apply inputs that replace those of :data:`APPLY_INPUTS`.

    Returns:
        Whether every assertion of the apply step holds.
    """
    environment = env()
    return all(
        environment.compile_expression(condition)(
            workspace_semaphore=ids,
            workspace_owner_group=owner_group,
            OPENBAO_PROVISION_SECRETS=dict.fromkeys(PROVIDERS),
            **{**APPLY_INPUTS, **inputs},
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
                ("jwt", f"ws-{WORKSPACE}-zone"),
                *(
                    ("jwt", f"ws-{WORKSPACE}-provision-{provider}")
                    for provider in PROVIDERS
                ),
            ],
        )
        for entry in entries:
            with self.subTest(role=f"{entry['mount']}/{entry['name']}"):
                self.assertEqual(body_findings(entry), [])

    def test_the_deploy_role_binds_the_workspace_project_only(self) -> None:
        body = roles(IDS)[0]["body"]
        self.assertEqual(body["bound_claims"], {"project_id": 42})
        self.assertEqual(body["token_policies"], ["tenant"])

    def test_the_provision_role_binds_the_unlock_and_dns_templates_only(self) -> None:
        body = roles(IDS)[1]["body"]
        self.assertEqual(
            body["bound_claims"], {"project_id": 7, "template_id": [73, 74]}
        )
        self.assertEqual(body["token_policies"], [f"ws-{WORKSPACE}-provision"])

    def test_each_provider_role_binds_its_own_two_templates_to_its_own_policy(
        self,
    ) -> None:
        entries = roles(IDS)[FIXED_ROLES:]
        self.assertEqual(len(entries), len(PROVIDERS))
        for entry, provider in zip(entries, PROVIDERS, strict=True):
            with self.subTest(provider=provider):
                body = entry["body"]
                own = PROVIDER_IDS[provider]
                self.assertEqual(
                    body["bound_claims"],
                    {
                        "project_id": 7,
                        "template_id": [own["provision"], own["destroy"]],
                    },
                )
                self.assertEqual(
                    body["token_policies"], [f"ws-{WORKSPACE}-provision-{provider}"]
                )

    def test_the_template_id_alone_picks_the_role(self) -> None:
        self.assertEqual(shared_template_ids(roles(IDS)), {})

    def test_control_provider_roles_on_one_template_pair_share_its_ids(self) -> None:
        source = read_text(str(ROLE_DIR / "templates/workspace/jwt_roles.json.j2"))
        planted = source.replace(
            "provider_templates[openbao_provider]",
            "provider_templates[(OPENBAO_PROVISION_SECRETS | list)[0]]",
        )
        self.assertNotEqual(planted, source)
        self.assertNotEqual(shared_template_ids(roles(IDS, planted)), {})

    def test_control_the_provision_role_on_a_provider_template_shares_its_id(
        self,
    ) -> None:
        source = read_text(str(ROLE_DIR / "templates/workspace/jwt_roles.json.j2"))
        unlock = "{{ workspace_semaphore.unlock_template_id | to_json }},\n"
        foreign = (
            "          {{ workspace_semaphore.provider_templates."
            f"{PROVIDERS[0]}.provision | to_json }}}},\n"
        )
        planted = source.replace(unlock, unlock + foreign, 1)
        self.assertNotEqual(planted, source)
        self.assertIn(
            PROVIDER_IDS[PROVIDERS[0]]["provision"],
            shared_template_ids(roles(IDS, planted)),
        )

    def test_control_a_provider_role_on_the_provider_free_policy_fails(self) -> None:
        source = read_text(str(ROLE_DIR / "templates/workspace/jwt_roles.json.j2"))
        planted = source.replace(
            '"token_policies": [{{ openbao_provider_role | to_json }}]',
            "\"token_policies\": [{{ (openbao_workspace ~ '-provision') | to_json }}]",
        )
        self.assertNotEqual(planted, source)
        body = roles(IDS, planted)[FIXED_ROLES]["body"]
        self.assertNotEqual(
            body["token_policies"], [f"ws-{WORKSPACE}-provision-{PROVIDERS[0]}"]
        )

    def test_the_zone_role_binds_the_zone_template_only(self) -> None:
        body = roles(IDS)[4]["body"]
        self.assertEqual(body["bound_claims"], {"project_id": 7, "template_id": [75]})
        self.assertEqual(body["token_policies"], [f"ws-{WORKSPACE}-zone"])

    def test_no_task_role_carries_the_transit_policy_itself(self) -> None:
        self.assertEqual(transit_holders(roles(IDS)), [])

    def test_control_a_zone_role_with_the_transit_policy_is_found(self) -> None:
        source = read_text(str(ROLE_DIR / "templates/workspace/jwt_roles.json.j2"))
        planted = source.replace(*TRANSIT_ON_THE_ZONE_ROLE)
        self.assertNotEqual(planted, source)
        self.assertEqual(transit_holders(roles(IDS, planted)), [f"ws-{WORKSPACE}-zone"])

    def test_no_other_role_binds_the_zone_template(self) -> None:
        self.assertEqual(zone_template_holders(roles(IDS)), [f"ws-{WORKSPACE}-zone"])

    def test_control_a_provision_role_with_the_zone_template_fails(self) -> None:
        source = read_text(str(ROLE_DIR / "templates/workspace/jwt_roles.json.j2"))
        planted = source.replace(
            "{{ workspace_semaphore.dns_template_id | to_json }}\n",
            "{{ workspace_semaphore.dns_template_id | to_json }},\n"
            "          {{ workspace_semaphore.zone_template_id | to_json }}\n",
            1,
        )
        self.assertNotEqual(planted, source)
        self.assertNotEqual(
            zone_template_holders(roles(IDS, planted)), [f"ws-{WORKSPACE}-zone"]
        )

    def test_control_a_provision_role_without_the_dns_template_fails(self) -> None:
        source = read_text(str(ROLE_DIR / "templates/workspace/jwt_roles.json.j2"))
        dropped = source.replace(
            "unlock_template_id | to_json }},\n"
            "          {{ workspace_semaphore.dns_template_id | to_json }}\n",
            "unlock_template_id | to_json }}\n",
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
            roles(IDS),
            (
                "deploy",
                "provision",
                "export",
                "deploy",
                "provision",
                *("provision" for _ in PROVIDERS),
            ),
            strict=True,
        ):
            with self.subTest(role=entry["name"], kind=kind):
                self.assertEqual(entry["body"]["token_ttl"], ttl[kind])
                self.assertEqual(entry["body"]["token_max_ttl"], ttl[kind])

    def test_control_a_string_project_id_fails(self) -> None:
        entries = roles({**IDS, "project_id": "42"})
        self.assertNotEqual(body_findings(entries[0]), [])

    def test_control_a_string_template_id_fails(self) -> None:
        entries = roles({**IDS, "unlock_template_id": "73"})
        self.assertNotEqual(body_findings(entries[1]), [])
        entries = roles({**IDS, "provider_templates": string_destroy(PROVIDERS[0])})
        self.assertNotEqual(body_findings(entries[FIXED_ROLES]), [])


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
        self.assertFalse(apply_accepts({**IDS, "unlock_template_id": "73"}))
        templates = string_destroy(PROVIDERS[-1])
        self.assertFalse(apply_accepts({**IDS, "provider_templates": templates}))

    def test_apply_refuses_a_missing_unlock_template_id(self) -> None:
        ids = {key: value for key, value in IDS.items() if key != "unlock_template_id"}
        self.assertFalse(apply_accepts(ids))

    def test_apply_refuses_a_string_dns_template_id(self) -> None:
        self.assertFalse(apply_accepts({**IDS, "dns_template_id": "74"}))

    def test_apply_refuses_a_missing_dns_template_id(self) -> None:
        ids = {key: value for key, value in IDS.items() if key != "dns_template_id"}
        self.assertFalse(apply_accepts(ids))

    def test_apply_refuses_a_missing_zone_template_id(self) -> None:
        ids = {key: value for key, value in IDS.items() if key != "zone_template_id"}
        self.assertFalse(apply_accepts(ids))

    def test_apply_refuses_a_provider_set_other_than_the_table(self) -> None:
        cases = {
            "a provider less": {
                provider: ids
                for provider, ids in PROVIDER_IDS.items()
                if provider != PROVIDERS[0]
            },
            "an unknown provider": {
                **PROVIDER_IDS,
                "aws": {"provision": 1, "destroy": 2},
            },
            "a provider without destroy": {
                **PROVIDER_IDS,
                PROVIDERS[0]: {"provision": 100},
            },
            "a provider with a third template": {
                **PROVIDER_IDS,
                PROVIDERS[0]: {**PROVIDER_IDS[PROVIDERS[0]], "unlock": 73},
            },
        }
        for case, templates in cases.items():
            with self.subTest(case=case):
                self.assertFalse(
                    apply_accepts({**IDS, "provider_templates": templates})
                )

    def test_apply_refuses_an_owner_group_that_is_no_uuid(self) -> None:
        self.assertFalse(apply_accepts(IDS, owner_group="Owner'; true #"))

    def test_apply_takes_the_store_switch_as_a_boolean_only(self) -> None:
        self.assertTrue(apply_accepts(IDS, WORKSPACE_PLATFORM_TOKENS=True))
        for value in ("true", "false", 1, None):
            with self.subTest(value=value):
                self.assertFalse(apply_accepts(IDS, WORKSPACE_PLATFORM_TOKENS=value))

    def test_apply_refuses_a_zone_that_no_policy_path_can_name(self) -> None:
        for zone in ("", "a/b", 'x" { }', "Example.org", None):
            with self.subTest(zone=zone):
                self.assertFalse(
                    apply_accepts(IDS, workspace_dns={**DNS, "zone": zone})
                )


if __name__ == "__main__":
    unittest.main()
