from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from .test_policies import (
    PROVISION_POLICY,
    ROLE_DIR,
    covers,
    effective,
    literal_vars,
    parse,
    planted,
    provision_policy,
    provision_secrets,
    render,
    transit_policy,
    zone_policy,
)
from .test_workspace_roles import DNS, IDS, apply_accepts

SHARED_ZONE = "ws.example.org"
ZONE_TOKEN = f"platform/data/provision/cloudflare/{SHARED_ZONE}"
WORKSPACES = ("0a", "0b")
FORMER_GRANT = (
    'path "{{ OPENBAO_PLATFORM_MOUNT }}/data/provision/cloudflare/'
    '{{ workspace_dns.zone }}" {\n  capabilities = ["read"]\n}\n'
)
PROVISION_TREE = 'path "platform/data/provision/*" {\n  capabilities = ["read"]\n}'
PLATFORM_READERS = {
    "ansible-admin": {"create", "read", "update"},
    "dns-broker": {"read"},
}
BROKER_GRANTS = {
    "platform/data/provision/cloudflare/*": {"read"},
    "platform/data/provision/dns-scope/*": {"read"},
}
BROKER_DENIED = (
    "platform/data/provision/cloudflare-zones",
    "platform/data/provision/hetzner",
    "platform/data/provision/transit/ws-0a",
    "tenant/data/ws-0a-provision/dns",
    "transit/decrypt/ws-0a-provision",
    "auth/token/create",
    "auth/token/create/ws-0a-dns-child",
)
DNS_POLICY = ROLE_DIR / "templates/workspace/dns_policy.hcl.j2"
POLICY_TEMPLATES = ROLE_DIR / "templates/policies"


