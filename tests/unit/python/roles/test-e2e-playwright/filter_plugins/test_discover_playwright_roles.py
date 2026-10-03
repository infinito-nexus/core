import importlib.util
import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import dump_yaml_str

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

    def _declare_run_after(
        self, role_name: str, run_after: list[str], provides: str | None = None
    ) -> None:
        meta_dir = self.playbook_dir / "roles" / role_name / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        (meta_dir / "main.yml").write_text("---\n", encoding="utf-8")
        entity = role_name.removeprefix("web-app-")
        primary = {"run_after": run_after}
        if provides:
            primary["provides"] = provides
        (meta_dir / "services.yml").write_text(
            dump_yaml_str({entity: primary}), encoding="utf-8"
        )

    def test_the_sso_provider_runs_first_even_after_its_mail_provider(self):
        self._create_role("web-app-idp", with_marker=True)
        self._create_role("web-app-mail", with_marker=True)
        self._create_role("web-app-app", with_marker=True)
        self._declare_run_after("web-app-idp", ["web-app-mail"], provides="sso")
        self._declare_run_after("web-app-mail", [])
        self._declare_run_after("web-app-app", ["web-app-idp"])

        result = _plugin.discover_playwright_roles(str(self.playbook_dir))
        self.assertEqual(result, ["web-app-idp", "web-app-mail", "web-app-app"])

    def test_a_provider_runs_before_its_consumer_whatever_the_names(self):
        self._create_role("web-app-alpha", with_marker=True)
        self._create_role("web-app-zeta", with_marker=True)
        self._declare_run_after("web-app-alpha", ["web-app-zeta"])
        self._declare_run_after("web-app-zeta", [])

        result = _plugin.discover_playwright_roles(str(self.playbook_dir))
        self.assertEqual(result, ["web-app-zeta", "web-app-alpha"])

    def test_the_order_holds_through_a_provider_without_specs(self):
        self._create_role("web-app-alpha", with_marker=True)
        self._create_role("web-app-mid", with_marker=False)
        self._create_role("web-app-zeta", with_marker=True)
        self._declare_run_after("web-app-alpha", ["web-app-mid"])
        self._declare_run_after("web-app-mid", ["web-app-zeta"])
        self._declare_run_after("web-app-zeta", [])

        result = _plugin.discover_playwright_roles(
            str(self.playbook_dir), only_roles="web-app-alpha,web-app-zeta"
        )
        self.assertEqual(result, ["web-app-zeta", "web-app-alpha"])

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
