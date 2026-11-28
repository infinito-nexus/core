from __future__ import annotations

import unittest

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import load_yaml_any

from ._incus import (
    INCUS,
    LISTEN_SETTING,
    LISTENER,
    NFTABLES,
    ROLE,
    SOURCES_SETTING,
    VARS,
    dropped,
    evaluate,
    ruleset,
)

TASKS = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"), default_if_missing=[])
SERVER = VARS["INCUS_SERVER_CONFIG"]
RUNNER = "10.42.0.7"
RUNNER6 = "fd42::7"
NEIGHBOUR = "10.42.0.8"
NEIGHBOUR6 = "fd42::8"
SOURCES = [RUNNER, f"{RUNNER6}/128"]


def _task(name: str) -> dict:
    return next(task for task in TASKS if task.get("name") == name)


def listener(variables: dict, server: dict = SERVER) -> list[str]:
    """Args:
        variables: ``INCUS_API`` and the stored value of the key.
        server: the role's ``INCUS_SERVER_CONFIG``.

    Returns:
        The argv the reconcile task runs for ``core.https_address``, [] when it
        skips.
    """
    value = evaluate(server["core.https_address"], variables)
    task = _task("🔐 Reconcile the API listener and the join token expiry")
    item = {
        "item": {"key": "core.https_address", "value": value},
        "stdout": variables["stored"],
    }
    if not evaluate(task["when"], {"item": item}):
        return []
    return evaluate(task["ansible.builtin.command"]["argv"], {"item": item})


def admitted(text: str) -> list[str]:
    """Args:
        text: a rendered ruleset.

    Returns:
        Every probe whose verdict breaks the source list.
    """
    probes = (
        ("ipv4", RUNNER, 8443, False),
        ("ipv6", RUNNER6, 8443, False),
        ("ipv4", NEIGHBOUR, 8443, True),
        ("ipv6", NEIGHBOUR6, 8443, True),
        ("ipv4", NEIGHBOUR, 22, False),
    )
    return [
        f"{family} {source}:{port}"
        for family, source, port, drop in probes
        if dropped(text, "input", family=family, saddr=source, dport=port) != drop
    ]


class TestApiListener(unittest.TestCase):
    def test_the_listener_follows_its_switch(self):
        api = dict(INCUS["api"])
        self.assertEqual(
            listener({"INCUS_API": {**api, "enabled": True}, "stored": ""}),
            ["incus", "config", "set", "core.https_address", api["listen"]],
        )
        self.assertEqual(
            listener({"INCUS_API": {**api, "enabled": False}, "stored": api["listen"]}),
            ["incus", "config", "unset", "core.https_address"],
        )
        self.assertEqual(
            listener({"INCUS_API": {**api, "enabled": True}, "stored": api["listen"]}),
            [],
        )
        self.assertEqual(
            listener({"INCUS_API": {**api, "enabled": False}, "stored": ""}), []
        )
        self.assertIs(INCUS["api"]["enabled"], False)
        read = _task("🔍 Read the API listener and the join token expiry")
        self.assertEqual(read["loop"], "{{ INCUS_SERVER_CONFIG | dict2items }}")

    def test_negative_control_a_listener_without_its_switch_is_caught(self):
        mutant = {**SERVER, "core.https_address": "{{ INCUS_API.listen }}"}
        api = {**INCUS["api"], "enabled": False}
        self.assertNotEqual(listener({"INCUS_API": api, "stored": ""}, mutant), [])

    def test_the_firewall_admits_only_the_allowed_sources(self):
        self.assertEqual(admitted(ruleset(NFTABLES, SOURCES)), [])
        nobody = ruleset(NFTABLES, [])
        self.assertTrue(
            dropped(nobody, "input", family="ipv4", saddr=RUNNER, dport=8443)
        )
        self.assertTrue(
            dropped(nobody, "input", family="ipv6", saddr=RUNNER6, dport=8443)
        )
        moved = ruleset(NFTABLES, SOURCES, listen="0.0.0.0:9443")
        self.assertTrue(
            dropped(moved, "input", family="ipv4", saddr=NEIGHBOUR, dport=9443)
        )
        self.assertFalse(
            dropped(moved, "input", family="ipv4", saddr=NEIGHBOUR, dport=8443)
        )
        include = _task(
            "🛡️ Admit the API from its sources only and keep workspace bridges apart"
        )
        self.assertEqual(include["vars"]["FIREWALL_FRAGMENT_ROLE"], "svc-virt-incus")

    def test_negative_control_a_ruleset_without_the_ipv6_rule_is_caught(self):
        mutant = NFTABLES.replace(
            "    meta nfproto ipv6 tcp dport {{ INCUS_API_PORT }} ip6 saddr != @api_ipv6 drop\n",
            "",
        )
        self.assertNotEqual(mutant, NFTABLES)
        self.assertEqual(
            admitted(ruleset(mutant, SOURCES)), [f"ipv6 {NEIGHBOUR6}:8443"]
        )

    def test_a_malformed_source_or_listen_is_refused(self):
        with self.assertRaisesRegex(AnsibleFilterError, SOURCES_SETTING):
            LISTENER.api_listener_sources(["runner.example"], SOURCES_SETTING)
        with self.assertRaisesRegex(AnsibleFilterError, LISTEN_SETTING):
            LISTENER.api_listener_port("[::]", LISTEN_SETTING)
        self.assertEqual(LISTENER.api_listener_port("[::]:8443", LISTEN_SETTING), 8443)
        self.assertEqual(
            VARS["INCUS_API_PORT"],
            f"{{{{ INCUS_API.listen | api_listener_port('{LISTEN_SETTING}') }}}}",
        )
        self.assertEqual(
            LISTENER.api_listener_sources(["10.42.0.0/16", "fd42::7"], SOURCES_SETTING),
            {"ipv4": ["10.42.0.0/16"], "ipv6": ["fd42::7/128"]},
        )

    def test_join_tokens_expire(self):
        self.assertEqual(INCUS["remote_token_expiry"], "1h")
        self.assertEqual(
            SERVER["core.remote_token_expiry"],
            "{{ lookup('config', application_id, 'services.incus.remote_token_expiry') }}",
        )

    def test_the_server_fingerprint_reaches_openbao(self):
        record = _task(
            "📇 Record the API endpoint and the server certificate in OpenBao"
        )
        store = record["block"][1]
        self.assertTrue(
            store["ansible.builtin.include_tasks"].endswith(
                "roles/web-app-openbao/tasks/utils/kv.yml') }}"
            )
        )
        data = store["vars"]["openbao_kv_data"]
        self.assertIn("certificate_fingerprint", data["fingerprint"])
        self.assertEqual(VARS["INCUS_PROVISION_MOUNT"], "platform")
        self.assertEqual(
            VARS["INCUS_PROVISION_PATH"], "provision/incus-{{ inventory_hostname }}"
        )


if __name__ == "__main__":
    unittest.main()
