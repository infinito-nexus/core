from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.wazuh_ruleset import LookupModule


def _run(roles_dir: Path, enabled: dict, groups: dict | None = None) -> list:
    """Run the lookup against a temporary roles directory.

    Args:
        roles_dir: directory holding the role fixtures.
        enabled: ``{role: services.wazuh.enabled}``; every key is an application.
        groups: inventory groups; defaults to one host per application.
    """
    if groups is None:
        groups = {role: ["localhost"] for role in enabled}
    applications = {role: {} for role in enabled}

    def _get(name, *a, **k):
        if name == "applications":
            return mock.MagicMock(run=lambda *_a, **_k: [applications])
        if name == "config":
            return mock.MagicMock(run=lambda terms, **_k: [enabled[terms[0]]])
        raise AssertionError(name)

    lm = LookupModule()
    lm._loader = mock.MagicMock()
    lm._templar = mock.MagicMock()
    with (
        patch("plugins.lookup.wazuh_ruleset.ROLES_DIR", roles_dir),
        patch("plugins.lookup.wazuh_ruleset.lookup_loader") as loader_mock,
    ):
        loader_mock.get.side_effect = _get
        return lm.run([], variables={"groups": groups})[0]


def _ship(roles_dir: Path, role: str, *kinds: str) -> None:
    target = roles_dir / role / "files" / "wazuh"
    target.mkdir(parents=True, exist_ok=True)
    for kind in kinds:
        (target / f"{kind}.xml").write_text("<group/>\n")


class TestWazuhRuleset(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_opted_in_role_ships_both_files(self):
        _ship(self.roles_dir, "web-app-pixelfed", "decoders", "rules")
        self.assertEqual(
            _run(self.roles_dir, {"web-app-pixelfed": True}),
            [
                {
                    "src": str(
                        self.roles_dir
                        / "web-app-pixelfed/files/wazuh/decoders.xml"
                    ),
                    "kind": "decoders",
                    "name": "pixelfed_decoders.xml",
                },
                {
                    "src": str(
                        self.roles_dir / "web-app-pixelfed/files/wazuh/rules.xml"
                    ),
                    "kind": "rules",
                    "name": "pixelfed_rules.xml",
                },
            ],
        )

    def test_rules_only_role_contributes_rules(self):
        _ship(self.roles_dir, "web-app-pixelfed", "rules")
        result = _run(self.roles_dir, {"web-app-pixelfed": True})
        self.assertEqual([f["name"] for f in result], ["pixelfed_rules.xml"])

    def test_tag_only_role_contributes_nothing(self):
        self.assertEqual(_run(self.roles_dir, {"web-app-pixelfed": True}), [])

    def test_disabled_role_is_skipped(self):
        _ship(self.roles_dir, "web-app-pixelfed", "decoders", "rules")
        self.assertEqual(_run(self.roles_dir, {"web-app-pixelfed": False}), [])

    def test_role_outside_inventory_is_skipped(self):
        _ship(self.roles_dir, "web-app-pixelfed", "rules")
        self.assertEqual(
            _run(self.roles_dir, {"web-app-pixelfed": True}, groups={}), []
        )

    def test_role_group_without_hosts_is_skipped(self):
        _ship(self.roles_dir, "web-app-pixelfed", "rules")
        self.assertEqual(
            _run(
                self.roles_dir,
                {"web-app-pixelfed": True},
                groups={"web-app-pixelfed": []},
            ),
            [],
        )

    def test_wazuh_role_is_skipped(self):
        _ship(self.roles_dir, "web-app-wazuh", "rules")
        self.assertEqual(_run(self.roles_dir, {"web-app-wazuh": True}), [])

    def test_duplicate_entity_name_fails(self):
        _ship(self.roles_dir, "web-app-pixelfed", "rules")
        _ship(self.roles_dir, "web-svc-pixelfed", "rules")
        with self.assertRaises(AnsibleError):
            _run(
                self.roles_dir,
                {"web-app-pixelfed": True, "web-svc-pixelfed": True},
            )

    def test_result_is_sorted_by_kind_then_name(self):
        _ship(self.roles_dir, "web-app-zammad", "decoders", "rules")
        _ship(self.roles_dir, "web-app-akaunting", "rules")
        result = _run(
            self.roles_dir, {"web-app-zammad": True, "web-app-akaunting": True}
        )
        self.assertEqual(
            [f["name"] for f in result],
            ["zammad_decoders.xml", "akaunting_rules.xml", "zammad_rules.xml"],
        )


if __name__ == "__main__":
    unittest.main()
