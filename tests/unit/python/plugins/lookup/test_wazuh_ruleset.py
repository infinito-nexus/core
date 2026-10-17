from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.wazuh_ruleset import LookupModule
from utils.roles.applications.services.wazuh import SELFTEST_TAG

_SELFTEST = {"program": SELFTEST_TAG, "decoder": SELFTEST_TAG}
_EMPTY = {"selftest": _SELFTEST, "entities": [], "files": [], "samples": []}


def _run(
    roles_dir: Path,
    wazuh: dict,
    groups: dict | None = None,
    scope: str | None = "deployment",
    group_names: list | None = None,
) -> dict:
    """Run the lookup against a temporary roles directory.

    Args:
        roles_dir: directory holding the role fixtures.
        wazuh: ``{role: services.wazuh}``; every key is an application. A
            ``bool`` is shorthand for ``{enabled: <bool>, rule_block: 101000}``.
        groups: inventory groups; defaults to one host per application.
        scope: the lookup's ``scope`` kwarg; ``None`` omits it.
        group_names: this host's groups for ``scope=host``.
    """
    if groups is None:
        groups = {role: ["localhost"] for role in wazuh}
    applications = {role: {} for role in wazuh}
    blocks = {
        role: {"enabled": cfg, "rule_block": 101000} if isinstance(cfg, bool) else cfg
        for role, cfg in wazuh.items()
    }

    def _config(terms, **_k):
        role, path, default = terms
        return [blocks[role].get(path.rsplit(".", 1)[1], default)]

    def _get(name, *a, **k):
        if name == "applications":
            return mock.MagicMock(run=lambda *_a, **_k: [applications])
        if name == "config":
            return mock.MagicMock(run=_config)
        raise AssertionError(name)

    lm = LookupModule()
    lm._loader = mock.MagicMock()
    lm._templar = mock.MagicMock()
    with (
        patch("plugins.lookup.wazuh_ruleset.ROLES_DIR", roles_dir),
        patch("plugins.lookup.wazuh_ruleset.lookup_loader") as loader_mock,
    ):
        loader_mock.get.side_effect = _get
        scope_kwargs = {} if scope is None else {"scope": scope}
        return lm.run(
            [],
            variables={"groups": groups, "group_names": group_names or []},
            **scope_kwargs,
        )[0]


def _ship(roles_dir: Path, role: str, *kinds: str) -> None:
    target = roles_dir / role / "files" / "wazuh"
    target.mkdir(parents=True, exist_ok=True)
    for kind in kinds:
        (target / f"{kind}.xml").write_text("<group/>\n")


def _write_samples(roles_dir: Path, role: str, content: str) -> None:
    target = roles_dir / role / "files" / "wazuh"
    target.mkdir(parents=True, exist_ok=True)
    (target / "samples.yml").write_text(content)


