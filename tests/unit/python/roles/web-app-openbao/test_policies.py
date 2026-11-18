from __future__ import annotations

import re
import unittest
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
JWT_ACCESSOR = "auth_jwt_1a2b3c4d"
EXPORT_ACCESSOR = "auth_jwt_5e6f7a8b"
POLICY_PATH = re.compile(
    r'path "(?P<path>[^"]+)" \{\s*capabilities = \[(?P<caps>[^\]]*)\]\s*\}'
)
HUMAN_POLICIES = ("administrator", "operator", "reader")
NEW_MOUNTS = ("tenant", "platform")
STORE_GRANTS = {
    "tenant/data/ws-*": {"create", "update"},
    "tenant/metadata/ws-*": {"read", "delete"},
    "platform/data/store/*": {"read"},
    "platform/data/store/workspace-keys/*": {"create", "read", "update"},
    "platform/metadata/store/workspace-keys/*": {"delete"},
    "platform/data/store/hostkeys/*": {"create", "read", "update", "delete"},
    "platform/metadata/store/hostkeys/*": {"create", "read", "update", "delete"},
    "platform/metadata/store/hostkeys/+/": {"list"},
    "platform/metadata/store/hostkeys/+/+/": {"list"},
    "platform/data/store/invites/*": {"create", "update"},
    "platform/metadata/store/invites/*": {"delete"},
    "auth/approle/role/store/secret-id": {"update"},
    "auth/approle/role/store/secret-id-accessor/destroy": {"update"},
    "auth/approle/role/store/secret-id/lookup": {"update"},
}
INVITE_METADATA = "platform/metadata/store/invites/ws-0a/3f2a"
FOREIGN_METADATA = (
    "platform/metadata/store/semaphore",
    "platform/metadata/store/gitea",
    "platform/metadata/store/other/x",
    "platform/metadata/store/directory/ws-0a",
    "platform/metadata/store/invites",
    "platform/metadata/provision/hetzner",
    "platform/metadata/provision/transit/ws-0a",
    "platform/metadata/export/owners/ws-0a",
    "platform/metadata/export/s3",
    "infinito/metadata/x",
)
STORE_PROBES = {
    "tenant/data/ws-0a/x": {"create", "update"},
    "tenant/data/ws-0a-provision/dns": {"create", "update"},
    "tenant/metadata/ws-0a/x": {"read", "delete"},
    "tenant/metadata/ws-0a/ssh": {"read", "delete"},
    "tenant/data/ws-0a/ssh": {"create", "update"},
    "tenant/metadata/": set(),
    "platform/data/store/workspace-keys/ws-0a": {"create", "read", "update"},
    "platform/metadata/store/workspace-keys/ws-0a": {"delete"},
    "platform/metadata/store/workspace-keys/": {"delete"},
    "platform/data/store/semaphore": {"read"},
    "platform/data/store/gitea": {"read"},
    "platform/data/store/directory/ws-0a": {"read"},
    "platform/data/store/other/x": {"read"},
    "platform/data/store/hostkeys/ws-0a/host.example/22": {
        "create",
        "read",
        "update",
        "delete",
    },
    "platform/metadata/store/hostkeys/ws-0a/host.example/22": {
        "create",
        "read",
        "update",
        "delete",
    },
    "platform/metadata/store/hostkeys/": {"create", "read", "update", "delete"},
    "platform/metadata/store/hostkeys/ws-0a/": {"list"},
    "platform/metadata/store/hostkeys/ws-0a/host.example/": {"list"},
    "platform/metadata/store/invites/ws-0a/3f2a": {"delete"},
    "platform/data/store/invites/ws-0a/3f2a": {"create", "update"},
    "platform/metadata/store/semaphore": set(),
    "platform/metadata/store/other/x": set(),
    "platform/data/provision/hetzner": set(),
    "platform/data/export/s3": set(),
    "auth/approle/role/store/secret-id": {"update"},
    "auth/approle/role/store/secret-id-accessor/destroy": {"update"},
    "auth/approle/role/store/secret-id/lookup": {"update"},
    "auth/approle/role/store/custom-secret-id": set(),
    "auth/approle/role/ansible/secret-id/lookup": set(),
    "auth/approle/role/ansible/secret-id": set(),
    "auth/jwt/role/ws-0a": set(),
    "auth/jwt/login": set(),
    "transit/keys/ws-0a-provision": set(),
    "transit/keys/ws-0a-provision/config": set(),
    "transit/datakey/plaintext/ws-0a-provision": set(),
    "sys/policies/acl/x": set(),
    "infinito/data/x": set(),
}


