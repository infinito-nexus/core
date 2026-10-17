from __future__ import annotations

import unittest
import unittest.mock as mock
from unittest.mock import patch

from plugins.lookup.wazuh_agent import LookupModule
from utils.roles.applications.services.wazuh import AGENT_ID, AGENT_TIME_RECONNECT


def _run(hostname: str) -> dict:
    calls: list = []

    def _config(terms, **_k):
        calls.append(terms)
        return ["vault-agent-key"]

    lm = LookupModule()
    lm._loader = mock.MagicMock()
    lm._templar = mock.MagicMock(template=lambda value: value)
    with patch("plugins.lookup.wazuh_agent.lookup_loader") as loader_mock:
        loader_mock.get.return_value = mock.MagicMock(run=_config)
        result = lm.run(
            [],
            variables={"inventory_hostname": hostname, "DOMAIN_PRIMARY": "infinito.test"},
        )[0]
    assert calls == [["web-app-wazuh", "secrets.credentials.agent_key"]], calls
    return result


class TestWazuhAgent(unittest.TestCase):
    def test_local_host_is_named_after_the_primary_domain(self):
        for hostname in ("localhost", "127.0.0.1"):
            with self.subTest(hostname=hostname):
                self.assertEqual(_run(hostname)["name"], "infinito.test")

    def test_remote_host_keeps_its_inventory_name(self):
        self.assertEqual(_run("node1.example.org")["name"], "node1.example.org")

    def test_entry_carries_id_key_and_reconnect_interval(self):
        self.assertEqual(
            _run("localhost"),
            {
                "id": AGENT_ID,
                "name": "infinito.test",
                "key": "vault-agent-key",
                "time_reconnect": AGENT_TIME_RECONNECT,
            },
        )


if __name__ == "__main__":
    unittest.main()
