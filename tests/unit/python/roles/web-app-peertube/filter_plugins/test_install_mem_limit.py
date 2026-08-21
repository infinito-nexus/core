import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_install_mem_limit_module():
    """
    Load the install_mem_limit.py filter plugin module from the
    roles/web-app-peertube path, without requiring the roles directory to
    be a Python package.
    """
    plugin_path = (
        PROJECT_ROOT
        / "roles"
        / "web-app-peertube"
        / "filter_plugins"
        / "install_mem_limit.py"
    )

    if not plugin_path.is_file():
        raise RuntimeError(f"Could not find install_mem_limit.py at {plugin_path}")

    spec = importlib.util.spec_from_file_location("install_mem_limit", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_install_mem_limit_module()
install_mem_limit = _mod.install_mem_limit
FilterModule = _mod.FilterModule


class TestInstallMemLimitFilter(unittest.TestCase):
    def test_registry_contains_filter(self):
        self.assertIn("install_mem_limit", FilterModule().filters())

    def test_default_overhead_with_string_mem_limit(self):
        self.assertEqual(install_mem_limit("8g", 1024), 12_096_000_000)

    def test_int_mem_limit_is_treated_as_bytes(self):
        self.assertEqual(install_mem_limit(8_000_000_000, 1024), 12_096_000_000)

    def test_custom_overhead(self):
        self.assertEqual(install_mem_limit("8g", 1024, overhead=2), 10_048_000_000)

    def test_small_mem_limit(self):
        self.assertEqual(install_mem_limit("512m", 256), 1_536_000_000)

    def test_binary_suffix_gib(self):
        self.assertEqual(install_mem_limit("1Gib", 128), 1_073_741_824 + 512_000_000)

    def test_string_int_install_heap_mb_accepted(self):
        self.assertEqual(install_mem_limit("8g", "1024"), 12_096_000_000)

    def test_none_mem_limit_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit(None, 1024)

    def test_empty_mem_limit_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit("", 1024)

    def test_unparseable_mem_limit_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit("not-a-size", 1024)

    def test_non_int_install_heap_mb_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit("8g", "not-a-number")

    def test_non_int_overhead_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit("8g", 1024, overhead="lots")

    def test_zero_install_heap_mb_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit("8g", 0)

    def test_negative_install_heap_mb_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit("8g", -1)

    def test_zero_overhead_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit("8g", 1024, overhead=0)

    def test_negative_overhead_raises(self):
        with self.assertRaises(AnsibleFilterError):
            install_mem_limit("8g", 1024, overhead=-1)

    def test_result_is_int(self):
        self.assertIsInstance(install_mem_limit("8g", 1024), int)


if __name__ == "__main__":
    unittest.main()
