from __future__ import annotations

import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.litellm.gateway import (
    FilterModule,
    litellm_gateway_keys,
    litellm_gateway_refusal,
)

INTERNAL = 4000
PUBLISHED = 8081
LOOPBACK = ("127.0.0.1", "localhost")
GATEWAY_MESH = "10.100.0.1"
OTHER_MESH = "10.100.0.3"
GATEWAY_VHOST = "litellm.infinito.example.internal"


class TestContainerNetwork(unittest.TestCase):
    def refusal(self, url, own_domain=""):
        return litellm_gateway_refusal(
            url, "container", INTERNAL, own_domain=own_domain
        )

    def test_the_gateway_service_on_its_internal_port_is_allowed(self):
        self.assertEqual(self.refusal("http://litellm:4000"), "")

    def test_a_public_domain_is_refused(self):
        self.assertIn("dotted", self.refusal("http://litellm.infinito.example:4000"))

    def test_the_published_port_is_refused(self):
        self.assertIn("port", self.refusal("http://litellm:8081"))

    def test_https_is_refused(self):
        self.assertIn("scheme", self.refusal("https://litellm:4000"))

    def test_the_consumers_own_domain_is_refused(self):
        self.assertIn("own domain", self.refusal("http://wiki:4000", own_domain="wiki"))


class TestLoopback(unittest.TestCase):
    def refusal(self, url):
        return litellm_gateway_refusal(
            url, "loopback", PUBLISHED, loopback_hosts=LOOPBACK
        )

    def test_a_loopback_host_on_the_published_port_is_allowed(self):
        self.assertEqual(self.refusal("http://127.0.0.1:8081"), "")

    def test_a_routable_address_is_refused(self):
        self.assertIn("not one of", self.refusal("http://192.0.2.10:8081"))

    def test_the_internal_port_is_refused(self):
        self.assertIn("port", self.refusal("http://127.0.0.1:4000"))


class TestMesh(unittest.TestCase):
    def refusal(self, url, mesh_address=GATEWAY_MESH):
        return litellm_gateway_refusal(
            url, "mesh", PUBLISHED, mesh_address=mesh_address
        )

    def test_the_gateway_hosts_mesh_address_on_the_published_port_is_allowed(self):
        self.assertEqual(self.refusal("http://10.100.0.1:8081"), "")

    def test_the_mesh_address_of_another_host_is_refused(self):
        refusal = self.refusal(f"http://{OTHER_MESH}:8081")
        self.assertIn(OTHER_MESH, refusal)
        self.assertIn(GATEWAY_MESH, refusal)

    def test_the_admin_ui_domain_is_refused(self):
        self.assertIn("IPv4", self.refusal("http://litellm.infinito.example:8081"))

    def test_a_public_domain_on_https_is_refused(self):
        self.assertIn("scheme", self.refusal("https://litellm.infinito.example"))

    def test_the_container_url_is_refused(self):
        self.assertNotEqual(self.refusal("http://litellm:4000"), "")

    def test_the_internal_port_is_refused(self):
        self.assertIn("port", self.refusal("http://10.100.0.1:4000"))

    def test_a_host_without_a_mesh_peer_for_the_gateway_is_refused(self):
        self.assertIn(
            "no peer", self.refusal("http://10.100.0.1:8081", mesh_address="")
        )


