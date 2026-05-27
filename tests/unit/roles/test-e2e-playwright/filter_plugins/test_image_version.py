import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_plugin_module():
    plugin_path = (
        PROJECT_ROOT
        / "roles"
        / "test-e2e-playwright"
        / "filter_plugins"
        / "image_version.py"
    )
    if not plugin_path.exists():
        raise FileNotFoundError(f"Could not find plugin: {plugin_path}")

    spec = importlib.util.spec_from_file_location("image_version_plugin", plugin_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


class TestImageVersion(unittest.TestCase):
    def setUp(self):
        self.image_version = _load_plugin_module().image_version

    def test_strips_v_prefix_and_distro_suffix(self):
        self.assertEqual(self.image_version("v1.59.1-noble"), "1.59.1")

    def test_strips_v_prefix_without_suffix(self):
        self.assertEqual(self.image_version("v2.0.0"), "2.0.0")

    def test_strips_distro_suffix_without_v_prefix(self):
        self.assertEqual(self.image_version("1.2.3-jammy"), "1.2.3")

    def test_bare_semver_unchanged(self):
        self.assertEqual(self.image_version("1.2.3"), "1.2.3")

    def test_different_distro_suffix(self):
        self.assertEqual(self.image_version("v1.0.0-bookworm"), "1.0.0")

    def test_raises_on_non_string(self):
        with self.assertRaises(AnsibleFilterError):
            self.image_version(123)

    def test_raises_on_none(self):
        with self.assertRaises(AnsibleFilterError):
            self.image_version(None)

    def test_filter_module_registers_filter(self):
        mod = _load_plugin_module()
        filters = mod.FilterModule().filters()
        self.assertIn("image_version", filters)
        self.assertIs(filters["image_version"], mod.image_version)


if __name__ == "__main__":
    unittest.main()
