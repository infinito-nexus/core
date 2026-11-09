import tempfile
import unittest
from pathlib import Path

from cli.contributing.changelog.extract.contributors import (
    Contributor,
    collect,
    is_bot,
    login_of,
    resolve_logins,
    section,
)

from ._repo import AUTHOR, FixtureRepo

BOB_OLD = ("Bobby", "bob@old.invalid")
BOB = ("Bob Builder", "42+bobb@users.noreply.github.com")
CAROL = "Carol Coder <carol@example.invalid>"
ASSISTANT = "Claude Opus 5.5 <noreply@anthropic.com>"
DEPENDABOT = ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com")


class TestCollect(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = FixtureRepo(Path(self.tmp.name))
        self.repo.write(".mailmap", f"{BOB[0]} <{BOB[1]}> <{BOB_OLD[1]}>\n")
        self.repo.commit("base")
        self.repo.tag("v1.0.0")
        self.repo.commit("one")
        self.repo.commit(
            f"two\n\nCo-authored-by: {CAROL}\nCo-Authored-By: {ASSISTANT}\n"
        )
        self.repo.commit("three", author=BOB_OLD)
        self.repo.commit(f"four\n\nCo-authored-by: {CAROL}\n", author=BOB)
        self.repo.commit("bump", author=DEPENDABOT)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_authors_co_authors_mailmap_and_profiles(self) -> None:
        people = collect(self.repo.root, "v1.0.0", "HEAD", {AUTHOR[1]: "ada-gh"})
        self.assertEqual(
            people,
            [
                Contributor("Ada Author", AUTHOR[1], 2, "https://github.com/ada-gh"),
                Contributor(
                    "Bob Builder", BOB[1].lower(), 2, "https://github.com/bobb"
                ),
                Contributor("Carol Coder", "carol@example.invalid", 2, None),
            ],
        )

    def test_missing_logins_are_resolved_once_per_author(self) -> None:
        asked: list[str] = []

        def lookup(sha: str) -> str | None:
            asked.append(sha)
            return "ada-gh"

        logins = resolve_logins(self.repo.root, "v1.0.0", "HEAD", {}, lookup)
        self.assertEqual(logins, {AUTHOR[1]: "ada-gh"})
        self.assertEqual(len(asked), 1)

    def test_section_links_known_profiles_only(self) -> None:
        text = section(
            [
                Contributor("Ada Author", AUTHOR[1], 2, "https://github.com/ada-gh"),
                Contributor("Carol Coder", "carol@example.invalid", 1, None),
            ]
        )
        self.assertEqual(
            text,
            "Contributors:\n\n- [Ada Author](https://github.com/ada-gh)\n- Carol Coder\n",
        )


class TestIdentities(unittest.TestCase):
    def test_bots_and_assistants_are_bots(self) -> None:
        self.assertTrue(is_bot(*DEPENDABOT))
        self.assertTrue(is_bot("Claude Opus 5.5", "noreply@anthropic.com"))
        self.assertFalse(is_bot(*AUTHOR))

    def test_a_noreply_email_names_its_login(self) -> None:
        self.assertEqual(login_of("42+bobb@users.noreply.github.com", {}), "bobb")
        self.assertIsNone(login_of("carol@example.invalid", {}))


if __name__ == "__main__":
    unittest.main()
