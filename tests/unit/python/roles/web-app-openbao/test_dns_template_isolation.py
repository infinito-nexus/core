from __future__ import annotations

import unittest
from typing import Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from .test_policies import (
    OWN_ZONE,
    PROVISION_POLICY,
    ROLE_DIR,
    covers,
    effective,
    literal_vars,
    parse,
    provision_policy,
)
from .test_workspace_roles import IDS, PROVIDERS, WORKSPACE, env, roles

WORKSPACE_B = "7f6e5d4c-3b2a-4190-8f7e-6d5c4b3a2f1e"
IDS_B = {
    **IDS,
    "project_id": 43,
    "provider_templates": {
        provider: {"provision": 200 + 2 * index, "destroy": 201 + 2 * index}
        for index, provider in enumerate(PROVIDERS)
    },
    "unlock_template_id": 83,
    "dns_template_id": 84,
    "zone_template_id": 85,
    "export_template_id": 92,
}
WORKSPACES = {WORKSPACE: IDS, WORKSPACE_B: IDS_B}
ZONES = {WORKSPACE: OWN_ZONE, WORKSPACE_B: "ws.example.net"}
PAIRS = ((WORKSPACE, WORKSPACE_B), (WORKSPACE_B, WORKSPACE))
JWT_ROLES = ROLE_DIR / "templates/workspace/jwt_roles.json.j2"
PROJECT_BINDING = (
    '"project_id": {{ workspace_semaphore.provision_project_id | to_json }}'
)
TEMPLATE_BINDING = (
    f"{PROJECT_BINDING},\n"
    '        "template_id": [\n'
    "          {{ workspace_semaphore.unlock_template_id | to_json }},\n"
    "          {{ workspace_semaphore.dns_template_id | to_json }}\n"
    "        ]"
)
WORKSPACE_GLOBS = ("tenant/data/+/dns", "tenant/data/ws-*")
GLOB_WORKSPACE_IDS = ("+", "*", f"{WORKSPACE}*", "0a+b")


def dns_claims(workspace: str) -> dict[str, int]:
    """
    Args:
        workspace: the workspace id without its ``ws-`` prefix.

    Returns:
        The claims a task token of ``dns ws-<workspace>`` carries for the
        bound claims of a jwt role.
    """
    ids = WORKSPACES[workspace]
    return {
        "project_id": ids["provision_project_id"],
        "template_id": ids["dns_template_id"],
    }


def both_workspaces(source: str | None) -> list[dict[str, Any]]:
    """
    Args:
        source: a jwt role template text that replaces the role's own file.

    Returns:
        The role entries ``workspace apply`` writes for both workspaces.
    """
    return [
        entry
        for workspace, ids in WORKSPACES.items()
        for entry in roles(ids, source, workspace)
    ]


def admits(body: dict[str, Any], claims: dict[str, int]) -> bool:
    """
    Args:
        body: a jwt role body.
        claims: the claims of a task token.

    Returns:
        Whether every bound claim of the role holds the token's value, a list
        binding any of its entries.
    """
    return all(
        claims.get(name) in (bound if isinstance(bound, list) else [bound])
        for name, bound in body["bound_claims"].items()
    )


def credential(workspace: str, name: str) -> str:
    mount = literal_vars()["OPENBAO_TENANT_MOUNT"]
    return f"{mount}/data/ws-{workspace}-provision/{name}"


def foreign_paths(workspace: str) -> tuple[str, ...]:
    """
    Args:
        workspace: the workspace whose provision paths another workspace's
            dns token must not reach.

    Returns:
        Its dns and s3 credentials, its transit record, its transit child
        token role, its transit decrypt and the Cloudflare token of its zone.
    """
    values = literal_vars()
    platform = values["OPENBAO_PLATFORM_MOUNT"]
    return (
        credential(workspace, "dns"),
        credential(workspace, "s3"),
        f"{platform}/data/{values['OPENBAO_TRANSIT_RECORD_PREFIX']}/ws-{workspace}",
        f"auth/token/create/ws-{workspace}-transit-child",
        f"{values['OPENBAO_TRANSIT_MOUNT']}/decrypt/ws-{workspace}-provision",
        f"{platform}/data/provision/cloudflare/{ZONES[workspace]}",
    )


def token_grants(entry: dict[str, Any], source: str | None) -> dict[str, set[str]]:
    """
    Args:
        entry: a jwt role entry a dns task logs in to.
        source: a provision policy text that replaces the role's own file.

    Returns:
        The capabilities per path pattern of every policy the role's token
        carries, each rendered for its own workspace and zone.

    Raises:
        AssertionError: the role carries a policy other than the provider-free
            provision policy of one of the two workspaces.
    """
    owners = {f"ws-{workspace}-provision": workspace for workspace in WORKSPACES}
    grants: dict[str, set[str]] = {}
    for policy in entry["body"]["token_policies"]:
        if policy not in owners:
            raise AssertionError(f"{policy}: no policy a dns task may carry")
        owner = owners[policy]
        rendered = provision_policy(owner, "", True, ZONES[owner], source)
        for pattern, caps in parse(rendered).items():
            grants[pattern] = grants.get(pattern, set()) | caps
    return grants


