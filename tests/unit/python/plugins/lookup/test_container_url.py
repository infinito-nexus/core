import unittest
import unittest.mock as mock

from ansible.errors import AnsibleError

from plugins.lookup.container_url import LookupModule

APPLICATIONS = {
    "web-svc-translate": {
        "services": {
            "translate": {
                "ports": {"internal": {"http": 8000}, "local": {"http": 8101}}
            }
        }
    },
    "svc-ai-agent-broker": {
        "services": {"agent-broker": {"ports": {"internal": {"http": 9000}}}}
    },
    "web-app-portless": {"services": {"portless": {"ports": {"local": {"http": 80}}}}},
}


def _loader(apps):
    def _get(name, *_a, **_k):
        if name == "applications":
            return mock.MagicMock(run=lambda *_a, **_k: [apps])
        return mock.MagicMock(run=lambda *_a, **_k: [None])

    loader = mock.MagicMock()
    loader.get.side_effect = _get
    return loader


class ContainerUrlTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = LookupModule()
        self.lookup._loader = mock.MagicMock()
        self.patcher = mock.patch(
            "plugins.lookup.container_url.lookup_loader", _loader(APPLICATIONS)
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _run(self, *terms):
        return self.lookup.run(list(terms), variables={})[0]

    def test_it_joins_the_entity_name_with_the_internal_port(self) -> None:
        self.assertEqual(
            self._run("web-svc-translate", "translate"), "http://translate:8000"
        )

    def test_a_service_key_with_a_hyphen_keeps_its_own_port(self) -> None:
        self.assertEqual(
            self._run("svc-ai-agent-broker", "agent-broker"),
            "http://agent-broker:9000",
        )

    def test_the_published_port_is_never_used(self) -> None:
        """A sibling reaching the local port leaves the container network and
        returns through the ingress, which the dns-search suffix turns into
        the public FQDN."""
        self.assertNotIn("8101", self._run("web-svc-translate", "translate"))

    def test_the_protocol_is_plaintext(self) -> None:
        self.assertTrue(
            self._run("web-svc-translate", "translate").startswith("http://")
        )

    def test_the_origin_carries_no_path_or_trailing_slash(self) -> None:
        self.assertFalse(self._run("web-svc-translate", "translate").endswith("/"))

    def test_an_unknown_application_is_refused(self) -> None:
        with self.assertRaises(AnsibleError):
            self._run("web-app-absent", "translate")

    def test_an_unknown_service_key_is_refused(self) -> None:
        with self.assertRaises(AnsibleError):
            self._run("web-svc-translate", "absent")

    def test_a_service_without_an_internal_http_port_is_refused(self) -> None:
        with self.assertRaises(AnsibleError):
            self._run("web-app-portless", "portless")

    def test_a_missing_term_is_refused(self) -> None:
        with self.assertRaises(AnsibleError):
            self._run("web-svc-translate")

    def test_an_empty_term_is_refused(self) -> None:
        with self.assertRaises(AnsibleError):
            self._run("web-svc-translate", "  ")


if __name__ == "__main__":
    unittest.main()
