from __future__ import annotations

import io
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout

from cli.meta.ci import roundtrip
from utils.roles.display import display_names

DECLARED = {"web-app-nextcloud": [{}] * 9, "svc-db-postgres": [{}]}


class TestEntries(unittest.TestCase):
    def test_a_bare_role_is_variant_zero(self) -> None:
        self.assertEqual(
            roundtrip.entries(["svc-db-postgres"], DECLARED), [("svc-db-postgres", 0)]
        )

    def test_a_pinned_variant_is_kept_in_order(self) -> None:
        self.assertEqual(
            roundtrip.entries(["web-app-nextcloud#8", "svc-db-postgres"], DECLARED),
            [("web-app-nextcloud", 8), ("svc-db-postgres", 0)],
        )

    def test_a_display_name_resolves_to_its_role(self) -> None:
        token = f"{display_names().encode('web-app-nextcloud')}#2"
        self.assertEqual(
            roundtrip.entries([token], DECLARED), [("web-app-nextcloud", 2)]
        )

    def test_an_undeclared_variant_is_refused(self) -> None:
        with self.assertRaisesRegex(SystemExit, "does not declare"):
            roundtrip.entries(["web-app-nextcloud#9"], DECLARED)

    def test_the_last_declared_variant_is_accepted(self) -> None:
        self.assertEqual(
            roundtrip.entries(["web-app-nextcloud#8"], DECLARED),
            [("web-app-nextcloud", 8)],
        )

    def test_an_unknown_role_is_refused(self) -> None:
        with self.assertRaisesRegex(SystemExit, "names no application role"):
            roundtrip.entries(["web-app-does-not-exist"], DECLARED)

    def test_a_pinned_mode_is_refused_as_an_axis_not_a_variant(self) -> None:
        with self.assertRaisesRegex(SystemExit, "pins a deploy axis") as refused:
            roundtrip.entries(["svc-db-postgres@swarm"], DECLARED)
        self.assertNotIn("variant", str(refused.exception).split(";")[0])

    def test_two_variants_in_one_token_are_refused(self) -> None:
        with self.assertRaisesRegex(SystemExit, "pins 2 variants"):
            roundtrip.entries(["web-app-nextcloud#1,2"], DECLARED)

    def test_a_later_bad_token_refuses_the_whole_list(self) -> None:
        with self.assertRaises(SystemExit):
            roundtrip.entries(["svc-db-postgres", "web-app-nextcloud#80"], DECLARED)


class TestMain(unittest.TestCase):
    def test_each_entry_prints_its_role_and_variant(self) -> None:
        out = io.StringIO()
        with (
            mock.patch.object(roundtrip, "get_variants", return_value=DECLARED),
            redirect_stdout(out),
        ):
            self.assertEqual(roundtrip.main(["web-app-nextcloud#8"]), 0)
        self.assertEqual(out.getvalue(), "web-app-nextcloud 8\n")


if __name__ == "__main__":
    unittest.main()