def literal_vars() -> dict[str, Any]:
    values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    return {
        key: value
        for key, value in values.items()
        if isinstance(value, str) and "{{" not in value
    }


def render(policy: str, source: str | None = None) -> str:
    """
    Args:
        policy: the policy template's name without ``.hcl.j2``.
        source: a template text that replaces the role's own file.

    Returns:
        The rendered policy.
    """
    env = Environment(
        loader=FileSystemLoader(str(ROLE_DIR / "templates")),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    template = (
        env.from_string(source)
        if source is not None
        else env.get_template(f"policies/{policy}.hcl.j2")
    )
    return template.render(
        **literal_vars(),
        OPENBAO_JWT_ACCESSOR=JWT_ACCESSOR,
        OPENBAO_JWT_EXPORT_ACCESSOR=EXPORT_ACCESSOR,
    )


def parse(rendered: str) -> dict[str, set[str]]:
    parsed = {
        match["path"]: set(re.findall(r'"([^"]+)"', match["caps"]))
        for match in POLICY_PATH.finditer(rendered)
    }
    if len(parsed) != rendered.count('path "'):
        raise AssertionError("a path stanza escaped the parser")
    return parsed


def template_source(policy: str) -> str:
    return read_text(str(ROLE_DIR / f"templates/policies/{policy}.hcl.j2"))


def _priority(pattern: str) -> tuple[int, int, int, int]:
    wildcard = min(
        (index for index, char in enumerate(pattern) if char in "*+"),
        default=len(pattern),
    )
    return (
        wildcard,
        0 if pattern.endswith("*") else 1,
        -pattern.count("+"),
        len(pattern),
    )


def covers(pattern: str, path: str) -> bool:
    regex = re.escape(pattern).replace(r"\+", "[^/]+")
    if regex.endswith(r"\*"):
        regex = regex[:-2] + ".*"
    return re.fullmatch(regex, path) is not None


def effective(grants: dict[str, set[str]], path: str) -> set[str]:
    """
    Args:
        grants: the capabilities of a policy per path pattern.
        path: a request path.

    Returns:
        The capabilities of the one pattern OpenBao applies to the path, the
        most specific match, or none when no pattern matches.
    """
    matching = [pattern for pattern in grants if covers(pattern, path)]
    if not matching:
        return set()
    return grants[max(matching, key=_priority)]


def store_findings(grants: dict[str, set[str]]) -> list[str]:
    findings = [
        f"{pattern}: {sorted(grants.get(pattern, set()))} != {sorted(expected)}"
        for pattern, expected in STORE_GRANTS.items()
        if grants.get(pattern) != expected
    ]
    findings.extend(
        f"{pattern}: not a path of decision 6"
        for pattern in grants
        if pattern not in STORE_GRANTS
    )
    findings.extend(
        f"{path}: {sorted(effective(grants, path))} != {sorted(expected)}"
        for path, expected in STORE_PROBES.items()
        if effective(grants, path) != expected
    )
    findings.extend(
        f"{pattern}: grants list"
        for pattern, caps in grants.items()
        if "list" in caps and "list" not in STORE_GRANTS.get(pattern, set())
    )
    return findings


def planted(policy: str, stanza: str) -> dict[str, set[str]]:
    return parse(render(policy, template_source(policy) + "\n" + stanza + "\n"))


class TestTheTenantPolicy(unittest.TestCase):
    def test_the_tenant_policy_is_templated_on_the_role(self) -> None:
        role = f"{{{{identity.entity.aliases.{JWT_ACCESSOR}.metadata.role}}}}"
        self.assertEqual(
            parse(render("tenant")),
            {
                f"tenant/data/{role}/*": {"read"},
                f"transit/datakey/plaintext/{role}": {"update"},
                f"transit/decrypt/{role}": {"update"},
            },
        )

    def test_no_tenant_path_names_a_workspace_literally(self) -> None:
        for pattern in parse(render("tenant")):
            with self.subTest(pattern=pattern):
                self.assertIn(f"aliases.{JWT_ACCESSOR}.metadata.role", pattern)
                self.assertNotIn("ws-", pattern)

    def test_the_provision_role_reads_the_shared_provision_secrets_only(self) -> None:
        self.assertEqual(
            parse(render("provision-shared")),
            {"platform/data/provision/*": {"read"}},
        )


class TestThePlatformReaders(unittest.TestCase):
    def test_no_platform_reader_reaches_the_new_mounts(self) -> None:
        probes = [
            f"{mount}/{kind}/ws-0a/x"
            for mount in NEW_MOUNTS
            for kind in ("data", "metadata")
        ] + [f"{mount}/data/store/semaphore" for mount in NEW_MOUNTS]
        for policy in HUMAN_POLICIES:
            grants = parse(render(policy))
            for path in probes:
                with self.subTest(policy=policy, path=path):
                    self.assertEqual(
                        [pattern for pattern in grants if covers(pattern, path)], []
                    )

    def test_the_kv_mounts_lie_outside_the_platform_reader_mount(self) -> None:
        values = literal_vars()
        self.assertNotIn(values["OPENBAO_KV_MOUNT"], NEW_MOUNTS)
        self.assertEqual(
            (values["OPENBAO_TENANT_MOUNT"], values["OPENBAO_PLATFORM_MOUNT"]),
            NEW_MOUNTS,
        )


class TestTheStorePolicy(unittest.TestCase):
    def test_the_store_policy_holds_exactly_its_paths(self) -> None:
        self.assertEqual(store_findings(parse(render("store"))), [])

    def test_control_list_on_the_tenant_metadata_fails(self) -> None:
        grants = planted(
            "store", 'path "tenant/metadata/*" {\n  capabilities = ["list"]\n}'
        )
        self.assertNotEqual(store_findings(grants), [])

    def test_control_delete_on_transit_keys_fails(self) -> None:
        grants = planted(
            "store", 'path "transit/keys/*" {\n  capabilities = ["delete"]\n}'
        )
        self.assertNotEqual(store_findings(grants), [])

    def test_control_custom_secret_id_fails(self) -> None:
        grants = planted(
            "store",
            'path "auth/approle/role/store/custom-secret-id" {\n'
            '  capabilities = ["update"]\n}',
        )
        self.assertNotEqual(store_findings(grants), [])

    def test_control_list_on_the_host_keys_fails(self) -> None:
        source = template_source("store").replace(
            'metadata/store/hostkeys/*" {\n  capabilities = ["create", "read", "update", "delete"]',
            'metadata/store/hostkeys/*" {\n  capabilities = ["create", "read", "update", "delete", "list"]',
        )
        self.assertNotEqual(source, template_source("store"))
        self.assertNotEqual(store_findings(parse(render("store", source))), [])

    def test_control_create_on_an_unnamed_store_path_fails(self) -> None:
        for path in ("platform/data/store/directory/*", "platform/data/store/other/*"):
            with self.subTest(path=path):
                grants = planted(
                    "store", f'path "{path}" {{\n  capabilities = ["create"]\n}}'
                )
                self.assertNotEqual(store_findings(grants), [])

    def test_the_store_reads_nothing_it_writes_below_tenant(self) -> None:
        grants = parse(render("store"))
        for path in (
            "tenant/data/ws-0a/x",
            "tenant/data/ws-0a/ssh",
            "tenant/data/ws-0a-provision/dns",
        ):
            with self.subTest(path=path):
                self.assertNotIn("read", effective(grants, path))


def invite_findings(grants: dict[str, set[str]]) -> list[str]:
    findings = []
    if "delete" not in effective(grants, INVITE_METADATA):
        findings.append(f"{INVITE_METADATA}: the store cannot erase a staged invite")
    findings.extend(
        f"{path}: the store may delete it"
        for path in FOREIGN_METADATA
        if "delete" in effective(grants, path)
    )
    return findings


class TestTheStoreErasesStagedInvites(unittest.TestCase):
    def test_the_store_deletes_invite_metadata_and_no_other_platform_metadata(
        self,
    ) -> None:
        self.assertEqual(invite_findings(parse(render("store"))), [])

    def test_control_delete_on_all_store_metadata_fails(self) -> None:
        source = template_source("store").replace(
            "metadata/store/invites/*", "metadata/store/*"
        )
        self.assertNotEqual(source, template_source("store"))
        self.assertNotEqual(invite_findings(parse(render("store", source))), [])
        self.assertNotEqual(store_findings(parse(render("store", source))), [])

    def test_control_a_store_without_the_invite_grant_fails(self) -> None:
        source = template_source("store").replace(
            'path "{{ OPENBAO_PLATFORM_MOUNT }}/metadata/store/invites/*" {\n'
            '  capabilities = ["delete"]\n}\n',
            "",
        )
        self.assertNotEqual(source, template_source("store"))
        self.assertNotEqual(invite_findings(parse(render("store", source))), [])


class TestTheExportPolicies(unittest.TestCase):
    def test_the_export_policy_is_templated_on_the_role(self) -> None:
        role = f"{{{{identity.entity.aliases.{EXPORT_ACCESSOR}.metadata.role}}}}"
        self.assertEqual(
            parse(render("tenant-export")),
            {
                f"tenant/data/{role}/*": {"read"},
                f"tenant/metadata/{role}/*": {"list"},
            },
        )

    def test_the_export_policy_names_the_export_accessor_not_the_task_one(
        self,
    ) -> None:
        rendered = render("tenant-export")
        self.assertNotIn(JWT_ACCESSOR, rendered)

    def test_the_shared_export_policy_reads_the_export_platform_entries(
        self,
    ) -> None:
        self.assertEqual(
            parse(render("export-shared")),
            {
                "platform/data/export/*": {"read"},
                "platform/metadata/export/owners/": {"list"},
            },
        )

    def test_the_scheduled_export_tasks_list_and_read_the_owners_and_read_s3(
        self,
    ) -> None:
        grants = parse(render("export-shared"))
        self.assertEqual(
            effective(grants, "platform/metadata/export/owners/"), {"list"}
        )
        for path in ("platform/data/export/owners/ws-0a", "platform/data/export/s3"):
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), {"read"})
        for path in (
            "platform/metadata/export/owners/ws-0a",
            "platform/metadata/export/",
            "tenant/data/ws-0a/x",
            "platform/data/store/semaphore",
        ):
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), set())

    def test_control_a_shared_export_policy_that_lists_all_export_metadata_fails(
        self,
    ) -> None:
        grants = planted(
            "export-shared",
            'path "platform/metadata/export/*" {\n  capabilities = ["list"]\n}',
        )
        self.assertNotEqual(
            grants,
            {
                "platform/data/export/*": {"read"},
                "platform/metadata/export/owners/": {"list"},
            },
        )
        self.assertEqual(effective(grants, "platform/metadata/export/"), {"list"})


