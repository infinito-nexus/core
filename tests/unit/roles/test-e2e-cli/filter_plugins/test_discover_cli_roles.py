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
        / "test-e2e-cli"
        / "filter_plugins"
        / "discover_cli_roles.py"
    )
    if not plugin_path.exists():
        raise FileNotFoundError(f"Could not find plugin: {plugin_path}")

    spec = importlib.util.spec_from_file_location(
        "discover_cli_roles_plugin", plugin_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


_plugin = _load_plugin_module()


class TestDiscoverCliRoles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="discover_cli_roles_")
        self.addCleanup(self.tmp.cleanup)
        self.playbook_dir = Path(self.tmp.name)
        (self.playbook_dir / "roles").mkdir(parents=True, exist_ok=True)

    def _create_role(self, role_name: str, with_marker: bool = True) -> None:
        templates_dir = self.playbook_dir / "roles" / role_name / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        if with_marker:
            (templates_dir / "test.env.j2").write_text("ROLE=test\n", encoding="utf-8")

    def test_discovers_roles_sorted(self):
        self._create_role("svc-runner")
        self._create_role("web-app-foo")
        self._create_role("web-app-bar", with_marker=False)

        result = _plugin.discover_cli_roles(str(self.playbook_dir))
        self.assertEqual(result, ["svc-runner", "web-app-foo"])

    def test_group_names_filters_to_host_roles(self):
        self._create_role("svc-runner")
        self._create_role("web-app-foo")

        result = _plugin.discover_cli_roles(
            str(self.playbook_dir),
            group_names=["web-app-foo"],
        )
        self.assertEqual(result, ["web-app-foo"])

    def test_group_names_excludes_roles_not_on_host(self):
        self._create_role("svc-runner")
        self._create_role("web-app-foo")

        result = _plugin.discover_cli_roles(
            str(self.playbook_dir),
            group_names=["svc-runner"],
        )
        self.assertEqual(result, ["svc-runner"])

    def test_group_names_none_includes_all(self):
        self._create_role("svc-runner")
        self._create_role("web-app-foo")

        result = _plugin.discover_cli_roles(
            str(self.playbook_dir),
            group_names=None,
        )
        self.assertEqual(result, ["svc-runner", "web-app-foo"])

    def test_group_names_empty_list_includes_all(self):
        self._create_role("svc-runner")
        self._create_role("web-app-foo")

        result = _plugin.discover_cli_roles(
            str(self.playbook_dir),
            group_names=[],
        )
        self.assertEqual(result, ["svc-runner", "web-app-foo"])

    def test_group_names_accepts_csv_string(self):
        self._create_role("svc-runner")
        self._create_role("web-app-foo")
        self._create_role("web-app-bar")

        result = _plugin.discover_cli_roles(
            str(self.playbook_dir),
            group_names="svc-runner,web-app-bar",
        )
        self.assertEqual(result, ["svc-runner", "web-app-bar"])

    def test_group_names_and_only_roles_combined(self):
        self._create_role("svc-runner")
        self._create_role("web-app-foo")
        self._create_role("web-app-bar")

        # group_names = on this host; only_roles = in this run
        # intersection: only roles that are both on this host AND in the run
        result = _plugin.discover_cli_roles(
            str(self.playbook_dir),
            group_names=["svc-runner", "web-app-foo"],
            only_roles=["web-app-foo", "web-app-bar"],
        )
        self.assertEqual(result, ["web-app-foo"])

    def test_skip_roles_applied_after_group_filter(self):
        self._create_role("svc-runner")
        self._create_role("web-app-foo")

        result = _plugin.discover_cli_roles(
            str(self.playbook_dir),
            group_names=["svc-runner", "web-app-foo"],
            skip_roles=["web-app-foo"],
        )
        self.assertEqual(result, ["svc-runner"])

    def test_missing_roles_dir_raises(self):
        with self.assertRaises(AnsibleFilterError):
            _plugin.discover_cli_roles(str(self.playbook_dir / "no-such-dir"))

    def test_invalid_group_names_type_raises(self):
        self._create_role("svc-runner")
        with self.assertRaises(AnsibleFilterError):
            _plugin.discover_cli_roles(str(self.playbook_dir), group_names=123)

    def test_filter_module_registers_filter(self):
        registry = _plugin.FilterModule().filters()
        self.assertIn("discover_cli_roles", registry)
        self.assertTrue(callable(registry["discover_cli_roles"]))


if __name__ == "__main__":
    unittest.main()
