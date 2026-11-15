from __future__ import annotations

import unittest

from .test_policies import (
    INVITE_METADATA,
    effective,
    parse,
    planted,
    render,
    template_source,
)

INVITE_DATA = "platform/data/store/invites/ws-0a/3f2a"
DATA_STANZA = 'data/store/invites/*" {\n  capabilities = ["create", "update"]\n}'
OTHER_METADATA = (
    "platform/metadata/store/semaphore",
    "platform/metadata/store/directory/ws-0a",
    "platform/metadata/store/other/x",
    "platform/metadata/provision/hetzner",
    "platform/metadata/export/s3",
)
TASK_POLICIES = ("tenant", "provision-shared", "tenant-export", "export-shared")


def staging_findings(
    store: dict[str, set[str]], tasks: dict[str, dict[str, set[str]]]
) -> list[str]:
    """
    Args:
        store: the capabilities of the store policy per path pattern.
        tasks: the same for every policy a workspace task role carries.

    Returns:
        Every way the policies stray from the staging rule of 107 decision 9.
    """
    findings = []
    if effective(store, INVITE_METADATA) != {"delete"}:
        findings.append(
            f"{INVITE_METADATA}: {sorted(effective(store, INVITE_METADATA))}"
        )
    if effective(store, INVITE_DATA) != {"create", "update"}:
        findings.append(f"{INVITE_DATA}: {sorted(effective(store, INVITE_DATA))}")
    findings.extend(
        f"{path}: the store may delete it"
        for path in OTHER_METADATA
        if "delete" in effective(store, path)
    )
    findings.extend(
        f"{name} reaches {path}"
        for name, grants in tasks.items()
        for path in (INVITE_DATA, INVITE_METADATA)
        if effective(grants, path)
    )
    return findings


def task_grants() -> dict[str, dict[str, set[str]]]:
    return {name: parse(render(name)) for name in TASK_POLICIES}


ERASURE_PROBES = {
    "platform/metadata/store/hostkeys/ws-0a/": {"list"},
    "platform/metadata/store/hostkeys/ws-0a/203.0.113.10/": {"list"},
    "platform/metadata/store/hostkeys/ws-0a/203.0.113.10/22": {
        "create",
        "read",
        "update",
        "delete",
    },
    "platform/metadata/store/hostkeys/": {"create", "read", "update", "delete"},
    "platform/metadata/store/hostkeys/ws-0a/203.0.113.10/22/": {
        "create",
        "read",
        "update",
        "delete",
    },
    "tenant/metadata/": set(),
    "tenant/metadata/ws-0a/": {"read", "delete"},
    "tenant/metadata/ws-0a-provision/": {"read", "delete"},
    "platform/metadata/store/directory/": set(),
    "platform/metadata/store/directory/ws-0a/": set(),
    "platform/metadata/store/directory/ws-0a/x": set(),
    "platform/data/store/directory/ws-0a/x": {"read"},
}
HOSTKEY_METADATA_STANZA = (
    'metadata/store/hostkeys/*" {\n'
    '  capabilities = ["create", "read", "update", "delete"]'
)
TENANT_METADATA_STANZA = 'metadata/ws-*" {\n  capabilities = ["read", "delete"]'


def erasure_findings(store: dict[str, set[str]]) -> list[str]:
    """
    Args:
        store: the capabilities of the store policy per path pattern.

    Returns:
        Every probe of the store's erasure walk whose capabilities differ from
        exactly the listing of one workspace's pinned host keys and the delete
        of each pin, with no listing across workspaces, below ``tenant`` or of
        ``platform/metadata/store/directory``.
    """
    return [
        f"{path}: {sorted(effective(store, path))} != {sorted(expected)}"
        for path, expected in ERASURE_PROBES.items()
        if effective(store, path) != expected
    ]


def patched(old: str, new: str) -> dict[str, set[str]]:
    source = template_source("store").replace(old, new)
    if source == template_source("store"):
        raise AssertionError(f"the store policy holds no {old!r}")
    return parse(render("store", source))


class TestTheStoreErasureWalk(unittest.TestCase):
    def test_the_store_lists_one_workspace_of_pins_and_nothing_else(self) -> None:
        self.assertEqual(erasure_findings(parse(render("store"))), [])

    def test_control_list_across_every_workspace_of_pins_fails(self) -> None:
        grants = patched(
            HOSTKEY_METADATA_STANZA,
            HOSTKEY_METADATA_STANZA.replace('"delete"]', '"delete", "list"]'),
        )
        self.assertNotEqual(erasure_findings(grants), [])

    def test_control_list_on_the_tenant_metadata_of_a_workspace_fails(self) -> None:
        grants = patched(
            TENANT_METADATA_STANZA,
            TENANT_METADATA_STANZA.replace('"delete"]', '"delete", "list"]'),
        )
        self.assertNotEqual(erasure_findings(grants), [])

    def test_control_list_and_delete_on_the_directory_metadata_fails(self) -> None:
        grants = planted(
            "store",
            'path "platform/metadata/store/directory/*" {\n'
            '  capabilities = ["list", "delete"]\n}',
        )
        self.assertNotEqual(erasure_findings(grants), [])

    def test_control_a_store_that_cannot_walk_the_pins_fails(self) -> None:
        grants = patched(
            'hostkeys/+/" {\n  capabilities = ["list"]',
            'hostkeys/+/" {\n  capabilities = []',
        )
        self.assertNotEqual(erasure_findings(grants), [])


