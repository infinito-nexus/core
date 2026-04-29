# tests/unit/plugins/filter/test_resource_filter.py
import unittest
from unittest.mock import patch
import importlib

# Import the plugin module under test
plugin_module = importlib.import_module("plugins.filter.resource_filter")


class TestResourceFilter(unittest.TestCase):
    def setUp(self):
        # Reload to ensure a clean module state for each test
        importlib.reload(plugin_module)

        self.applications = {"some": "dict"}
        self.application_id = "web-app-foo"
        self.key = "cpus"

        # Patch get and get_entity_name inside the plugin module
        self.patcher_conf = patch.object(plugin_module, "get")
        self.patcher_entity = patch.object(plugin_module, "get_entity_name")
        self.mock_get = self.patcher_conf.start()
        self.mock_get_entity_name = self.patcher_entity.start()
        self.mock_get_entity_name.return_value = "foo"  # derived service name

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
            "0.5",
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
            "0.5",
        )

    def test_returns_hard_default_when_missing(self):
        """
        If the primary value is missing, get (strict=False) should return the provided
        default. We simulate that by returning the default value directly from the mock.
        """
        self.mock_get.return_value = "2g"

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            key="mem_limit",
            service_name="openresty",
            hard_default="2g",
        )

        self.assertEqual(result, "2g")
        self.mock_get.assert_called_once_with(
            self.applications,
            self.application_id,
            "services.openresty.mem_limit",
            False,
            "2g",
        )

    def test_hard_default_passthrough_type(self):
        """Ensure the hard_default (including non-string types) is passed through correctly."""
        self.mock_get.return_value = 2048  # simulate get returning the default

        result = plugin_module.resource_filter(
            self.applications,
            self.application_id,
            key="pids_limit",
            service_name="openresty",
            hard_default=2048,
        )

        self.assertEqual(result, 2048)
        self.mock_get.assert_called_once_with(
            self.applications,
            self.application_id,
            "services.openresty.pids_limit",
            False,
            2048,
        )

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