def dns_policy(workspace: str) -> str:
    """
    Args:
        workspace: the workspace id without its ``ws-`` prefix.

    Returns:
        The policy ``ws-<id>-dns`` of the token a run hands the DNS broker.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return env.from_string(read_text(str(DNS_POLICY))).render(
        **literal_vars(), WORKSPACE=workspace
    )


def identities() -> dict[str, dict[str, set[str]]]:
    """
    Returns:
        The grants per path pattern of every policy OpenBao holds: each
        template under ``templates/policies``, and each workspace policy of
        two workspaces placed in one shared cloudflare zone.
    """
    grants = {
        path.name.removesuffix(".hcl.j2"): parse(
            render(path.name.removesuffix(".hcl.j2"))
        )
        for path in sorted(POLICY_TEMPLATES.glob("*.hcl.j2"))
    }
    for workspace in WORKSPACES:
        for provider in ("", *provision_secrets()):
            suffix = f"-{provider}" if provider else ""
            grants[f"ws-{workspace}-provision{suffix}"] = parse(
                provision_policy(workspace, provider, True, SHARED_ZONE)
            )
        grants[f"ws-{workspace}-zone"] = parse(zone_policy(workspace))
        grants[f"ws-{workspace}-transit"] = parse(transit_policy(workspace))
        grants[f"ws-{workspace}-dns"] = parse(dns_policy(workspace))
    return grants


def reader_findings(grants: dict[str, dict[str, set[str]]]) -> list[str]:
    """
    Args:
        grants: the grants per path pattern of each policy by its name.

    Returns:
        Every policy whose capabilities on the zone token of the shared zone
        differ from ``PLATFORM_READERS``, none for every other policy, and
        every platform reader that is missing.
    """
    findings = [
        f"{name}: {sorted(effective(policy, ZONE_TOKEN))}"
        for name, policy in grants.items()
        if effective(policy, ZONE_TOKEN) != PLATFORM_READERS.get(name, set())
    ]
    findings.extend(
        f"{name}: missing" for name in PLATFORM_READERS if name not in grants
    )
    return findings


class TestNoWorkspacePolicyReadsTheZoneToken(unittest.TestCase):
    def test_no_provision_policy_of_a_cloudflare_workspace_names_the_zone_token(
        self,
    ) -> None:
        for workspace in WORKSPACES:
            for provider in ("", *provision_secrets()):
                for granted in (False, True):
                    with self.subTest(
                        workspace=workspace, provider=provider, granted=granted
                    ):
                        grants = parse(
                            provision_policy(workspace, provider, granted, SHARED_ZONE)
                        )
                        self.assertEqual(
                            [
                                pattern
                                for pattern in grants
                                if covers(pattern, ZONE_TOKEN)
                            ],
                            [],
                        )

    def test_control_the_former_grant_hands_every_workspace_of_the_zone_its_token(
        self,
    ) -> None:
        source = read_text(str(PROVISION_POLICY)) + "\n" + FORMER_GRANT
        for workspace in WORKSPACES:
            with self.subTest(workspace=workspace):
                grants = parse(
                    provision_policy(workspace, "", True, SHARED_ZONE, source)
                )
                self.assertEqual(effective(grants, ZONE_TOKEN), {"read"})


class TestOnlyThePlatformReadsTheZoneToken(unittest.TestCase):
    def test_each_identity_reads_the_zone_token_only_as_the_platform(self) -> None:
        self.assertEqual(reader_findings(identities()), [])

    def test_control_a_store_that_reads_the_provision_tree_is_found(self) -> None:
        grants = {**identities(), "store": planted("store", PROVISION_TREE)}
        self.assertEqual(reader_findings(grants), ["store: ['read']"])

    def test_control_a_workspace_policy_with_the_former_grant_is_found(self) -> None:
        source = read_text(str(PROVISION_POLICY)) + "\n" + FORMER_GRANT
        grants = {
            **identities(),
            "ws-0b-provision": parse(
                provision_policy("0b", "", True, SHARED_ZONE, source)
            ),
        }
        self.assertEqual(reader_findings(grants), ["ws-0b-provision: ['read']"])

    def test_control_a_missing_broker_policy_is_found(self) -> None:
        grants = {
            name: policy
            for name, policy in identities().items()
            if name != "dns-broker"
        }
        self.assertEqual(reader_findings(grants), ["dns-broker: missing"])

    def test_the_deploy_writes_the_broker_policy(self) -> None:
        self.assertIn(
            "dns-broker",
            load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))[
                "OPENBAO_TENANCY_POLICIES"
            ],
        )

    def test_the_broker_reads_the_zone_tokens_and_the_dns_scopes_alone(self) -> None:
        grants = parse(render("dns-broker"))
        self.assertEqual(grants, BROKER_GRANTS)
        for path in BROKER_DENIED:
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), set())

    def test_the_broker_caller_of_a_workspace_only_looks_itself_up(self) -> None:
        for workspace in WORKSPACES:
            with self.subTest(workspace=workspace):
                self.assertEqual(
                    parse(dns_policy(workspace)),
                    {"auth/token/lookup-self": {"read"}},
                )

    def test_a_provision_role_mints_the_broker_caller_of_its_own_workspace_only(
        self,
    ) -> None:
        for provider in ("", *provision_secrets()):
            with self.subTest(provider=provider):
                grants = parse(provision_policy("0a", provider, True, SHARED_ZONE))
                self.assertEqual(
                    effective(grants, "auth/token/create/ws-0a-dns-child"), {"update"}
                )
                for path in ("auth/token/create/ws-0b-dns-child", "auth/token/create"):
                    self.assertEqual(effective(grants, path), set())


class TestTheDnsScopeTheBrokerTrusts(unittest.TestCase):
    def test_apply_pins_a_zone_id_of_letters_and_digits_or_none(self) -> None:
        for zone_id in (
            "",
            "0123456789abcdef0123456789abcdef",
            "Z0123456789ABCDEFGHIJ",
        ):
            with self.subTest(zone_id=zone_id):
                self.assertTrue(
                    apply_accepts(IDS, workspace_dns={**DNS, "zone_id": zone_id})
                )

    def test_apply_refuses_a_zone_id_that_leaves_the_scope_command(self) -> None:
        for zone_id in ('x" ; true', "a'b", "a b", "a/b", "x" * 65, None):
            with self.subTest(zone_id=zone_id):
                self.assertFalse(
                    apply_accepts(IDS, workspace_dns={**DNS, "zone_id": zone_id})
                )


if __name__ == "__main__":
    unittest.main()
