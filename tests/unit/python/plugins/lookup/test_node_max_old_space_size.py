import unittest
from unittest.mock import patch

import plugins.lookup.node_max_old_space_size as na

try:
    from ansible.errors import AnsibleError
except Exception:
    AnsibleError = Exception


class TestNodeMaxOldSpaceSize(unittest.TestCase):
    """Unit tests for the node_max_old_space_size lookup plugin's core sizing."""

    def setUp(self):
        self.applications = {"web-app-nextcloud": {"services": {"whiteboard": {}}}}
        self.application_id = "web-app-nextcloud"
        self.service_name = "whiteboard"

        self.patcher = patch("plugins.lookup.node_max_old_space_size.get")
        self.mock_get = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def _set_mem_limit(self, value):
        """Helper: mock get to return a specific mem_limit value."""

        def _fake_get(
            applications,
            application_id,
            config_path,
            strict=True,
            default=None,
            **_kwargs,
        ):
            assert application_id == self.application_id
            assert config_path == f"services.{self.service_name}.mem_limit"
            return value

        self.mock_get.side_effect = _fake_get

    def test_512m_below_minimum_raises(self):
        self._set_mem_limit("512m")
        with self.assertRaises(AnsibleError):
            na.node_max_old_space_size(
                self.applications, self.application_id, self.service_name
            )

    def test_2g_caps_to_minimum_768(self):
        self._set_mem_limit("2g")
        mb = na.node_max_old_space_size(
            self.applications, self.application_id, self.service_name
        )
        self.assertEqual(mb, 768)  # 35% of 2g = 700 < 768 -> min wins

    def test_8g_uses_35_percent_without_hitting_hardcap(self):
        self._set_mem_limit("8g")
        mb = na.node_max_old_space_size(
            self.applications, self.application_id, self.service_name
        )
        self.assertEqual(mb, 2800)  # 8g -> 8000 MB * 0.35 = 2800

    def test_16g_hits_hardcap_3072(self):
        self._set_mem_limit("16g")
        mb = na.node_max_old_space_size(
            self.applications, self.application_id, self.service_name
        )
        self.assertEqual(mb, 3072)  # 35% of 16g = 5600, hardcap=3072

    def test_numeric_bytes_input(self):
        self._set_mem_limit(2147483648)
        mb = na.node_max_old_space_size(
            self.applications, self.application_id, self.service_name
        )
        self.assertEqual(mb, 768)  # ~2147 MB; 35% => ~751, min 768 => 768

    def test_invalid_unit_raises_error(self):
        self._set_mem_limit("12x")
        with self.assertRaises(AnsibleError):
            na.node_max_old_space_size(
                self.applications, self.application_id, self.service_name
            )

    def test_missing_mem_limit_raises_error(self):
        self._set_mem_limit(None)
        with self.assertRaises(AnsibleError):
            na.node_max_old_space_size(
                self.applications, self.application_id, self.service_name
            )


if __name__ == "__main__":
    unittest.main()