class TestVhost(unittest.TestCase):
    def refusal(self, url, gateway_name=GATEWAY_VHOST):
        return litellm_gateway_refusal(url, "vhost", gateway_name=gateway_name)

    def test_the_gateway_vhost_over_https_is_allowed(self):
        self.assertEqual(self.refusal(f"https://{GATEWAY_VHOST}"), "")

    def test_a_trailing_slash_is_allowed(self):
        self.assertEqual(self.refusal(f"https://{GATEWAY_VHOST}/"), "")

    def test_plain_http_is_refused(self):
        self.assertIn("scheme", self.refusal(f"http://{GATEWAY_VHOST}"))

    def test_the_public_admin_ui_domain_is_refused(self):
        self.assertIn("not exactly", self.refusal("https://llm.ai.infinito.example"))

    def test_an_explicit_port_is_refused(self):
        self.assertIn("not exactly", self.refusal(f"https://{GATEWAY_VHOST}:443"))
        self.assertIn("not exactly", self.refusal(f"https://{GATEWAY_VHOST}:8081"))

    def test_credentials_in_the_url_are_refused(self):
        self.assertIn(
            "not exactly", self.refusal(f"https://consumer:secret@{GATEWAY_VHOST}")
        )

    def test_a_path_or_query_is_refused(self):
        self.assertIn("path", self.refusal(f"https://{GATEWAY_VHOST}/v1"))
        self.assertIn("query", self.refusal(f"https://{GATEWAY_VHOST}/?x=1"))

    def test_the_loopback_port_url_is_refused(self):
        self.assertIn("scheme", self.refusal("http://127.0.0.1:8081"))

    def test_a_gateway_name_inside_public_dns_is_refused(self):
        refusal = self.refusal(
            "https://llm.ai.infinito.example", gateway_name="llm.ai.infinito.example"
        )
        self.assertIn("private-use", refusal)

    def test_an_unnamed_gateway_vhost_is_refused(self):
        self.assertIn("private-use", self.refusal(f"https://{GATEWAY_VHOST}", ""))


class TestModes(unittest.TestCase):
    def test_an_unknown_mode_raises(self):
        with self.assertRaises(AnsibleFilterError):
            litellm_gateway_refusal("http://litellm:4000", "public", INTERNAL)

    def test_a_port_mode_without_a_port_raises(self):
        with self.assertRaises(AnsibleFilterError):
            litellm_gateway_refusal("http://litellm:4000", "container")

    def test_the_filters_are_registered(self):
        self.assertEqual(
            sorted(FilterModule().filters()),
            ["litellm_gateway_keys", "litellm_gateway_refusal"],
        )


class TestGatewayKeys(unittest.TestCase):
    LOCAL = (
        {"alias": "web-app-openwebui", "key": "sk-local-openwebui"},
        {"alias": "web-app-hermes", "key": "sk-local-hermes"},
    )

    def test_local_consumers_keep_their_alias_and_hosts_follow_under_host_aliases(self):
        keys = litellm_gateway_keys(
            list(self.LOCAL),
            {"hotelserver": "sk-host-hotel", "galaxyserver": "sk-host-galaxy"},
        )
        self.assertEqual(
            keys,
            [
                {"alias": "web-app-openwebui", "key": "sk-local-openwebui"},
                {"alias": "web-app-hermes", "key": "sk-local-hermes"},
                {"alias": "host:galaxyserver", "key": "sk-host-galaxy"},
                {"alias": "host:hotelserver", "key": "sk-host-hotel"},
            ],
        )
        aliases = [entry["alias"] for entry in keys]
        self.assertEqual(len(aliases), len(set(aliases)))

    def test_without_consuming_hosts_the_local_list_is_unchanged(self):
        self.assertEqual(litellm_gateway_keys(list(self.LOCAL), {}), list(self.LOCAL))

    def test_a_key_held_twice_is_refused_without_printing_it(self):
        with self.assertRaises(AnsibleFilterError) as raised:
            litellm_gateway_keys(list(self.LOCAL), {"galaxyserver": "sk-local-hermes"})
        self.assertIn("host:galaxyserver", str(raised.exception))
        self.assertNotIn("sk-local-hermes", str(raised.exception))

    def test_an_alias_registered_twice_is_refused(self):
        with self.assertRaises(AnsibleFilterError):
            litellm_gateway_keys(
                [
                    {"alias": "host:galaxyserver", "key": "sk-a"},
                ],
                {"galaxyserver": "sk-b"},
            )

    def test_an_empty_host_key_is_refused(self):
        with self.assertRaises(AnsibleFilterError) as raised:
            litellm_gateway_keys(list(self.LOCAL), {"galaxyserver": ""})
        self.assertIn("galaxyserver", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
