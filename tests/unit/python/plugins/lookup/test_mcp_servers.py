"""Unit tests for ``plugins/lookup/mcp_servers.py``.

Only the pure builder and the credential resolver are exercised; the lookup
wrapper forwards ``roles_with_service``, ``applications`` and ``users`` into
them.
"""

import importlib
import unittest
from typing import ClassVar

from ansible.errors import AnsibleError

plugin_module = importlib.import_module("plugins.lookup.mcp_servers")
build_mcp_discovery = plugin_module.build_mcp_discovery
resolve_credential = plugin_module.resolve_credential
resolve_consumer_id = plugin_module.resolve_consumer_id
role_credentials_of = plugin_module.role_credentials_of

CONSUMER = "web-app-openwebui"

CLIENT = {
    "supported_transports": ["streamable_http", "sse"],
    "supported_auths": ["bearer_token", "app_password"],
}

HOMEASSISTANT = {
    "id": "web-app-homeassistant",
    "auth": "bearer_token",
    "auth_subject": "service_account",
    "transport": "streamable_http",
    "allowed_consumers": [CONSUMER],
    "credential": {
        "owner": "mcp-web-app-homeassistant",
        "source": "token_store",
        "key": "web-app-homeassistant",
    },
    "endpoint": {"service_key": "homeassistant", "port": 8123, "path": "/api/mcp"},
}

CREDENTIALS = {"web-app-homeassistant": ("ha-token", "mcp-web-app-homeassistant")}


def reasons(result):
    return {entry["id"]: entry["reason"] for entry in result["rejected"]}


class TestSelectDeployed(unittest.TestCase):
    """Providers the run does not deploy must not reach a client's config.

    Inventory membership, group_names and the raw whitelist all admit roles the
    play never runs; the deployed set is the whitelist's dependency closure, the
    same one sys-service-loader preloads from.
    """

    SERVERS: ClassVar[list] = [
        {"id": "web-app-homeassistant"},
        {"id": "web-app-prometheus"},
    ]

    def test_a_provider_outside_the_closure_is_dropped(self):
        self.assertEqual(
            ["web-app-homeassistant"],
            [
                s["id"]
                for s in plugin_module.select_deployed(
                    self.SERVERS, {"web-app-hermes", "web-app-homeassistant"}
                )
            ],
        )

    def test_an_unresolvable_closure_filters_nothing(self):
        for closure in (None, set()):
            self.assertEqual(
                2,
                len(plugin_module.select_deployed(self.SERVERS, closure)),
                "dropping every provider would look like a deployment with none",
            )

    def test_no_servers_stays_empty(self):
        self.assertEqual([], plugin_module.select_deployed(None, {"web-app-hermes"}))