def grant_findings(grants: dict[str, set[str]], own: str, other: str) -> list[str]:
    """
    Args:
        grants: the capabilities per path pattern of a dns task token.
        own: the workspace of the dns template.
        other: another workspace in another zone.

    Returns:
        A missing read of the own dns credential, every pattern that reaches a
        path of :func:`foreign_paths` of the other workspace, and every tenant
        pattern that is no literal path below the own provision subtree.
    """
    own_dns = credential(own, "dns")
    findings = [] if effective(grants, own_dns) == {"read"} else [f"{own_dns}: unread"]
    findings.extend(
        f"{pattern} reaches {path}"
        for path in foreign_paths(other)
        for pattern in grants
        if covers(pattern, path)
    )
    tenant = literal_vars()["OPENBAO_TENANT_MOUNT"]
    findings.extend(
        f"{pattern}: no literal path below {credential(own, '')}"
        for pattern in grants
        if pattern.startswith(f"{tenant}/")
        and (
            not pattern.startswith(credential(own, ""))
            or any(glob in pattern for glob in ("*", "+"))
        )
    )
    return findings


def isolation_findings(
    entries: list[dict[str, Any]], own: str, other: str, source: str | None
) -> list[str]:
    """
    Args:
        entries: the role entries of both workspaces.
        own: the workspace of the dns template whose task logs in.
        other: the other workspace.
        source: a provision policy text that replaces the role's own file.

    Returns:
        A login to any role but ``jwt/ws-<own>-provision``, and every finding
        of :func:`grant_findings` on the token of each role the task logs in to.
    """
    admitted = [entry for entry in entries if admits(entry["body"], dns_claims(own))]
    names = [f"{entry['mount']}/{entry['name']}" for entry in admitted]
    findings = []
    if names != [f"jwt/ws-{own}-provision"]:
        findings.append(f"dns ws-{own} logs in to {names}")
    for entry in admitted:
        grants = token_grants(entry, source)
        findings.extend(
            f"{entry['name']}: {finding}"
            for finding in grant_findings(grants, own, other)
        )
    return findings


def workspace_accepted(workspace: str) -> bool:
    """
    Args:
        workspace: a ``WORKSPACE`` value.

    Returns:
        Whether the ``WORKSPACE`` checks of the OpenBao workspace operation
        accept it.
    """
    tasks = load_yaml_any(str(ROLE_DIR / "tasks/workspace.yml"))
    checks = [
        check
        for check in tasks[0]["ansible.builtin.assert"]["that"]
        if check.startswith("WORKSPACE is ")
    ]
    environment = env()
    return all(
        environment.compile_expression(check)(WORKSPACE=workspace) for check in checks
    )


class TestTheDnsTokenReachesNoProvisionPathOfAnotherWorkspace(unittest.TestCase):
    def test_a_dns_token_reads_its_dns_credential_and_no_path_of_the_other(
        self,
    ) -> None:
        entries = both_workspaces(None)
        for own, other in PAIRS:
            with self.subTest(own=own):
                self.assertEqual(isolation_findings(entries, own, other, None), [])

    def test_control_a_provision_role_without_its_templates_admits_the_other(
        self,
    ) -> None:
        source = read_text(str(JWT_ROLES))
        planted = source.replace(TEMPLATE_BINDING, PROJECT_BINDING, 1)
        self.assertNotEqual(planted, source)
        foreign = credential(WORKSPACE, "dns")
        self.assertIn(
            f"ws-{WORKSPACE}-provision: {foreign} reaches {foreign}",
            isolation_findings(both_workspaces(planted), WORKSPACE_B, WORKSPACE, None),
        )

    def test_control_a_wildcard_workspace_segment_reaches_the_other(self) -> None:
        entries = both_workspaces(None)
        foreign = credential(WORKSPACE_B, "dns")
        for pattern in WORKSPACE_GLOBS:
            with self.subTest(pattern=pattern):
                source = (
                    read_text(str(PROVISION_POLICY))
                    + f'\npath "{pattern}" {{\n  capabilities = ["read"]\n}}\n'
                )
                findings = isolation_findings(entries, WORKSPACE, WORKSPACE_B, source)
                self.assertIn(
                    f"ws-{WORKSPACE}-provision: {pattern} reaches {foreign}", findings
                )

    def test_the_workspace_id_holds_no_glob_character(self) -> None:
        for workspace in WORKSPACES:
            with self.subTest(workspace=workspace):
                self.assertTrue(workspace_accepted(workspace))
        for workspace in GLOB_WORKSPACE_IDS:
            with self.subTest(workspace=workspace):
                self.assertFalse(workspace_accepted(workspace))


if __name__ == "__main__":
    unittest.main()
