import ipaddress
import json
import unittest
from types import SimpleNamespace

import jinja2
from ansible.plugins.filter.core import FilterModule as CoreFilters

from plugins.filter.dotenv import FilterModule
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/svc-ai-freellmapi"
MASKED = "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"


class TestFreeLlmApiEnvironment(unittest.TestCase):
    def test_shared_gateway_declares_the_bridge_subnet_and_compose_attachment(self):
        networks = load_yaml(ROLE / ROLE_FILE_META_NETWORKS)
        subnet = ipaddress.ip_network(networks["local"]["subnet"], strict=True)
        self.assertTrue(subnet.is_private)
        self.assertGreater(subnet.num_addresses, 2)
        self.assertIn("compose", networks["overlay"]["modes"])
        self.assertEqual(networks["overlay"]["topology"], "shared_net")

    def setUp(self):
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(PROJECT_ROOT),
            undefined=jinja2.StrictUndefined,
            autoescape=jinja2.select_autoescape(default_for_string=False),
        )
        self.env.filters["dotenv_quote"] = FilterModule().filters()["dotenv_quote"]
        self.env.filters["combine"] = CoreFilters().filters()["combine"]
        self.env.filters["to_json"] = json.dumps
        self.template = self.env.get_template(
            "roles/svc-ai-freellmapi/templates/env.j2"
        )

    def render(self, config):
        return self.template.render(
            HOST_TIMEZONE="UTC",
            DEPLOYMENT_MODE="compose",
            FREELLMAPI_PORT=3001,
            FREELLMAPI_ENCRYPTION_KEY="a" * 64,
            FREELLMAPI_STARTUP_CONFIG=config,
            FREELLMAPI_ADMIN={
                "email": "admin@example.test",
                "password": 'test$secret"\\\nvalue',
            },
        )

    def startup_config(self, rendered):
        line = next(
            line
            for line in rendered.splitlines()
            if line.startswith("FREEAPI_CONFIG_JSON=")
        )
        return json.loads(json.loads(line.split("=", 1)[1]).replace("$$", "$"))

    def test_empty_provider_config_still_provisions_the_platform_admin(self):
        rendered = self.render({})
        config = self.startup_config(rendered)
        self.assertEqual(
            config,
            {
                "admin": {
                    "email": "admin@example.test",
                    "password": 'test$secret"\\\nvalue',
                }
            },
        )
        self.assertIn("NODE_ENV=production", rendered)
        self.assertIn("PORT=3001", rendered)
        encryption = next(
            line for line in rendered.splitlines() if line.startswith("ENCRYPTION_KEY=")
        )
        self.assertEqual(json.loads(encryption.split("=", 1)[1]), "a" * 64)

    def test_declarative_config_keeps_credentials_in_one_dotenv_assignment(self):
        config = {
            "keys": [{"platform": "openrouter", "key": 'test$secret"\\\nvalue'}],
            "routing": {"strategy": "balanced"},
        }
        rendered = self.render(config)
        assignments = [
            line
            for line in rendered.splitlines()
            if line.startswith("FREEAPI_CONFIG_JSON=")
        ]
        self.assertEqual(len(assignments), 1)
        encoded = assignments[0].split("=", 1)[1]
        value = json.loads(encoded).replace("$$", "$")
        expected = {
            **config,
            "admin": {
                "email": "admin@example.test",
                "password": 'test$secret"\\\nvalue',
            },
        }
        self.assertEqual(json.loads(value), expected)

    def test_startup_config_cannot_replace_the_platform_admin(self):
        config = self.startup_config(
            self.render(
                {
                    "admin": {
                        "email": "other@example.test",
                        "password": "other-password",
                    },
                    "routing": {"strategy": "balanced"},
                }
            )
        )
        self.assertEqual(config["admin"]["email"], "admin@example.test")
        self.assertEqual(config["routing"], {"strategy": "balanced"})

    def test_admin_credentials_are_resolved_from_the_central_users_lookup(self):
        variables = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)
        user = SimpleNamespace(
            email="central@example.test", password="central-password"
        )

        def lookup(kind, identity):
            self.assertEqual((kind, identity), ("users", "platform_administrator"))
            return user

        admin = {
            key: self.env.from_string(value).render(lookup=lookup)
            for key, value in variables["FREELLMAPI_ADMIN"].items()
        }
        self.assertEqual(admin, {"email": user.email, "password": user.password})

    def test_a_missing_encryption_key_fails_the_render(self):
        with self.assertRaises(jinja2.UndefinedError):
            self.template.render(
                HOST_TIMEZONE="UTC",
                DEPLOYMENT_MODE="compose",
                FREELLMAPI_PORT=3001,
                FREELLMAPI_STARTUP_CONFIG={},
            )

    def test_every_deploy_reconciles_after_start_and_masks_the_login_input(self):
        tasks = load_yaml_any(ROLE / "tasks/00_core.yml")
        self.assertEqual(tasks[-1]["ansible.builtin.include_tasks"], "01_admin.yml")
        self.assertTrue(tasks[-2]["vars"]["compose_handlers_flush"])
        reconcile, parse, check, report, persist = load_yaml_any(
            ROLE / "tasks/01_admin.yml"
        )
        self.assertEqual(reconcile["no_log"], MASKED)
        self.assertFalse(reconcile["failed_when"])
        self.assertEqual(parse["no_log"], MASKED)
        self.assertIn(
            "FREELLMAPI_RESULT_PREFIX",
            parse["ansible.builtin.set_fact"]["freellmapi_admin"],
        )
        self.assertEqual(report["when"], "freellmapi_admin.changed | bool")
        payload = self.env.from_string(
            reconcile["ansible.builtin.command"]["stdin"]
        ).render(
            FREELLMAPI_ADMIN={
                "email": "admin@example.test",
                "password": "fixture-password",
            },
            FREELLMAPI_PORT=3001,
            lookup=lambda kind, seconds: seconds,
        )
        self.assertEqual(json.loads(payload)["admin"]["password"], "fixture-password")
        self.assertIn(
            "freellmapi_admin.login_verified | default(false) | bool",
            check["ansible.builtin.assert"]["that"],
        )
        self.assertEqual(persist["no_log"], MASKED)
        self.assertEqual(
            persist["ansible.builtin.include_role"]["name"], "sys-token-store"
        )
        self.assertEqual(
            persist["vars"]["sys_token_store_user_key"], "platform_administrator"
        )
        self.assertEqual(persist["vars"]["sys_token_store_app"], "{{ application_id }}")
        self.assertEqual(
            persist["vars"]["sys_token_store_token"], "{{ freellmapi_admin.api_key }}"
        )

    def test_marked_result_survives_image_import_output(self):
        from ansible.plugins.test.core import TestModule
        from jinja2.nativetypes import NativeEnvironment

        env = NativeEnvironment(undefined=jinja2.StrictUndefined)
        env.filters.update(CoreFilters().filters())
        env.tests.update(TestModule().tests())
        source = load_yaml_any(ROLE / "tasks/01_admin.yml")[1]
        prefix = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)["FREELLMAPI_RESULT_PREFIX"]
        result = env.from_string(
            source["ansible.builtin.set_fact"]["freellmapi_admin"]
        ).render(
            FREELLMAPI_RESULT_PREFIX=prefix,
            freellmapi_admin_result={
                "stdout_lines": [
                    "◇ injected env (0) from .env",
                    prefix + json.dumps({"ok": True, "changed": False}),
                ]
            },
        )
        self.assertEqual(result, {"ok": True, "changed": False})
