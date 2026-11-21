import importlib.util
import unittest

from utils import PROJECT_ROOT

SPEC = importlib.util.spec_from_file_location(
    "claude_cli_discovery",
    PROJECT_ROOT / "roles/test-e2e-cli/filter_plugins/discover_cli_roles.py",
)
discovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discovery)


class ClaudeCliDiscoveryTest(unittest.TestCase):
    def test_active_claude_roles_are_discovered_by_the_deploy_harness(self):
        self.assertEqual(
            discovery.discover_cli_roles(
                str(PROJECT_ROOT), group_names=["dsk-code", "dsk-gnt-claude"]
            ),
            ["dsk-code", "dsk-gnt-claude"],
        )

    def test_inactive_claude_role_does_not_run(self):
        self.assertEqual(
            discovery.discover_cli_roles(str(PROJECT_ROOT), group_names=["dsk-code"]),
            ["dsk-code"],
        )

    def test_explicit_role_filter_is_respected(self):
        self.assertEqual(
            discovery.discover_cli_roles(
                str(PROJECT_ROOT),
                group_names=["dsk-code", "dsk-gnt-claude"],
                only_roles=["dsk-gnt-claude"],
            ),
            ["dsk-gnt-claude"],
        )
