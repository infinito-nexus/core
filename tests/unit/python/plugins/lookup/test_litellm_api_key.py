from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

import plugins.lookup.litellm_api_key as module


class _DummyTemplar:
    def __init__(self):
        self.available_variables = {}


def _run(terms, values):
    lookup = module.LookupModule()
    lookup._templar = _DummyTemplar()
    lookup._loader = MagicMock()
    asked = []

    class _StubConfig:
        def run(self, terms_, variables=None, **kwargs):
            asked.append(tuple(terms_))
            key = (terms_[0], terms_[1])
            if key in values:
                return [values[key]]
            if len(terms_) == 3:
                return [terms_[2]]
            raise AnsibleError(f"missing {key}")

    with patch.object(module.lookup_loader, "get", return_value=_StubConfig()):
        return lookup.run(terms, variables={}), asked


class TestLitellmApiKey(unittest.TestCase):
    OWN = ("web-app-openwebui", "secrets.credentials.litellm_api_key")
    GATEWAY_HOST = ("svc-ai-litellm", "services.litellm.gateway_host")
    HOST_KEY = ("svc-ai-litellm", "secrets.credentials.gateway_key")

    def test_beside_its_own_gateway_a_consumer_presents_its_own_key(self):
        result, asked = _run(
            ["web-app-openwebui"],
            {self.GATEWAY_HOST: "", self.OWN: "sk-own", self.HOST_KEY: "sk-host"},
        )
        self.assertEqual(result, ["sk-own"])
        self.assertNotIn(self.HOST_KEY, [entry[:2] for entry in asked])

    def test_on_a_consuming_host_every_consumer_presents_the_host_key(self):
        for consumer in ("web-app-openwebui", "web-app-hermes", "dsk-gnt-codex"):
            with self.subTest(consumer=consumer):
                result, asked = _run(
                    [consumer],
                    {
                        self.GATEWAY_HOST: "echoserver",
                        self.OWN: "sk-own",
                        self.HOST_KEY: "sk-host",
                    },
                )
                self.assertEqual(result, ["sk-host"])
                self.assertNotIn(
                    "secrets.credentials.litellm_api_key",
                    [entry[1] for entry in asked],
                )

    def test_a_consumer_without_a_key_yields_empty_for_the_contract(self):
        result, _asked = _run(["web-app-hermes"], {self.GATEWAY_HOST: ""})
        self.assertEqual(result, [""])

    def test_exactly_one_application_id_is_required(self):
        for terms in ([], ["a", "b"], [" "]):
            with self.subTest(terms=terms), self.assertRaises(AnsibleError):
                module.LookupModule().run(terms, variables={})


if __name__ == "__main__":
    unittest.main()
