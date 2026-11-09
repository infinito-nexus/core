"""``# nocheck: inventory-open-subtree`` opens one services.yml key for the
inventory; a marker without a reason, on no key, or inside a list opens
nothing, and the real repository opens exactly ``services.wordpress.options``."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.validate.applications import (
    compare_application_keys,
)
from cli.administration.inventory.validate.open_subtrees import (
    markers,
    open_paths,
    open_subtree_paths,
)
from utils.annotations.suppress import marker_reason
from utils.cache.applications import get_application_defaults, get_variants
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

REASON = "the role validates every option at deploy time"
SERVICES = f"""\
wordpress:
  enabled: true
  options: # nocheck: inventory-open-subtree  {REASON}
    permalink_structure: "/%postname%/"
  # nocheck: inventory-open-subtree  {REASON}
  extra:
    a: 1
  bare: # nocheck: inventory-open-subtree
    a: 1
  short: # nocheck: inventory-open-subtree  too short
    a: 1
  items:
    - name: x
      inner: # nocheck: inventory-open-subtree  {REASON}
        a: 1
# nocheck: inventory-open-subtree  {REASON}

other:
  ports:
    local:
      http: 8003
"""


def _lines(text: str = SERVICES) -> list[str]:
    return text.splitlines()


class TestMarkerReason(unittest.TestCase):
    def test_the_text_after_the_rule_is_the_reason(self):
        line = "options: # nocheck: inventory-open-subtree  any option is validated"
        self.assertEqual(
            marker_reason(line, "inventory-open-subtree"), "any option is validated"
        )

    def test_a_bare_marker_states_an_empty_reason(self):
        self.assertEqual(
            marker_reason(
                "a: # nocheck: inventory-open-subtree", "inventory-open-subtree"
            ),
            "",
        )

    def test_a_line_without_the_rule_has_no_reason(self):
        self.assertIsNone(
            marker_reason("a: # nocheck: url  x", "inventory-open-subtree")
        )


class TestMarkers(unittest.TestCase):
    def test_every_marker_is_listed_with_its_path(self):
        found = {number: (path, reason) for number, path, reason in markers(_lines())}
        self.assertEqual(found[3], ("services.wordpress.options", REASON))
        self.assertEqual(found[5], ("services.wordpress.extra", REASON))
        self.assertEqual(found[8], ("services.wordpress.bare", ""))
        self.assertEqual(found[10], ("services.wordpress.short", "too short"))
        self.assertEqual(found[14][0], "services.wordpress.items.[].inner")
        self.assertEqual(found[16], ("", REASON))

    def test_only_reasoned_markers_on_a_mapping_key_open_a_path(self):
        self.assertEqual(
            open_paths(_lines()),
            {"services.wordpress.options", "services.wordpress.extra"},
        )

    def test_a_file_without_markers_opens_nothing(self):
        self.assertEqual(open_paths(["wordpress:", "  options:", "    a: 1"]), set())


class TestRolesDirectory(unittest.TestCase):
    def test_roles_without_markers_are_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            for role, text in (("web-app-a", SERVICES), ("web-app-b", "b:\n  x: 1\n")):
                path = Path(tmp) / role / ROLE_FILE_META_SERVICES
                path.parent.mkdir(parents=True)
                path.write_text(text, encoding="utf-8")
            self.assertEqual(
                open_subtree_paths(tmp),
                {
                    "web-app-a": {
                        "services.wordpress.options",
                        "services.wordpress.extra",
                    }
                },
            )


class TestRepository(unittest.TestCase):
    ROLES = PROJECT_ROOT / "roles"

    def _errors(self, services: dict) -> list[str]:
        return compare_application_keys(
            {"web-app-wordpress": {"services": services}},
            get_application_defaults(roles_dir=self.ROLES),
            "host_vars/example.yml",
            get_variants(roles_dir=self.ROLES),
            open_paths=open_subtree_paths(self.ROLES),
        )

    def test_wordpress_options_is_the_open_subtree(self):
        self.assertEqual(
            open_subtree_paths(self.ROLES).get("web-app-wordpress"),
            {"services.wordpress.options"},
        )

    def test_the_inventory_may_pin_an_undeclared_wordpress_option(self):
        options = {"blogdescription": "Notes", "posts_per_page": 5}
        self.assertEqual(self._errors({"wordpress": {"options": options}}), [])

    def test_an_unknown_key_beside_the_options_still_fails(self):
        result = self._errors({"wordpress": {"optionz": {"blogdescription": "x"}}})
        self.assertEqual(len(result), 2)
        self.assertTrue(
            all("Missing default for web-app-wordpress" in e for e in result)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
