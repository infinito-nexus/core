from __future__ import annotations

import unittest

from utils.i18n.untranslatable import is_name, untranslatable


class TestUntranslatable(unittest.TestCase):
    def test_a_message_without_a_word_is_withheld(self) -> None:
        self.assertTrue(untranslatable("[`e2e/`](e2e/)"))

    def test_a_brand_on_its_own_is_withheld(self) -> None:
        self.assertTrue(untranslatable("Mastodon"))

    def test_a_credited_person_is_withheld(self) -> None:
        self.assertTrue(untranslatable("Kevin Veen-Birkenbach"))

    def test_the_software_itself_is_withheld(self) -> None:
        for written in ("Infinito.Nexus", "**Infinito.Nexus**", "infinito.nexus"):
            with self.subTest(written):
                self.assertTrue(untranslatable(written))

    def test_a_sentence_about_the_software_is_translated(self) -> None:
        self.assertFalse(untranslatable("Infinito.Nexus is a platform."))

    def test_a_bare_url_is_withheld(self) -> None:
        for address in ("https://veen.world", "www.veen.world", "mailto:a@b.c"):
            with self.subTest(address):
                self.assertTrue(untranslatable(address))

    def test_markdown_around_the_brand_does_not_hide_it(self) -> None:
        for marked in ("**Mastodon**", "*Mastodon*", "`Mastodon`"):
            with self.subTest(marked):
                self.assertTrue(untranslatable(marked))

    def test_a_name_carrying_a_digit_survives_the_stripping(self) -> None:
        for written in ("n8n", "**n8n**", "Mini-QR"):
            with self.subTest(written):
                self.assertTrue(
                    untranslatable(written),
                    "comparing against the prose left 'nn', because masking "
                    "treats the digit as a span of its own",
                )

    def test_the_name_is_matched_whatever_case_the_page_wrote_it_in(self) -> None:
        self.assertTrue(
            untranslatable("**mailu**"),
            "a page writes the name the way its sentence needs it, and the "
            "product is Mailu either way",
        )

    def test_a_link_whose_text_is_the_name_is_withheld(self) -> None:
        for written in (
            "[Baserow](roles/web-app-baserow/)",
            "[Mastodon](https://joinmastodon.org)",
        ):
            with self.subTest(written):
                self.assertTrue(untranslatable(written))

    def test_an_emoji_behind_the_name_does_not_hide_it(self) -> None:
        for written in ("Git 🔐", "Claude Code 🤖"):
            with self.subTest(written):
                self.assertTrue(untranslatable(written))

    def test_a_message_saying_more_than_the_name_is_translated(self) -> None:
        for written in ("Redis ``cache``", "Redis `queue`", "[Documentation](docs/)"):
            with self.subTest(written):
                self.assertFalse(
                    untranslatable(written),
                    "stripping every protected span instead of the decoration "
                    "withheld 131 messages that say more than a name",
                )

    def test_a_link_inside_a_sentence_is_translated(self) -> None:
        self.assertFalse(untranslatable("See [Mastodon](https://x) and more."))

    def test_a_marked_up_description_is_still_translated(self) -> None:
        self.assertFalse(untranslatable("**Cleanup Disc Space**"))

    def test_a_brand_inside_a_marked_up_sentence_is_translated(self) -> None:
        self.assertFalse(untranslatable("See **Mastodon** here."))

    def test_a_sentence_carrying_the_brand_is_translated(self) -> None:
        self.assertFalse(
            untranslatable("Mastodon is a federated social network."),
            "inside a sentence the name is protected by the span machinery and "
            "the sentence around it still needs translating",
        )

    def test_a_descriptive_title_is_translated(self) -> None:
        self.assertFalse(untranslatable("Cleanup Disc Space"))

    def test_an_ordinary_heading_is_translated(self) -> None:
        self.assertFalse(
            untranslatable("Documentation"),
            "a role title that is an ordinary word is not a brand: no upstream "
            "identifier of that role carries it",
        )

    def test_a_url_inside_prose_is_not_a_name(self) -> None:
        self.assertFalse(is_name("See https://veen.world for details."))

    def test_surrounding_whitespace_does_not_hide_a_name(self) -> None:
        self.assertTrue(untranslatable("  Mastodon \n"))


if __name__ == "__main__":
    unittest.main()