class TestBuildMcpDiscovery(unittest.TestCase):
    def test_no_servers_yields_nothing(self):
        for servers in (None, []):
            result = build_mcp_discovery(servers, CONSUMER, CLIENT, {})
            self.assertEqual(result, {"selected": [], "rejected": []})

    def test_authorized_server_becomes_a_container_network_entry(self):
        entry = build_mcp_discovery([HOMEASSISTANT], CONSUMER, CLIENT, CREDENTIALS)[
            "selected"
        ][0]
        self.assertEqual(entry["id"], "web-app-homeassistant")
        self.assertEqual(entry["url"], "http://homeassistant:8123/api/mcp")
        self.assertEqual(entry["token"], "ha-token")
        self.assertEqual(entry["auth"], "bearer_token")
        self.assertEqual(entry["auth_subject"], "service_account")
        self.assertEqual(entry["owner"], "mcp-web-app-homeassistant")
        self.assertEqual(entry["transport"], "streamable-http")

    def test_unlisted_consumer_is_rejected_with_a_reason(self):
        result = build_mcp_discovery(
            [HOMEASSISTANT], "web-app-flowise", CLIENT, CREDENTIALS
        )
        self.assertEqual(result["selected"], [])
        self.assertEqual(
            reasons(result), {"web-app-homeassistant": "consumer_not_allowed"}
        )

    def test_transport_the_client_cannot_speak_is_rejected(self):
        client = dict(CLIENT, supported_transports=["sse"])
        result = build_mcp_discovery([HOMEASSISTANT], CONSUMER, client, CREDENTIALS)
        self.assertEqual(
            reasons(result), {"web-app-homeassistant": "transport_unsupported"}
        )

    def test_auth_the_client_cannot_present_is_rejected(self):
        client = dict(CLIENT, supported_auths=["app_password"])
        result = build_mcp_discovery([HOMEASSISTANT], CONSUMER, client, CREDENTIALS)
        self.assertEqual(reasons(result), {"web-app-homeassistant": "auth_unsupported"})

    def test_unresolved_credential_is_rejected(self):
        result = build_mcp_discovery([HOMEASSISTANT], CONSUMER, CLIENT, {})
        self.assertEqual(
            reasons(result), {"web-app-homeassistant": "credential_missing"}
        )

    def test_incomplete_endpoint_is_rejected(self):
        no_port = dict(HOMEASSISTANT, endpoint={"service_key": "x", "path": "/mcp"})
        result = build_mcp_discovery([no_port], CONSUMER, CLIENT, CREDENTIALS)
        self.assertEqual(
            reasons(result), {"web-app-homeassistant": "endpoint_unreachable"}
        )

    def test_two_providers_sharing_one_credential_abort_discovery(self):
        twin = dict(HOMEASSISTANT, id="web-app-baserow")
        credentials = dict(
            CREDENTIALS,
            **{"web-app-baserow": ("ha-token", "mcp-web-app-homeassistant")},
        )
        with self.assertRaises(AnsibleError):
            build_mcp_discovery([HOMEASSISTANT, twin], CONSUMER, CLIENT, credentials)

    def test_a_client_never_discovers_itself(self):
        itself = dict(HOMEASSISTANT, id=CONSUMER)
        result = build_mcp_discovery([itself], CONSUMER, CLIENT, CREDENTIALS)
        self.assertEqual(result, {"selected": [], "rejected": []})

    def test_a_discovered_url_never_carries_a_secret_path_segment(self):
        """A URL segment cannot be scoped per consumer, nor revoked alone.

        A provider that keys its session that way is fronted by an adapter, so
        the segment stays between adapter and upstream and never reaches a
        client's rendered configuration.
        """
        keyed = dict(
            HOMEASSISTANT,
            endpoint={
                "service_key": "baserow",
                "port": 80,
                "path": "/mcp",
                "key_credential": "mcp_endpoint_key",
                "suffix": "sse",
            },
        )
        entry = build_mcp_discovery([keyed], CONSUMER, CLIENT, CREDENTIALS)["selected"][
            0
        ]
        self.assertEqual(entry["url"], "http://baserow:80/mcp")

    def test_an_endpoint_without_a_port_is_rejected(self):
        portless = dict(HOMEASSISTANT, endpoint={"service_key": "x", "path": "/mcp"})
        result = build_mcp_discovery([portless], CONSUMER, CLIENT, CREDENTIALS)
        self.assertEqual(
            reasons(result), {"web-app-homeassistant": "endpoint_unreachable"}
        )

    def test_order_of_the_discovered_servers_is_kept(self):
        jenkins = dict(HOMEASSISTANT, id="web-app-jenkins")
        credentials = dict(CREDENTIALS, **{"web-app-jenkins": ("jk", "mcp-jenkins")})
        result = build_mcp_discovery(
            [jenkins, HOMEASSISTANT], CONSUMER, CLIENT, credentials
        )
        self.assertEqual(
            [e["id"] for e in result["selected"]],
            ["web-app-jenkins", "web-app-homeassistant"],
        )


class TestAssertAuthorizedAreRenderable(unittest.TestCase):
    assert_renderable = staticmethod(plugin_module.assert_authorized_are_renderable)

    def test_nothing_rejected_passes(self):
        self.assert_renderable({"selected": [], "rejected": []})

    def test_a_narrowing_decision_passes(self):
        self.assert_renderable(
            {
                "selected": [],
                "rejected": [
                    {"id": "a", "reason": "consumer_not_allowed", "detail": "d"}
                ],
            }
        )

    def test_a_provider_not_provisioned_yet_does_not_abort(self):
        self.assert_renderable(
            {
                "selected": [],
                "rejected": [
                    {"id": "a", "reason": "credential_missing", "detail": "d"}
                ],
            }
        )

    def test_a_credential_that_never_resolved_aborts_the_reconciliation(self):
        with self.assertRaises(AnsibleError):
            self.assert_renderable(
                {
                    "selected": [],
                    "rejected": [
                        {"id": "a", "reason": "credential_missing", "detail": "d"}
                    ],
                },
                strict=True,
            )

    def test_a_narrowing_decision_still_passes_under_reconciliation(self):
        self.assert_renderable(
            {
                "selected": [],
                "rejected": [
                    {"id": "a", "reason": "consumer_not_allowed", "detail": "d"}
                ],
            },
            strict=True,
        )

    def test_an_authorized_but_unrenderable_server_aborts(self):
        for reason in (
            "transport_unsupported",
            "auth_unsupported",
            "endpoint_unreachable",
        ):
            with self.subTest(reason=reason), self.assertRaises(AnsibleError):
                self.assert_renderable(
                    {
                        "selected": [],
                        "rejected": [{"id": "a", "reason": reason, "detail": "d"}],
                    }
                )


