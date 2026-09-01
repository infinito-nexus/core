import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cli.meta.roles.applications.bond.edit import EditError, parse_bond, set_bond
from utils.roles.mapping import ROLE_FILE_META_SERVICES

SOURCE = """---
litellm:
  bond: 0.5
  enabled: "{{ 'svc-ai-litellm' in group_names }}"
# nocheck: dockerfile-custom
sso:
  bond: 1 # nocheck: dynamic-flag
  flavor: oidc
ldap:
  enabled: true
"""


class TestSetBond(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.roles = Path(self._tmp.name)
        self.path = self.roles / "web-app-demo" / ROLE_FILE_META_SERVICES
        self.path.parent.mkdir(parents=True)
        self.path.write_text(SOURCE, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")  # nocheck: cache-read — re-reads the file set_bond just rewrote

    def test_rewrites_the_value_in_place(self) -> None:
        self.assertEqual(set_bond(self.roles, "web-app-demo", "litellm", 0.25), "0.25")
        self.assertIn("  bond: 0.25\n", self.read())
        self.assertIn("# nocheck: dockerfile-custom\n", self.read())

    def test_keeps_a_trailing_comment(self) -> None:
        set_bond(self.roles, "web-app-demo", "sso", 0.5)
        self.assertIn("  bond: 0.5 # nocheck: dynamic-flag\n", self.read())

    def test_inserts_a_missing_bond(self) -> None:
        set_bond(self.roles, "web-app-demo", "ldap", 1)
        self.assertIn("ldap:\n  bond: 1\n  enabled: true\n", self.read())

    def test_removes_on_none(self) -> None:
        self.assertEqual(set_bond(self.roles, "web-app-demo", "litellm", None), "")
        self.assertNotIn("bond: 0.5", self.read())
        self.assertIn("litellm:\n  enabled:", self.read())

    def test_rejects_an_unknown_key(self) -> None:
        with self.assertRaises(EditError):
            set_bond(self.roles, "web-app-demo", "nope", 1)

    def test_does_not_match_a_nested_key(self) -> None:
        with self.assertRaises(EditError):
            set_bond(self.roles, "web-app-demo", "flavor", 1)


class TestParseBond(unittest.TestCase):
    def test_blank_clears(self) -> None:
        self.assertIsNone(parse_bond(""))
        self.assertIsNone(parse_bond(" - "))

    def test_rejects_out_of_range(self) -> None:
        for raw in ("2", "-0.1", "abc"):
            with self.assertRaises(EditError):
                parse_bond(raw)

    def test_accepts_the_edges(self) -> None:
        self.assertEqual(parse_bond("0"), 0.0)
        self.assertEqual(parse_bond("1"), 1.0)


if __name__ == "__main__":
    unittest.main()
