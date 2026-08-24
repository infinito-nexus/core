import importlib.util
import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_plugin_module():
    plugin_path = (
        PROJECT_ROOT
        / "roles"
        / "test-e2e-playwright"
        / "filter_plugins"
        / "discover_playwright_roles.py"
    )
    if not plugin_path.exists():
        raise FileNotFoundError(f"Could not find plugin: {plugin_path}")

    spec = importlib.util.spec_from_file_location(
        "discover_playwright_roles_plugin", plugin_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


_plugin = _load_plugin_module()


class TestDiscoverPlaywrightRoles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="discover_playwright_roles_")
        self.addCleanup(self.tmp.cleanup)
        self.playbook_dir = Path(self.tmp.name)
        (self.playbook_dir / "roles").mkdir(parents=True, exist_ok=True)

    def _create_role(self, role_name: str, with_marker: bool) -> None:
        role_dir = self.playbook_dir / "roles" / role_name
        templates_dir = role_dir / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        if with_marker:
            (templates_dir / "playwright.env.j2").write_text(
                "APP_BASE_URL=https://example.invalid\n",
                encoding="utf-8",
            )

    def test_discovers_roles_from_templates_marker_sorted(self):
        self._create_role("web-app-zeta", with_marker=True)
        self._create_role("web-app-alpha", with_marker=True)
        self._create_role("web-app-ignore", with_marker=False)

        result = _plugin.discover_playwright_roles(str(self.playbook_dir))
        self.assertEqual(result, ["web-app-alpha", "web-app-zeta"])

    def test_only_and_skip_accept_csv_and_iterable(self):
        self._create_role("web-app-a", with_marker=True)
        self._create_role("web-app-b", with_marker=True)
        self._create_role("web-app-c", with_marker=True)

        result = _plugin.discover_playwright_roles(
            str(self.playbook_dir),
            only_roles="web-app-a,web-app-c",
            skip_roles=["web-app-c"],
        )
        self.assertEqual(result, ["web-app-a"])

    def test_missing_roles_dir_raises_ansible_filter_error(self):
        bad_playbook_dir = self.playbook_dir / "missing-root"
        with self.assertRaises(AnsibleFilterError):
            _plugin.discover_playwright_roles(str(bad_playbook_dir))

    def test_invalid_only_roles_type_raises_ansible_filter_error(self):
        self._create_role("web-app-a", with_marker=True)
        with self.assertRaises(AnsibleFilterError):
            _plugin.discover_playwright_roles(str(self.playbook_dir), only_roles=123)

    def test_filter_module_registers_discover_filter(self):
        registry = _plugin.FilterModule().filters()
        self.assertIn("discover_playwright_roles", registry)
        self.assertTrue(callable(registry["discover_playwright_roles"]))

    def test_only_roles_accepts_python_list_repr_string(self):
        self._create_role("web-app-a", with_marker=True)
        self._create_role("web-app-b", with_marker=True)
        self._create_role("web-app-c", with_marker=True)

        result = _plugin.discover_playwright_roles(
            str(self.playbook_dir),
            only_roles="['web-app-a', 'web-app-c']",
        )
        self.assertEqual(result, ["web-app-a", "web-app-c"])

    def test_skip_roles_accepts_python_list_repr_string(self):
        self._create_role("web-app-a", with_marker=True)
        self._create_role("web-app-b", with_marker=True)

        result = _plugin.discover_playwright_roles(
            str(self.playbook_dir),
            skip_roles="['web-app-b']",
        )
        self.assertEqual(result, ["web-app-a"])


if __name__ == "__main__":
    unittest.main()
