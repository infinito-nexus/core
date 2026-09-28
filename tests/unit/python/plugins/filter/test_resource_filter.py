import importlib
import unittest
from unittest.mock import patch

plugin_module = importlib.import_module("plugins.filter.resource_filter")


class TestResourceFilter(unittest.TestCase):
    def setUp(self):
        importlib.reload(plugin_module)

        self.applications = {"some": "dict"}
        self.application_id = "web-app-foo"
        self.key = "cpus"

        self.patcher_conf = patch.object(plugin_module, "get")
        self.patcher_entity = patch.object(plugin_module, "get_entity_name")
        self.mock_get = self.patcher_conf.start()
        self.mock_get_entity_name = self.patcher_entity.start()
        self.mock_get_entity_name.return_value = "foo"

    def tearDown(self):
        self.patcher_conf.stop()
        self.patcher_entity.stop()

    def test_primary_service_value_found(self):
        """Returns the value when get finds it for an explicit service."""
        self.mock_get.return_value = "0.75"

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            self.key,
            service_name="openresty",
            hard_default="0.5",
        )

        self.assertEqual(result, "0.75")
        self.mock_get.assert_called_once_with(
            self.applications,
            self.application_id,
            "services.openresty.cpus",
            False,
            plugin_module._UNSET,
        )

    def test_service_name_empty_uses_get_entity_name(self):
        """When service_name is empty, it resolves via get_entity_name(application_id)."""
        self.mock_get.return_value = "1.0"

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            self.key,
            service_name="",
            hard_default="0.5",
        )

        self.assertEqual(result, "1.0")
        self.mock_get_entity_name.assert_called_once_with(self.application_id)
        self.mock_get.assert_called_once_with(
            self.applications,
            self.application_id,
            "services.foo.cpus",
            False,
            plugin_module._UNSET,
        )

    def test_returns_hard_default_when_missing(self):
        """When both the service and the entity key miss, the hard_default wins."""
        self.mock_get.return_value = plugin_module._UNSET

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            key="mem_limit",
            service_name="openresty",
            hard_default="2g",
        )

        self.assertEqual(result, "2g")
        self.assertEqual(self.mock_get.call_count, 2)
        paths = [c.args[2] for c in self.mock_get.call_args_list]
        self.assertEqual(
            paths, ["services.openresty.mem_limit", "services.foo.mem_limit"]
        )

    def test_entity_fallback_when_service_key_missing(self):
        """A miss on the compose-service key falls back to the entity key."""
        self.mock_get.side_effect = [plugin_module._UNSET, "3g"]

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            key="mem_limit",
            service_name="foo-web",
            hard_default="0.2g",
        )

        self.assertEqual(result, "3g")
        paths = [c.args[2] for c in self.mock_get.call_args_list]
        self.assertEqual(
            paths, ["services.foo-web.mem_limit", "services.foo.mem_limit"]
        )

    def test_hard_default_passthrough_type(self):
        """Ensure the hard_default (including non-string types) is passed through correctly."""
        self.mock_get.return_value = plugin_module._UNSET

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            key="pids_limit",
            service_name="openresty",
            hard_default=2048,
        )

        self.assertEqual(result, 2048)

    def test_a_percentage_resolves_against_the_host(self):
        """cpus: 100% in services.yml is every CPU the host has."""
        self.mock_get.return_value = "100%"

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            self.key,
            service_name="openresty",
            hard_default="0.5",
            host_cpus=20,
        )

        self.assertEqual(result, 20.0)

    def test_a_percentage_in_the_hard_default_resolves_too(self):
        """The share applies to the fallback, not only to an explicit key."""
        self.mock_get.return_value = plugin_module._UNSET

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            self.key,
            service_name="openresty",
            hard_default="25%",
            host_cpus=20,
        )

        self.assertEqual(result, 5.0)

    def test_a_plain_value_is_left_alone(self):
        self.mock_get.return_value = "2"

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            self.key,
            service_name="openresty",
            hard_default="0.5",
            host_cpus=20,
        )

        self.assertEqual(result, "2")

    def test_other_keys_keep_a_zero(self):
        """Keys other than cpus pass no host_cpus and must keep their zero."""
        self.mock_get.return_value = 0

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            key="pids_limit",
            service_name="openresty",
            hard_default=2048,
        )

        self.assertEqual(result, 0)

    def test_raises_ansible_filter_error_on_config_errors(self):
        """Underlying config errors must be wrapped as AnsibleFilterError."""
        self.mock_get.side_effect = plugin_module.AppConfigKeyError("bad path")

        with self.assertRaises(plugin_module.AnsibleFilterError):
            plugin_module.resource_filter(
                self.applications,
                self.application_id,
                key="pids_limit",
                service_name="openresty",
                hard_default=2048,
            )


class TestResolveCpus(unittest.TestCase):
    def test_a_share_of_the_host(self):
        for value, expected in (
            ("100%", 20.0),
            ("50%", 10.0),
            ("25%", 5.0),
            ("  10%  ", 2.0),
            ("2.5%", 0.5),
        ):
            with self.subTest(value=value):
                self.assertEqual(plugin_module.resolve_cpus(value, 20), expected)

    def test_a_full_share_lands_on_the_docker_ceiling(self):
        """100% must equal the host count exactly, which is docker's maximum."""
        self.assertEqual(plugin_module.resolve_cpus("100%", 20), 20.0)

    def test_the_host_count_may_arrive_as_a_string(self):
        """RESOURCE_HOST_CPUS comes through a lookup and renders as text."""
        self.assertEqual(plugin_module.resolve_cpus("50%", "20"), 10.0)

    def test_a_share_is_rounded_to_dockers_granularity(self):
        self.assertEqual(plugin_module.resolve_cpus("33%", 20), 6.6)
        self.assertEqual(plugin_module.resolve_cpus("1%", 3), 0.03)

    def test_a_share_never_falls_below_the_smallest_docker_takes(self):
        self.assertEqual(plugin_module.resolve_cpus("0%", 20), 0.01)

    def test_a_plain_value_is_returned_unchanged(self):
        for value in (2, 0.5, "1.5"):
            with self.subTest(value=value):
                self.assertEqual(plugin_module.resolve_cpus(value, 20), value)

    def test_a_bare_zero_is_refused_as_uncapped(self):
        """docker reads cpus 0 as unlimited, so it must not pass silently."""
        with self.assertRaises(plugin_module.AnsibleFilterError):
            plugin_module.resolve_cpus(0, 20)

    def test_more_than_the_host_has_is_refused(self):
        with self.assertRaises(plugin_module.AnsibleFilterError):
            plugin_module.resolve_cpus("120%", 20)

    def test_an_unreadable_percentage_is_refused(self):
        with self.assertRaises(plugin_module.AnsibleFilterError):
            plugin_module.resolve_cpus("half%", 20)

    def test_false_is_not_a_zero(self):
        """bool is an int in Python, and False here would be a config error."""
        self.assertIs(plugin_module.resolve_cpus(False, 20), False)


if __name__ == "__main__":
    unittest.main()
