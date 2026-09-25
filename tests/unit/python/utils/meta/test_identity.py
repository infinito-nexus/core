from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utils.meta.identity import (
    DOMAIN,
    MAILMAP,
    PROFILE_BASE,
    by_name,
    canonical,
    committing_as,
    profile_url,
)

MAILMAP_BODY = """\
# a comment line
Alejandro Roman Ibanez <alexromanibanez@infinito.nexus> <romanibanez.alex@gmail.com>
Kevin Veen-Birkenbach <kevinveenbirkenbach@infinito.nexus> <kevin@veen.world>
Kevin Veen-Birkenbach <kevinveenbirkenbach@infinito.nexus> Old Name <old@example.com>
<prageethpanicker@infinito.nexus> <prage.pani@gmail.com>
"""


class TestProfileUrl(unittest.TestCase):
    def test_the_local_part_names_the_profile(self) -> None:
        self.assertEqual(
            profile_url(f"kevinveenbirkenbach@{DOMAIN}"),
            f"{PROFILE_BASE}/kevinveenbirkenbach/profile",
        )

    def test_a_foreign_domain_names_no_profile(self) -> None:
        self.assertEqual(profile_url("someone@example.com"), "")

    def test_the_domain_is_matched_case_insensitively(self) -> None:
        self.assertTrue(profile_url(f"someone@{DOMAIN.upper()}"))

    def test_an_empty_local_part_names_no_profile(self) -> None:
        self.assertEqual(profile_url(f"@{DOMAIN}"), "")


class TestMailmap(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="infinito-identity-")
        self.root = Path(self._tmp.name)
        (self.root / MAILMAP).write_text(MAILMAP_BODY, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)
        by_name.cache_clear()
        self.addCleanup(by_name.cache_clear)

    def test_an_alias_folds_into_the_canonical_address(self) -> None:
        self.assertEqual(
            canonical("Alejandro Roman", "romanibanez.alex@gmail.com", self.root),
            ("Alejandro Roman Ibanez", "alexromanibanez@infinito.nexus"),
        )

    def test_an_alias_written_with_a_name_folds_too(self) -> None:
        self.assertEqual(
            canonical("Old Name", "old@example.com", self.root)[1],
            "kevinveenbirkenbach@infinito.nexus",
        )

    def test_an_entry_without_a_canonical_name_keeps_the_commit_name(self) -> None:
        self.assertEqual(
            canonical("Prageeth Panicker", "prage.pani@gmail.com", self.root),
            ("Prageeth Panicker", "prageethpanicker@infinito.nexus"),
        )

    def test_an_unknown_address_is_returned_unchanged(self) -> None:
        self.assertEqual(
            canonical("Nobody", "nobody@example.com", self.root),
            ("Nobody", "nobody@example.com"),
        )

    def test_the_address_is_matched_case_insensitively(self) -> None:
        self.assertEqual(
            canonical("Kevin Veen-Birkenbach", "Kevin@Veen.World", self.root)[1],
            "kevinveenbirkenbach@infinito.nexus",
        )

    def test_by_name_reads_the_canonical_column(self) -> None:
        self.assertEqual(
            by_name(str(self.root))["Kevin Veen-Birkenbach"],
            "kevinveenbirkenbach@infinito.nexus",
        )

    def test_a_missing_mailmap_folds_nothing(self) -> None:
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()

        self.assertEqual(
            canonical("Nobody", "nobody@example.com", empty),
            ("Nobody", "nobody@example.com"),
        )


class TestCommittingAs(unittest.TestCase):
    def test_the_carried_environment_wins_over_git(self) -> None:
        carried = {
            "INFINITO_GIT_AUTHOR_NAME": "Carried Name",
            "INFINITO_GIT_AUTHOR_EMAIL": "carried@example.com",
        }
        with mock.patch.dict("os.environ", carried):
            self.assertEqual(committing_as(), ("Carried Name", "carried@example.com"))

    def test_an_empty_carried_address_falls_through_to_git(self) -> None:
        with mock.patch.dict("os.environ", {"INFINITO_GIT_AUTHOR_EMAIL": "  "}):
            with mock.patch("subprocess.run") as run:
                run.return_value = mock.Mock(stdout="from-git\n")
                self.assertEqual(committing_as(), ("from-git", "from-git"))


if __name__ == "__main__":
    unittest.main()
