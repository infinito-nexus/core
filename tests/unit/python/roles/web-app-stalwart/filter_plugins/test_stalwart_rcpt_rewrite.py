from __future__ import annotations

import importlib.util
import re
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load():
    path = (
        PROJECT_ROOT / "roles/web-app-stalwart/filter_plugins/stalwart_rcpt_rewrite.py"
    )
    spec = importlib.util.spec_from_file_location("stalwart_rcpt_rewrite", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TestStalwartRcptRewrite(unittest.TestCase):
    def setUp(self):
        self.rewrite = _load().stalwart_rcpt_rewrite

    def test_no_alias_domain_rewrites_nothing(self):
        self.assertEqual(self.rewrite([]), {"match": {}, "else": "false"})

    def test_alias_domain_maps_the_local_part_onto_the_target(self):
        result = self.rewrite([{"source": "Legacy.Example", "target": "new.example"}])
        self.assertEqual(
            result,
            {
                "match": {
                    "0": {
                        "if": "matches('(?i)^([^@]+)@legacy\\.example$', rcpt)",
                        "then": "$1 + '@new.example'",
                    }
                },
                "else": "false",
            },
        )

    def test_pattern_matches_only_the_alias_domain(self):
        expression = self.rewrite([{"source": "legacy.example", "target": "n.example"}])
        pattern = re.search(r"matches\('(.*)', rcpt\)", expression["match"]["0"]["if"])
        regex = re.compile(pattern.group(1))
        self.assertEqual(regex.match("Alice@LEGACY.example").group(1), "Alice")
        self.assertIsNone(regex.match("alice@legacyxexample"))
        self.assertIsNone(regex.match("alice@sub.legacy.example"))

    def test_each_alias_domain_gets_its_own_match(self):
        result = self.rewrite(
            [
                {"source": "a.example", "target": "t.example"},
                {"source": "b.example", "target": "t.example"},
            ]
        )
        self.assertEqual(list(result["match"]), ["0", "1"])

    def test_invalid_entries_are_rejected(self):
        for alias_domains in (
            "a.example",
            [{"source": "a.example"}],
            [{"source": "a.example", "target": "a.example"}],
            [{"source": "a'.example", "target": "t.example"}],
            [
                {"source": "a.example", "target": "t.example"},
                {"source": "a.example", "target": "u.example"},
            ],
        ):
            with self.assertRaises(AnsibleFilterError):
                self.rewrite(alias_domains)


if __name__ == "__main__":
    unittest.main()
