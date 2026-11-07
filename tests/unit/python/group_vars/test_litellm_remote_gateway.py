"""The group_vars that point every consumer at the gateway, local or remote.

A host that names another host's gateway in
``svc-ai-litellm.services.litellm.gateway_host`` must resolve every consumer's
base URL, chat model and usability from the values the inventory pass wrote,
in one place, while a host that names none resolves exactly as before.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

_AI_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "16_ai.yml"

GATEWAY_URL = "http://10.100.0.1:8081"
CONTAINER_URL = "http://litellm:4000"
HOST_URL = "http://127.0.0.1:8081"


def _ansible_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return bool(value)


class TestRemoteGatewayVars(unittest.TestCase):
    source: ClassVar[dict]
    env: ClassVar[Environment]

    @classmethod
    def setUpClass(cls):
        cls.source = load_yaml(_AI_VARS)
        cls.env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders URLs and booleans, not markup
        cls.env.filters["bool"] = _ansible_bool

    def _resolve(
        self, *, gateway_host, groups=(), served=True, local_model="qwen2.5:0.5b"
    ):
        config = {
            "services.litellm.gateway_host": gateway_host,
            "services.litellm.gateway_url": GATEWAY_URL if gateway_host else "",
            "services.litellm.gateway_model": "mock/deterministic"
            if gateway_host
            else "",
            "secrets.credentials.gateway_key": "sk-host" if gateway_host else "",
        }
        peers = {"echoserver": "10.100.0.1"}

        def lookup(kind, *terms, **kwargs):
            if kind == "config":
                return config[terms[1]]
            if kind == "mesh_address":
                return peers.get(kwargs.get("peer"), "")
            raise AssertionError(f"unexpected lookup({kind!r}, {terms!r})")

        values = {
            "lookup": lookup,
            "inventory_hostname": "galaxyserver",
            "group_names": list(groups),
            "LITELLM_BASE_CONTAINER_URL": CONTAINER_URL,
            "LITELLM_BASE_HOST_URL": HOST_URL,
            "LITELLM_LOCAL_CHAT_MODEL": local_model,
            "LITELLM_CHAT_MODEL_SERVED": str(served),
        }
        for name in (
            "LITELLM_GATEWAY_HOST",
            "LITELLM_GATEWAY_REMOTE",
            "LITELLM_GATEWAY_URL",
            "LITELLM_GATEWAY_KEY",
            "LITELLM_GATEWAY_MODEL",
            "LITELLM_GATEWAY_MESH_ADDRESS",
            "LITELLM_SHARED",
            "LITELLM_BASE_LOCAL_URL",
            "LITELLM_BASE_LOOPBACK_URL",
            "LITELLM_CHAT_MODEL",
            "LITELLM_USABLE",
        ):
            values[name] = (
                self.env.from_string(str(self.source[name])).render(**values).strip()
            )
        values["LITELLM_OPENAI_BASE_LOCAL_URL"] = (
            self.env.from_string(self.source["LITELLM_OPENAI_BASE_LOCAL_URL"])
            .render(**values)
            .strip()
        )
        return values

    def test_a_host_without_a_gateway_value_resolves_as_before(self):
        values = self._resolve(gateway_host="", groups=["svc-ai-litellm"])
        self.assertEqual(values["LITELLM_BASE_LOCAL_URL"], CONTAINER_URL)
        self.assertEqual(values["LITELLM_OPENAI_BASE_LOCAL_URL"], CONTAINER_URL + "/v1")
        self.assertEqual(values["LITELLM_BASE_LOOPBACK_URL"], HOST_URL)
        self.assertEqual(values["LITELLM_CHAT_MODEL"], "qwen2.5:0.5b")
        self.assertEqual(values["LITELLM_SHARED"], "True")
        self.assertEqual(values["LITELLM_USABLE"], "True")
        self.assertEqual(values["LITELLM_GATEWAY_MESH_ADDRESS"], "")

    def test_without_its_own_gateway_a_local_host_is_not_usable(self):
        values = self._resolve(gateway_host="", groups=["web-app-openwebui"])
        self.assertEqual(values["LITELLM_USABLE"], "False")

    def test_a_consuming_host_points_every_consumer_at_the_mesh_url(self):
        values = self._resolve(gateway_host="echoserver", groups=["web-app-openwebui"])
        self.assertEqual(values["LITELLM_BASE_LOCAL_URL"], GATEWAY_URL)
        self.assertEqual(values["LITELLM_OPENAI_BASE_LOCAL_URL"], GATEWAY_URL + "/v1")
        self.assertEqual(values["LITELLM_BASE_LOOPBACK_URL"], GATEWAY_URL)
        self.assertEqual(values["LITELLM_GATEWAY_MESH_ADDRESS"], "10.100.0.1")

    def test_a_consuming_host_uses_the_gateway_hosts_model(self):
        values = self._resolve(gateway_host="echoserver")
        self.assertEqual(values["LITELLM_CHAT_MODEL"], "mock/deterministic")

    def test_a_consuming_host_is_usable_without_a_gateway_of_its_own(self):
        values = self._resolve(gateway_host="echoserver", groups=["web-app-openwebui"])
        self.assertEqual(values["LITELLM_USABLE"], "True")

    def test_a_consuming_host_shares_no_local_gateway(self):
        values = self._resolve(gateway_host="echoserver")
        self.assertEqual(values["LITELLM_SHARED"], "False")


if __name__ == "__main__":
    unittest.main()