class TestWazuhRuleset(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.roles_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_opted_in_role_ships_both_files(self):
        _ship(self.roles_dir, "web-app-pixelfed", "decoders", "rules")
        self.assertEqual(
            _run(self.roles_dir, {"web-app-pixelfed": True})["files"],
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

    def test_opted_in_role_is_an_entity_with_its_block(self):
        result = _run(
            self.roles_dir,
            {"web-app-pixelfed": {"enabled": True, "rule_block": 101200}},
        )
        self.assertEqual(
            result["entities"],
            [
                {
                    "entity": "pixelfed",
                    "program": "pixelfed",
                    "decoder": "infinito-pixelfed",
                    "rule_block": 101200,
                }
            ],
        )

    def test_selftest_source_comes_from_the_helper(self):
        self.assertEqual(_run(self.roles_dir, {})["selftest"], _SELFTEST)

    def test_rules_only_role_contributes_rules(self):
        _ship(self.roles_dir, "web-app-pixelfed", "rules")
        result = _run(self.roles_dir, {"web-app-pixelfed": True})
        self.assertEqual([f["name"] for f in result["files"]], ["pixelfed_rules.xml"])

    def test_tag_only_role_is_an_entity_without_files(self):
        result = _run(self.roles_dir, {"web-app-pixelfed": True})
        self.assertEqual(result["files"], [])
        self.assertEqual([e["entity"] for e in result["entities"]], ["pixelfed"])

    def test_opt_in_without_rule_block_fails(self):
        with self.assertRaises(AnsibleError):
            _run(self.roles_dir, {"web-app-pixelfed": {"enabled": True}})

    def test_disabled_role_is_skipped(self):
        _ship(self.roles_dir, "web-app-pixelfed", "decoders", "rules")
        self.assertEqual(
            _run(self.roles_dir, {"web-app-pixelfed": False}),
            _EMPTY,
        )

    def test_role_outside_inventory_is_skipped(self):
        _ship(self.roles_dir, "web-app-pixelfed", "rules")
        self.assertEqual(
            _run(self.roles_dir, {"web-app-pixelfed": True}, groups={}),
            _EMPTY,
        )

    def test_role_group_without_hosts_is_skipped(self):
        _ship(self.roles_dir, "web-app-pixelfed", "rules")
        self.assertEqual(
            _run(
                self.roles_dir,
                {"web-app-pixelfed": True},
                groups={"web-app-pixelfed": []},
            ),
            _EMPTY,
        )

    def test_wazuh_role_is_skipped(self):
        _ship(self.roles_dir, "web-app-wazuh", "rules")
        self.assertEqual(
            _run(self.roles_dir, {"web-app-wazuh": True}),
            _EMPTY,
        )

    def test_wazuh_role_samples_are_selftest_samples(self):
        _write_samples(self.roles_dir, "web-app-wazuh", "- log: plain\n  rule: 100100\n  level: 0\n")
        self.assertEqual(
            _run(self.roles_dir, {"web-app-wazuh": True})["samples"],
            [
                {
                    "role": "web-app-wazuh",
                    "program": SELFTEST_TAG,
                    "decoder": SELFTEST_TAG,
                    "lines": ["plain"],
                    "rule": 100100,
                    "level": 0,
                }
            ],
        )

    def test_opted_in_role_samples_carry_tag_and_decoder(self):
        _write_samples(
            self.roles_dir,
            "web-app-pixelfed",
            "- log: [a, b]\n  rule: 101002\n  level: 10\n",
        )
        self.assertEqual(
            _run(self.roles_dir, {"web-app-pixelfed": True})["samples"],
            [
                {
                    "role": "web-app-pixelfed",
                    "program": "pixelfed",
                    "decoder": "infinito-pixelfed",
                    "lines": ["a", "b"],
                    "rule": 101002,
                    "level": 10,
                }
            ],
        )

    def test_disabled_role_samples_are_skipped(self):
        _write_samples(
            self.roles_dir, "web-app-pixelfed", "- log: a\n  rule: 101000\n  level: 0\n"
        )
        self.assertEqual(_run(self.roles_dir, {"web-app-pixelfed": False})["samples"], [])

    def test_host_scope_keeps_only_this_hosts_roles(self):
        result = _run(
            self.roles_dir,
            {"web-app-pixelfed": True, "web-app-zammad": True},
            scope="host",
            group_names=["web-app-zammad"],
        )
        self.assertEqual([e["entity"] for e in result["entities"]], ["zammad"])

    def test_deployment_scope_covers_every_inventory_role(self):
        result = _run(
            self.roles_dir,
            {"web-app-pixelfed": True, "web-app-zammad": True},
            group_names=["web-app-zammad"],
        )
        self.assertEqual(
            [e["entity"] for e in result["entities"]], ["pixelfed", "zammad"]
        )

    def test_missing_scope_fails(self):
        with self.assertRaises(AnsibleError):
            _run(self.roles_dir, {"web-app-pixelfed": True}, scope=None)

    def test_duplicate_entity_name_fails(self):
        _ship(self.roles_dir, "web-app-pixelfed", "rules")
        _ship(self.roles_dir, "web-svc-pixelfed", "rules")
        with self.assertRaises(AnsibleError):
            _run(
                self.roles_dir,
                {"web-app-pixelfed": True, "web-svc-pixelfed": True},
            )

    def test_result_is_sorted(self):
        _ship(self.roles_dir, "web-app-zammad", "decoders", "rules")
        _ship(self.roles_dir, "web-app-akaunting", "rules")
        result = _run(
            self.roles_dir, {"web-app-zammad": True, "web-app-akaunting": True}
        )
        self.assertEqual(
            [f["name"] for f in result["files"]],
            ["zammad_decoders.xml", "akaunting_rules.xml", "zammad_rules.xml"],
        )
        self.assertEqual(
            [e["entity"] for e in result["entities"]], ["akaunting", "zammad"]
        )


if __name__ == "__main__":
    unittest.main()
