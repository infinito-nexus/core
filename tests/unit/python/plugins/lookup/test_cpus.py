import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.cpus import LookupModule

VARS = {"application_id": "web-app-docs"}


def _run(terms, configured, host_cpus=20):
    with (
        patch("plugins.lookup.cpus.ConfigLookup") as config,
        patch("plugins.lookup.cpus.ResourceLookup") as resource,
    ):
        config.return_value.run.return_value = [configured]
        resource.return_value.run.return_value = [host_cpus]
        result = LookupModule().run(terms, variables=VARS)
    return result, config.return_value.run.call_args


class TestCpusLookup(unittest.TestCase):
    def test_a_percentage_becomes_a_share_of_the_host(self):
        result, _ = _run(["web-app-docs", "docs"], "95%")
        self.assertEqual(result, [19.0])

    def test_a_plain_value_passes_through(self):
        result, _ = _run(["web-app-docs", "docs"], "2")
        self.assertEqual(result, ["2"])

    def test_the_service_name_builds_the_config_path(self):
        _, call = _run(["web-app-hermes", "hermes"], "50%")
        self.assertEqual(call.args[0], ["web-app-hermes", "services.hermes.cpus"])

    @patch("plugins.lookup.cpus.get_entity_name", return_value="docs")
    def test_the_entity_name_is_the_default_service(self, _entity):
        _, call = _run(["web-app-docs"], "50%")
        self.assertEqual(call.args[0], ["web-app-docs", "services.docs.cpus"])

    def test_no_terms_is_refused(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([], variables=VARS)

    def test_a_third_term_is_refused(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run(["a", "b", "c"], variables=VARS)


if __name__ == "__main__":
    unittest.main()