KEY_RECOVERY_PROBES = {
    "tenant/data/ws-0a/ssh": {"create", "update"},
    "tenant/metadata/ws-0a/ssh": {"read", "delete"},
    "platform/data/store/workspace-keys/ws-0a": {"create", "read", "update"},
    "platform/metadata/store/workspace-keys/ws-0a": {"delete"},
}


def key_recovery_findings(store: dict[str, set[str]]) -> list[str]:
    """
    Args:
        store: the capabilities of the store policy per path pattern.

    Returns:
        Every probe of the workspace key recovery whose capabilities differ from
        a write-only private key, a readable version history of it, and a
        public-half record the store writes, reads and erases.
    """
    return [
        f"{path}: {sorted(effective(store, path))} != {sorted(expected)}"
        for path, expected in KEY_RECOVERY_PROBES.items()
        if effective(store, path) != expected
    ]


class TestTheWorkspaceKeyRecovery(unittest.TestCase):
    def test_the_store_reads_the_key_version_and_public_half_only(self) -> None:
        self.assertEqual(key_recovery_findings(parse(render("store"))), [])

    def test_control_a_store_that_reads_the_private_key_fails(self) -> None:
        grants = patched(
            'data/ws-*" {\n  capabilities = ["create", "update"]',
            'data/ws-*" {\n  capabilities = ["create", "read", "update"]',
        )
        self.assertNotEqual(key_recovery_findings(grants), [])

    def test_control_a_narrow_ssh_grant_never_applies_beside_ws(self) -> None:
        grants = patched(
            TENANT_METADATA_STANZA,
            'metadata/ws-*" {\n  capabilities = ["delete"]\n}\n\n'
            'path "tenant/metadata/+/ssh" {\n  capabilities = ["read", "delete"]',
        )
        self.assertNotEqual(key_recovery_findings(grants), [])

    def test_control_a_store_that_cannot_read_the_public_half_fails(self) -> None:
        grants = patched(
            'workspace-keys/*" {\n  capabilities = ["create", "read", "update"]',
            'workspace-keys/*" {\n  capabilities = ["create", "update"]',
        )
        self.assertNotEqual(key_recovery_findings(grants), [])


MEMBERS_GRANTS = {"platform/data/store/invites/*": {"read"}}


class TestTheMembersPolicy(unittest.TestCase):
    def test_the_members_policy_reads_the_staged_invites_only(self) -> None:
        grants = parse(render("members"))
        self.assertEqual(grants, MEMBERS_GRANTS)
        self.assertEqual(effective(grants, INVITE_DATA), {"read"})
        self.assertEqual(effective(grants, INVITE_METADATA), set())

    def test_control_a_members_policy_that_deletes_fails(self) -> None:
        grants = planted(
            "members",
            'path "platform/metadata/store/invites/*" {\n  capabilities = ["delete"]\n}',
        )
        self.assertNotEqual(grants, MEMBERS_GRANTS)


class TestInviteStaging(unittest.TestCase):
    def test_invite_staging_policies(self) -> None:
        self.assertEqual(staging_findings(parse(render("store")), task_grants()), [])

    def test_control_delete_on_the_staged_data_fails(self) -> None:
        source = template_source("store").replace(
            DATA_STANZA, DATA_STANZA.replace('"update"]', '"update", "delete"]')
        )
        self.assertNotEqual(source, template_source("store"))
        grants = parse(render("store", source))
        self.assertNotEqual(staging_findings(grants, task_grants()), [])

    def test_control_a_store_that_cannot_stage_fails(self) -> None:
        source = template_source("store").replace(
            f'path "{{{{ OPENBAO_PLATFORM_MOUNT }}}}/{DATA_STANZA}\n', ""
        )
        self.assertNotEqual(source, template_source("store"))
        grants = parse(render("store", source))
        self.assertNotEqual(staging_findings(grants, task_grants()), [])

    def test_control_delete_on_another_metadata_path_fails(self) -> None:
        grants = planted(
            "store",
            'path "platform/metadata/store/semaphore" {\n  capabilities = ["delete"]\n}',
        )
        self.assertNotEqual(staging_findings(grants, task_grants()), [])

    def test_control_a_task_role_reading_the_invites_fails(self) -> None:
        tasks = task_grants()
        tasks["export-shared"] = planted(
            "export-shared",
            'path "platform/data/store/invites/*" {\n  capabilities = ["read"]\n}',
        )
        self.assertNotEqual(staging_findings(parse(render("store")), tasks), [])


if __name__ == "__main__":
    unittest.main()
