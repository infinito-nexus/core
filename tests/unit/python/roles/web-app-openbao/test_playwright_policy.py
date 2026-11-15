from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from .test_policies import (
    ROLE_DIR,
    effective,
    literal_vars,
    parse,
    planted,
    render,
    template_source,
)

PLAYWRIGHT_GRANTS = {
    "tenant/data/+/proxmox": {"read"},
    "tenant/data/+/incus": {"read"},
    "tenant/data/+/s3": {"read"},
    "tenant/data/+/dns": {"read"},
    "platform/data/provision/proxmox-*": {"read"},
    "platform/data/provision/incus-*": {"read"},
    "platform/data/provision/transit/ws-*": {"read"},
    "transit/keys/ws-*": {"read"},
    "platform/data/fixture/+/workspace-ssh": {"read"},
    "platform/data/playwright/semaphore": {"read"},
    "platform/data/playwright/store": {"read"},
    "auth/token/revoke-self": {"update"},
}
PLAYWRIGHT_PROBES = {
    "tenant/data/ws-0a-provision/proxmox": {"read"},
    "tenant/data/ws-0a-provision/incus": {"read"},
    "tenant/data/ws-0a-provision/s3": {"read"},
    "tenant/data/ws-0a-provision/dns": {"read"},
    "platform/data/provision/proxmox-echoserver": {"read"},
    "platform/data/provision/incus-echoserver": {"read"},
    "platform/data/provision/transit/ws-0a": {"read"},
    "transit/keys/ws-0a-provision": {"read"},
    "transit/datakey/plaintext/ws-0a-provision": set(),
    "transit/decrypt/ws-0a-provision": set(),
    "transit/export/encryption-key/ws-0a-provision": set(),
    "transit/backup/ws-0a-provision": set(),
    "platform/metadata/provision/transit/ws-0a": set(),
    "platform/data/fixture/platform/workspace-ssh": {"read"},
    "platform/data/fixture/platform/apps/web-app-semaphore": set(),
    "platform/data/fixture/platform/users/platform_administrator": set(),
    "platform/data/fixture/platform/workspace-ssh/extra": set(),
    "platform/metadata/fixture/platform/workspace-ssh": set(),
    "platform/data/playwright/semaphore": {"read"},
    "platform/data/playwright/store": {"read"},
    "tenant/data/ws-0a/probe/alpha": set(),
    "tenant/data/ws-0a-provision/proxmox/extra": set(),
    "tenant/metadata/ws-0a-provision/proxmox": set(),
    "platform/data/store/gitea": set(),
    "platform/data/store/semaphore": set(),
    "platform/data/provision/hetzner": set(),
    "platform/data/provision/cloudflare/example.org": set(),
    "platform/data/workspaces/route53": set(),
    "platform/data/playwright/other": set(),
    "platform/metadata/playwright/store": set(),
    "auth/approle/role/store/secret-id": set(),
    "auth/approle/role/playwright/secret-id": set(),
    "sys/policies/acl/playwright": set(),
}
RUNTIME_GATE = re.compile(r"RUNTIME in \[[^\]]*\]")


def playwright_findings(grants: dict[str, set[str]]) -> list[str]:
    findings = [] if grants == PLAYWRIGHT_GRANTS else [f"grants {grants}"]
    findings.extend(
        f"{path}: {sorted(effective(grants, path))} != {sorted(expected)}"
        for path, expected in PLAYWRIGHT_PROBES.items()
        if effective(grants, path) != expected
    )
    return findings


def playwright_config() -> dict:
    services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
    return services["openbao"]["workspaces"]["playwright"]


class TestThePlaywrightPolicy(unittest.TestCase):
    def test_the_policy_reads_exactly_the_paths_the_specs_read(self) -> None:
        self.assertEqual(playwright_findings(parse(render("playwright"))), [])

    def test_control_a_widened_tenant_path_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "tenant/data/*" {\n  capabilities = ["read"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_a_widened_fixture_read_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "platform/data/fixture/*" {\n  capabilities = ["read"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_an_added_write_capability_fails(self) -> None:
        source = template_source("playwright").replace(
            '["read"]', '["create", "read"]', 1
        )
        self.assertNotEqual(source, template_source("playwright"))
        self.assertNotEqual(
            playwright_findings(parse(render("playwright", source))), []
        )

    def test_control_a_transit_data_key_grant_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "transit/datakey/plaintext/ws-*" {\n  capabilities = ["update"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_a_widened_transit_key_read_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "transit/*" {\n  capabilities = ["read"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])

    def test_control_a_store_secret_id_grant_fails(self) -> None:
        grants = planted(
            "playwright",
            'path "auth/approle/role/store/secret-id" {\n  capabilities = ["update"]\n}',
        )
        self.assertNotEqual(playwright_findings(grants), [])


class TestThePlaywrightLogins(unittest.TestCase):
    def test_the_logins_live_on_the_platform_mount(self) -> None:
        self.assertEqual(
            playwright_config()["mount"], literal_vars()["OPENBAO_PLATFORM_MOUNT"]
        )

    def test_the_policy_reads_exactly_the_configured_logins(self) -> None:
        config = playwright_config()
        prefix = f"{config['mount']}/data/playwright/"
        self.assertEqual(
            {
                pattern
                for pattern in parse(render("playwright"))
                if pattern.startswith(prefix)
            },
            {f"{config['mount']}/data/{path}" for path in config["logins"].values()},
        )

    def test_the_deploy_seeds_every_configured_login(self) -> None:
        values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            set(values["OPENBAO_PLAYWRIGHT_LOGINS"]), set(playwright_config()["logins"])
        )

    def test_the_deploy_writes_and_withdraws_every_login(self) -> None:
        config = playwright_config()
        grants = parse(render("ansible-admin"))
        for path in config["logins"].values():
            with self.subTest(path=path):
                self.assertLessEqual(
                    {"create", "update"},
                    effective(grants, f"{config['mount']}/data/{path}"),
                )
                self.assertLessEqual(
                    {"delete"}, effective(grants, f"{config['mount']}/metadata/{path}")
                )

    def test_the_approle_follows_the_runtimes_of_the_test_runner(self) -> None:
        values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        stage = read_text(str(PROJECT_ROOT / "tasks/stages/02_server.yml"))
        self.assertEqual(
            set(RUNTIME_GATE.findall(values["OPENBAO_PLAYWRIGHT_ENABLED"])),
            set(RUNTIME_GATE.findall(stage)),
        )


if __name__ == "__main__":
    unittest.main()