ROTATION_GRANTS = {
    "platform/data/store/semaphore": {"create", "update"},
    "platform/data/store/gitea": {"create", "update"},
}
ROTATION_PROBES = {
    "platform/data/store/semaphore/workspaces": set(),
    "platform/data/store/hostkeys/ws-0a/host.example/22": set(),
    "platform/data/store/invites/ws-0a/3f2a": set(),
    "platform/data/store/other": set(),
    "platform/metadata/store/semaphore": set(),
    "tenant/data/ws-0a/x": set(),
}


def rotation_findings(grants: dict[str, set[str]]) -> list[str]:
    findings = [] if grants == ROTATION_GRANTS else [f"grants {grants}"]
    findings.extend(
        f"{path}: {sorted(effective(grants, path))}"
        for path, expected in ROTATION_PROBES.items()
        if effective(grants, path) != expected
    )
    return findings


class TestTheStoreCredentialsPolicy(unittest.TestCase):
    def test_the_rotation_writes_exactly_the_two_store_entries(self) -> None:
        self.assertEqual(rotation_findings(parse(render("store-credentials"))), [])

    def test_control_a_wildcard_over_the_store_entries_fails(self) -> None:
        grants = planted(
            "store-credentials",
            'path "platform/data/store/*" {\n  capabilities = ["create", "update"]\n}',
        )
        self.assertNotEqual(rotation_findings(grants), [])

    def test_control_a_rotation_that_reads_its_entries_back_fails(self) -> None:
        source = template_source("store-credentials").replace(
            '["create", "update"]', '["create", "read", "update"]', 1
        )
        self.assertNotEqual(source, template_source("store-credentials"))
        self.assertNotEqual(
            rotation_findings(parse(render("store-credentials", source))), []
        )

    def test_the_store_reads_both_entries(self) -> None:
        grants = parse(render("store"))
        for path in ROTATION_GRANTS:
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), {"read"})


