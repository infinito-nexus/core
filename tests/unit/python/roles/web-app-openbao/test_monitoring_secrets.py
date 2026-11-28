from __future__ import annotations

import json
import unittest
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from .test_policies import JWT_ACCESSOR, ROLE_DIR, effective, parse, planted, render

WS = "ws-0a"
FOREIGN = "ws-0b"
CHECKMK = "platform/data/monitoring/checkmk"
TOKEN = f"platform/data/monitoring/federation/{WS}/target"
FOREIGN_TOKEN = f"platform/data/monitoring/federation/{FOREIGN}/target"
INVENTORY_KEY = f"platform/data/monitoring/inventory/{WS}"
DIGEST = f"monitoring/data/{WS}/federation/target"
AGENT_KEY_SOURCE = "platform/data/monitoring/agent-key"
AGENT_KEY_COPY = f"monitoring/data/{WS}/agent/target"
MONITORED = f"platform/data/monitoring/inventory/{WS}/hosts/host-a"
UNCHANGEABLE = (
    f"platform/metadata/monitoring/inventory/{WS}/hosts/host-a",
    f"platform/metadata/monitoring/inventory/{WS}/hosts/",
    f"platform/delete/monitoring/inventory/{WS}/hosts/host-a",
    f"platform/destroy/monitoring/inventory/{WS}/hosts/host-a",
    f"platform/undelete/monitoring/inventory/{WS}/hosts/host-a",
    f"platform/data/monitoring/inventory/{WS}/hosts/",
    f"platform/data/monitoring/inventory/{WS}/hosts/host-a/x",
    INVENTORY_KEY,
)
PROTECTED = (DIGEST, AGENT_KEY_COPY)
SECRETS = (CHECKMK, TOKEN, INVENTORY_KEY, AGENT_KEY_SOURCE)
GRANTS = {
    CHECKMK: {"read"},
    AGENT_KEY_SOURCE: {"read"},
    "platform/data/monitoring/inventory/+": {"read"},
    "platform/data/monitoring/inventory/+/hosts/+": {"create", "read", "update"},
    "platform/data/monitoring/federation/+/+": {"create", "read", "update"},
    "platform/metadata/monitoring/federation/+/": {"list"},
    "platform/metadata/monitoring/federation/+/+": {"delete"},
    "monitoring/data/+/federation/+": {"create", "read", "update"},
    "monitoring/data/+/agent/+": {"create", "read", "update"},
    "monitoring/data/+/labels/+": {"create", "read", "update"},
    "monitoring/data/+/released/+": {"read"},
    "monitoring/data/+/releasing/+": {"read"},
    "monitoring/metadata/+/federation/+": {"delete"},
    "monitoring/metadata/+/agent/+": {"delete"},
    "monitoring/metadata/+/labels/+": {"delete"},
    "monitoring/metadata/+/labels/": {"list"},
}
TOMBSTONES = (
    f"monitoring/data/{WS}/released/target",
    f"monitoring/data/{WS}/releasing/target",
)
OTHER_READERS = (
    "store",
    "tenant",
    "tenant-export",
    "export-shared",
    "members",
    "store-credentials",
    "task-entities",
    "dns-broker",
    "administrator",
    "operator",
    "reader",
)
IDENTITY = {
    "project_id": 3,
    "templates": {"monitoring": {"template_id": 41}, "workspace": {"template_id": 7}},
}


def role_body(identity: dict[str, Any]) -> dict[str, Any]:
    values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    services = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
    environment = Environment(
        loader=FileSystemLoader(str(ROLE_DIR / "templates")),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["to_json"] = json.dumps
    rendered = environment.get_template("monitoring_role.json.j2").render(
        semaphore_workspaces_identity=identity,
        OPENBAO_MONITORING_ROLE=values["OPENBAO_MONITORING_ROLE"],
        OPENBAO_MONITORING_TEMPLATE=values["OPENBAO_MONITORING_TEMPLATE"],
        OPENBAO_JWT_AUDIENCE=services["openbao"]["workspaces"]["audience"],
        OPENBAO_JWT_TOKEN_TTL=services["openbao"]["workspaces"]["token_ttl"],
    )
    return json.loads(rendered)


def tenant_path(path: str) -> str:
    return path.replace(
        f"/{WS}/", f"/{{{{identity.entity.aliases.{JWT_ACCESSOR}.metadata.role}}}}/"
    )


class TestTheMonitoringPolicy(unittest.TestCase):
    def test_the_policy_reads_exactly_the_monitoring_secrets(self) -> None:
        self.assertEqual(parse(render("monitoring")), GRANTS)

    def test_the_policy_reaches_nothing_beyond_its_paths(self) -> None:
        grants = parse(render("monitoring"))
        for path in (
            "platform/metadata/monitoring/",
            "platform/metadata/monitoring/checkmk",
            "platform/data/monitoring/federation/ws-0a/target/extra",
            "platform/data/store/semaphore",
            "tenant/data/ws-0a/x",
            "tenant/data/ws-0a/ssh",
            "tenant/data/ws-0a/monitoring/target",
            "monitoring/data/shared",
            "monitoring/metadata/",
        ):
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), set())
        for path in (CHECKMK, INVENTORY_KEY, AGENT_KEY_SOURCE):
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), {"read"})

    def test_the_policy_reads_but_never_writes_or_deletes_a_tombstone(self) -> None:
        grants = parse(render("monitoring"))
        for path in TOMBSTONES:
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), {"read"})
                self.assertEqual(
                    effective(grants, path.replace("/data/", "/metadata/")), set()
                )
        for path in (
            f"monitoring/data/{WS}/other/target",
            f"monitoring/metadata/{WS}/other/target",
            f"monitoring/data/{WS}/agent",
        ):
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), set())

    def test_control_a_widened_monitoring_grant_fails(self) -> None:
        grants = planted(
            "monitoring", 'path "platform/data/*" {\n  capabilities = ["read"]\n}'
        )
        self.assertNotEqual(grants, GRANTS)

    def test_the_deploy_writes_the_policy(self) -> None:
        values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        self.assertIn(
            values["OPENBAO_MONITORING_ROLE"], values["OPENBAO_TENANCY_POLICIES"]
        )