class TestResolveCredential(unittest.TestCase):
    USERS: ClassVar[dict] = {
        "mcp-web-app-baserow": {"tokens": {"web-app-baserow": " key "}}
    }

    def _server(self, **credential):
        return {"credential": credential}

    def test_token_store_owner_yields_its_stripped_token(self):
        server = self._server(
            owner="mcp-web-app-baserow", source="token_store", key="web-app-baserow"
        )
        self.assertEqual(
            resolve_credential(server, self.USERS, {}), ("key", "mcp-web-app-baserow")
        )

    def test_role_credentials_source_reads_the_role_secret(self):
        server = self._server(
            owner="mcp-web-app-x", source="credentials", key="mcp_token"
        )
        self.assertEqual(
            resolve_credential(server, {}, {"mcp_token": "v"}), ("v", "mcp-web-app-x")
        )

    def test_the_role_secret_is_read_where_the_inventory_writes_it(self):
        """The function was tested; the address its caller used was not.

        Provisioning writes `<role>.secrets.credentials.<key>`, which is also
        how the roles' own vars address it. Discovery read the top-level
        `credentials` and therefore found nothing for all fifteen providers
        whose source is `credentials`, aborting the deploy on a secret that
        had been generated and vaulted all along.
        """
        applications = {
            "web-app-prometheus": {
                "secrets": {"credentials": {"mcp_bearer": "resolved"}}
            }
        }
        self.assertEqual(
            {"mcp_bearer": "resolved"},
            role_credentials_of(applications, "web-app-prometheus"),
        )

    def test_a_top_level_credentials_block_is_not_the_address(self):
        applications = {"web-app-x": {"credentials": {"mcp_bearer": "wrong-place"}}}
        self.assertEqual({}, role_credentials_of(applications, "web-app-x"))

    def test_an_absent_role_yields_an_empty_mapping(self):
        self.assertEqual({}, role_credentials_of({}, "web-app-missing"))

    def test_the_extraction_feeds_resolve_credential(self):
        """End to end: the payload shape provisioning produces must resolve."""
        applications = {
            "web-app-prometheus": {
                "secrets": {"credentials": {"mcp_bearer": "resolved"}}
            }
        }
        server = self._server(
            owner="mcp-web-app-prometheus", source="credentials", key="mcp_bearer"
        )
        self.assertEqual(
            ("resolved", "mcp-web-app-prometheus"),
            resolve_credential(
                server, {}, role_credentials_of(applications, "web-app-prometheus")
            ),
        )

    def test_administrator_owner_resolves_to_nothing(self):
        server = self._server(
            owner="administrator", source="token_store", key="web-app-baserow"
        )
        users = {"administrator": {"tokens": {"web-app-baserow": "k"}}}
        self.assertEqual(resolve_credential(server, users, {}), ("", "administrator"))

    def test_unknown_source_resolves_to_nothing(self):
        server = self._server(owner="o", source="vault", key="k")
        self.assertEqual(resolve_credential(server, {}, {}), ("", "o"))

    def test_missing_declaration_resolves_to_nothing(self):
        self.assertEqual(resolve_credential({}, {}, {}), ("", ""))

    def test_a_blank_stored_token_resolves_to_nothing(self):
        server = self._server(
            owner="mcp-web-app-x", source="token_store", key="web-app-x"
        )
        users = {"mcp-web-app-x": {"tokens": {"web-app-x": "   "}}}
        self.assertEqual(resolve_credential(server, users, {}), ("", "mcp-web-app-x"))

    def test_a_blank_role_credential_resolves_to_nothing(self):
        server = self._server(
            owner="mcp-web-app-x", source="credentials", key="mcp_token"
        )
        self.assertEqual(
            resolve_credential(server, {}, {"mcp_token": ""}), ("", "mcp-web-app-x")
        )

    def test_a_principal_the_store_never_saw_resolves_to_nothing(self):
        server = self._server(
            owner="mcp-web-app-x", source="token_store", key="web-app-x"
        )
        self.assertEqual(resolve_credential(server, {}, {}), ("", "mcp-web-app-x"))


class TestResolveConsumerId(unittest.TestCase):
    """The consumer must be a rendered role id before it is matched.

    sys-svc-mcp-reconcile sets ``application_id`` from a loop variable, so the
    lookup receives the literal ``{{ mcp_client.id }}``. An unrendered id
    matches no ``allowed_consumers``, which rejects every provider as
    ``consumer_not_allowed`` and empties the registry without an error.
    """

    class _Templar:
        def template(self, value):
            return {"{{ mcp_client.id }}": CONSUMER}[value]

    def test_a_deferred_application_id_is_rendered(self):
        self.assertEqual(
            resolve_consumer_id(
                {"application_id": "{{ mcp_client.id }}"}, self._Templar()
            ),
            CONSUMER,
        )

    def test_a_plain_application_id_is_kept(self):
        self.assertEqual(
            resolve_consumer_id({"application_id": CONSUMER}, self._Templar()), CONSUMER
        )

    def test_a_missing_application_id_aborts(self):
        with self.assertRaises(AnsibleError):
            resolve_consumer_id({}, self._Templar())


if __name__ == "__main__":
    unittest.main()
