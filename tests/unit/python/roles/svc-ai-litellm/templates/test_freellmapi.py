import json
import unittest

from ansible.plugins.filter.core import FilterModule
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from .test_config_model_list import render
from .test_router_hook import load, remote

ROLE = PROJECT_ROOT / "roles/svc-ai-litellm"


class TestFreeLLMAPI(unittest.TestCase):
    def setUp(self):
        self.source = load_yaml(PROJECT_ROOT / "group_vars/all/16_ai.yml")
        self.env = NativeEnvironment(undefined=StrictUndefined, autoescape=False)
        self.env.filters.update(FilterModule().filters())
        self.pool = load_yaml(ROLE / ROLE_FILE_META_SERVICES)["litellm"]["freellmapi"]

    def models(self, enabled):
        def lookup(kind, *terms):
            if kind == "container_url":
                self.assertEqual(terms, ("svc-ai-freellmapi", "freellmapi"))
                return "http://freellmapi:3001"
            self.assertEqual(terms[0], "svc-ai-litellm")
            return self.pool[terms[1].split(".")[-1]]

        return self.env.from_string(self.source["AI_FREELLMAPI_MODELS"]).render(
            lookup=lookup,
            LITELLM_FREELLMAPI_BACKEND=enabled,
        )

    def test_unselected_upstream_is_absent(self):
        self.assertEqual(self.models(False), [])

    def test_selected_upstream_uses_internal_endpoint_and_its_own_key(self):
        models = self.models(True)
        config = render(keys={"freellmapi": "fixture"}, remote_models=models)
        entry = config["model_list"][0]
        self.assertEqual(entry["model_name"], "freellmapi/auto")
        self.assertEqual(entry["litellm_params"]["model"], "openai/auto")
        self.assertEqual(
            entry["litellm_params"]["api_base"], "http://freellmapi:3001/v1"
        )
        self.assertEqual(
            entry["litellm_params"]["api_key"], "os.environ/FREELLMAPI_API_KEY"
        )
        self.assertEqual(entry["model_info"]["traits"], {"local": False, "auto": False})
        aliases = self.env.from_string(self.source["AI_REMOTE_ALIASES"]).render(
            lookup=lambda kind, *terms: [] if kind == "config" else False,
            AI_MOCK_PROVIDER="mock",
            AI_FREELLMAPI_MODELS=models,
        )
        self.assertEqual(aliases, ["freellmapi/auto"])

    def test_automatic_routing_requires_opt_in_and_treats_pool_as_remote(self):
        hook = load()
        need = hook.summarize({})
        route = remote(
            "freellmapi/auto",
            model="openai/auto",
            context=32768,
            traits={"local": False, "auto": False, "tools": True},
        )
        self.assertEqual(hook.eligible([route], need, "auto", {}, "2026-11-02"), [])
        route["model_info"]["traits"]["auto"] = True
        candidates = hook.eligible([route], need, "auto", {}, "2026-11-02")
        self.assertEqual(
            [entry["model_name"] for entry in candidates], ["freellmapi/auto"]
        )
        self.assertFalse(candidates[0]["_caps"]["local"])

    def test_key_is_never_looked_up_when_integration_is_disabled(self):
        source = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)

        def forbidden(*args):
            self.fail("Disabled integration read an upstream credential")

        key = self.env.from_string(
            source["LITELLM_PROVIDER_KEYS"]["freellmapi"]
        ).render(
            lookup=forbidden,
            LITELLM_FREELLMAPI_BACKEND=False,
        )
        self.assertEqual(key, "")

    def test_enabled_integration_reads_the_key_from_the_token_store(self):
        source = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)

        def lookup(kind, user, default):
            self.assertEqual((kind, user), ("users", "platform_administrator"))
            return {"tokens": {"svc-ai-freellmapi": "freellmapi-stored-fixture"}}

        key = self.env.from_string(
            source["LITELLM_PROVIDER_KEYS"]["freellmapi"]
        ).render(lookup=lookup, LITELLM_FREELLMAPI_BACKEND=True)
        self.assertEqual(key, "freellmapi-stored-fixture")

    def test_deploy_probe_uses_the_selected_alias_and_masked_input(self):
        tasks = load_yaml_any(
            PROJECT_ROOT / "roles/svc-ai-litellm/tasks/utils/validate/freellmapi.yml"
        )
        values = {
            "services.litellm.freellmapi.alias": "freellmapi/auto",
            "services.litellm.validation.workers": 3,
            "services.litellm.validation.max_output_tokens": 512,
            "services.codex.reasoning_effort": "medium",
        }
        payload = self.env.from_string(tasks[0]["args"]["stdin"]).render(
            lookup=lambda kind, role, path: values[path],
            LITELLM_PORT=4000,
            LITELLM_UPSTREAM_TIMEOUT=240,
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
        self.assertEqual(payload["model"], "freellmapi/auto")
        self.assertEqual(payload["workers"], 3)
        self.assertEqual(payload["base_url"], "http://127.0.0.1:4000")
        self.assertEqual(tasks[0]["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")
        self.assertIn(
            "litellm_freellmapi_validation.rc == 0",
            tasks[1]["ansible.builtin.assert"]["that"],
        )


if __name__ == "__main__":
    unittest.main()