class TestNoOtherReader(unittest.TestCase):
    def test_no_other_template_policy_nor_the_store_approle_reads_a_secret(
        self,
    ) -> None:
        for policy in OTHER_READERS:
            grants = parse(render(policy))
            for path in SECRETS:
                with self.subTest(policy=policy, path=path):
                    self.assertNotIn("read", effective(grants, path))

    def test_control_a_store_policy_reading_the_secrets_is_caught(self) -> None:
        grants = planted(
            "store", 'path "platform/data/monitoring/*" {\n  capabilities = ["read"]\n}'
        )
        self.assertIn("read", effective(grants, TOKEN))

    def test_a_workspace_deploy_reads_its_digest_and_no_token(self) -> None:
        grants = parse(render("tenant"))
        for path in PROTECTED:
            with self.subTest(path=path):
                self.assertEqual(effective(grants, tenant_path(path)), {"read"})
        for path in (TOKEN, FOREIGN_TOKEN, AGENT_KEY_SOURCE):
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), set())

    def test_a_workspace_reads_its_monitored_hosts_and_never_changes_them(
        self,
    ) -> None:
        grants = parse(render("tenant"))
        self.assertEqual(effective(grants, tenant_path(MONITORED)), {"read"})
        for path in UNCHANGEABLE:
            with self.subTest(path=path):
                self.assertEqual(effective(grants, tenant_path(path)), set())

    def test_control_a_tenant_delete_on_the_monitored_hosts_is_caught(self) -> None:
        grants = planted(
            "tenant",
            'path "platform/metadata/monitoring/inventory/+/hosts/+" {\n'
            '  capabilities = ["delete"]\n}',
        )
        self.assertEqual(effective(grants, tenant_path(UNCHANGEABLE[0])), {"delete"})

    def test_the_monitoring_policy_writes_the_monitored_hosts(self) -> None:
        grants = parse(render("monitoring"))
        self.assertEqual(effective(grants, MONITORED), {"create", "read", "update"})
        self.assertEqual(effective(grants, UNCHANGEABLE[0]), set())

    def test_the_store_approle_neither_reads_nor_writes_the_protected_paths(
        self,
    ) -> None:
        grants = parse(render("store"))
        for path in PROTECTED + tuple(
            path.replace("/data/", "/metadata/") for path in PROTECTED
        ):
            with self.subTest(path=path):
                self.assertEqual(effective(grants, path), set())

    def test_control_a_store_grant_on_the_monitoring_mount_is_caught(self) -> None:
        grants = planted(
            "store", 'path "monitoring/data/ws-*" {\n  capabilities = ["update"]\n}'
        )
        self.assertEqual(effective(grants, DIGEST), {"update"})

    def test_the_monitoring_mount_is_a_kv_tenancy_mount_of_its_own(self) -> None:
        values = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
        mounts = {values["OPENBAO_TENANT_MOUNT"], values["OPENBAO_PLATFORM_MOUNT"]}
        self.assertNotIn(values["OPENBAO_MONITORING_MOUNT"], mounts)
        self.assertIn(
            "{{ OPENBAO_MONITORING_MOUNT }}", values["OPENBAO_KV_TENANCY_MOUNTS"]
        )


class TestTheMonitoringRole(unittest.TestCase):
    def test_the_role_binds_the_monitoring_template_alone(self) -> None:
        body = role_body(IDENTITY)
        self.assertEqual(body["bound_claims"], {"project_id": 3, "template_id": [41]})
        self.assertEqual(body["token_policies"], ["monitoring"])
        self.assertEqual(body["user_claim"], "sub")

    def test_control_another_template_does_not_match(self) -> None:
        body = role_body(IDENTITY)
        self.assertNotIn(
            IDENTITY["templates"]["workspace"]["template_id"],
            body["bound_claims"]["template_id"],
        )

    def test_the_binding_asserts_integer_ids(self) -> None:
        tasks = load_yaml_any(str(ROLE_DIR / "tasks/07_workspaces.yml"))
        block = next(
            task
            for task in tasks
            if task.get("name")
            == "🎫 Bind the monitoring template once Semaphore reports its ids"
        )
        self.assertEqual(
            block["block"][0]["ansible.builtin.assert"]["that"],
            [
                "semaphore_workspaces_identity.project_id is integer",
                "semaphore_workspaces_identity.templates[OPENBAO_MONITORING_TEMPLATE].template_id is integer",
            ],
        )


if __name__ == "__main__":
    unittest.main()
