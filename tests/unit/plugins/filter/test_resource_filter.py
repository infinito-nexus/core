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


if __name__ == "__main__":
    unittest.main()