DEPLOY_WRITES = {
    "tenant/data/ws-0a-provision/s3": {"create", "read", "update"},
    "tenant/data/ws-0a-provision/dns": {"create", "read", "update"},
    "platform/data/workspaces/route53": {"create", "read", "update"},
    "platform/data/provision/cloudflare/example.org": {"create", "read", "update"},
    "platform/data/provision/proxmox-echoserver": {"create", "read", "update"},
    "platform/data/provision/incus-echoserver": {"create", "read", "update"},
    "platform/data/provision/hetzner": set(),
    "tenant/data/ws-0a-provision/proxmox": {"create", "read", "update"},
    "tenant/metadata/ws-0a-provision/proxmox": {"list", "delete"},
    "platform/data/store/semaphore/workspaces": {"create", "read", "update"},
    "platform/data/store/semaphore": set(),
    "platform/data/store/invites/ws-0a/3f2a": set(),
    "platform/data/store/erpnext/api-identity": {"create", "read", "update"},
    "platform/data/store/erpnext": set(),
    "platform/data/store/rotation": set(),
}


class TestTheAnsiblePolicy(unittest.TestCase):
    def test_the_deploy_writes_exactly_its_workspace_entries(self) -> None:
        grants = parse(render("ansible-admin"))
        for path, expected in DEPLOY_WRITES.items():
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), expected)

    def test_control_a_deploy_that_cannot_write_tenant_data_fails(self) -> None:
        source = template_source("ansible-admin").replace(
            'path "{{ OPENBAO_TENANT_MOUNT }}/data/*" {\n'
            '  capabilities = ["create", "read", "update"]\n}\n',
            "",
        )
        self.assertNotEqual(source, template_source("ansible-admin"))
        grants = parse(render("ansible-admin", source))
        self.assertEqual(effective(grants, "tenant/data/ws-0a-provision/s3"), set())


if __name__ == "__main__":
    unittest.main()
