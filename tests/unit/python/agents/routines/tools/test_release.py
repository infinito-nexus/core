import unittest

from agents.routines.tools.release import (
    EM_DASH,
    brief_problems,
    measure,
    outline,
    problems,
    since_last_tag,
    skeleton,
)

ENTRIES = [
    ("17.0.1", "2026-11-10", "## [17.0.1] - 2026-11-10\n\nFixed:\n\n- Mail: a fix\n"),
    (
        "17.0.0",
        "2026-11-08",
        (
            "## [17.0.0] - 2026-11-08\n\nAdded:\n\n- i18n: catalogs for 182 languages\n\n"
            "Version jumps (net since 16.2.3):\n\n- *pkgmgr*: v2.0.4 to v2.4.0\n\n"
            "Upgrade notes:\n\n- Odoo: 20.0 cannot move back\n\n"
            "Contributors:\n\n- [Ada](https://github.com/ada)\n"
        ),
    ),
    ("16.2.3", "2026-10-30", "## [16.2.3] - 2026-10-30\n\nFixed:\n\n- Old\n"),
]
TAGS = {"v16.2.3", "v17.0.1"}
LINE = "i18n: catalogs for 182 languages"
LINK = "https://s.infinito.nexus/infinito17"


def _brief(**changes) -> dict:
    brief = skeleton(since_last_tag(ENTRIES, "17.0.0", TAGS), "v16.2.3")
    brief["headline"] = "Every app speaks your language"
    brief["benefits"] = [{"title": f"b{i}", "changelog": [LINE]} for i in range(3)]
    brief.update(changes)
    return brief


def _evidence(brief: dict) -> str:
    return repr(brief)


def _mastodon(extra: str = "") -> str:
    """Return a release post of 480 to 490 characters as Mastodon counts them.

    Args:
        extra: Text put into the opening sentence.
    """
    text = ""
    body = ""
    while len(text) - len(LINK) + 23 < 480:
        body += "Yours. "
        text = (
            f"Infinito.Nexus 17.0.0 speaks 182 languages{extra}.\n\n"
            f"{body.strip()}\n\n{LINK}\n\n#InfinitoNexus"
        )
    return text


def _check(files: dict[str, str], brief: dict | None = None) -> list[str]:
    brief = brief or _brief()
    return problems(files, brief, _evidence(brief), outline(brief, {}))


class TestBrief(unittest.TestCase):
    def test_the_release_takes_its_untagged_patches_until_the_last_tag(self) -> None:
        picked = since_last_tag(ENTRIES, "17.0.0", {"v16.2.3"})
        self.assertEqual([entry[0] for entry in picked], ["17.0.0"])
        picked = since_last_tag(ENTRIES, "17.0.1", {"v16.2.3"})
        self.assertEqual([entry[0] for entry in picked], ["17.0.1", "17.0.0"])

    def test_a_missing_entry_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            since_last_tag(ENTRIES, "18.0.0", TAGS)

    def test_the_skeleton_copies_the_changelog_lines(self) -> None:
        brief = skeleton(since_last_tag(ENTRIES, "17.0.0", TAGS), "v16.2.3")
        self.assertEqual(brief["languages"], ["en"])
        self.assertEqual(brief["changelog"], {"Added": [LINE]})
        self.assertEqual(brief["updated_applications"], ["*pkgmgr*: v2.0.4 to v2.4.0"])
        self.assertEqual(brief["upgrade_notes"], ["Odoo: 20.0 cannot move back"])
        self.assertEqual(brief["links"]["article"], LINK)

    def test_a_brief_the_model_left_open_is_named(self) -> None:
        self.assertEqual(brief_problems(_brief()), [])
        open_brief = _brief(headline="", benefits=[{"changelog": ["invented"]}])
        self.assertEqual(
            brief_problems(open_brief),
            [
                "brief.yml: no headline",
                "brief.yml: 1 benefits, needs 3 to 5",
                "brief.yml: benefit 1 cites no changelog line verbatim",
            ],
        )


class TestInvestorOutline(unittest.TestCase):
    def test_a_section_without_evidence_is_omitted(self) -> None:
        titles = outline(_brief(contributors=[]), {})
        self.assertNotIn("Community", titles)
        self.assertNotIn("Revenue", titles)
        self.assertEqual(titles, ["The Release", "Product Progress", "Ecosystem"])

    def test_the_facts_file_adds_its_sections(self) -> None:
        titles = outline(_brief(), {"revenue": {"arr_eur": 1}, "funding": {}})
        self.assertIn("Revenue", titles)
        self.assertNotIn("Funding", titles)

    def test_an_investor_heading_without_evidence_fails(self) -> None:
        text = (
            "Subject: Infinito.Nexus 17.0.0\nPreheader: 182 languages\n\n"
            "## The Release\n\nText.\n\n## Revenue\n\nText.\n"
        )
        found = _check({"newsletter-investors.en.md": text})
        self.assertEqual(
            found,
            ["newsletter-investors.en.md: section 'Revenue' has no evidence"],
        )


class TestCheck(unittest.TestCase):
    def test_a_clean_post_passes(self) -> None:
        self.assertEqual(_check({"mastodon.en.txt": _mastodon()}), [])

    def test_a_leftover_placeholder_fails(self) -> None:
        found = _check({"mastodon.en.txt": _mastodon(" {{ARTICLE_URL}}")})
        self.assertEqual(
            found, ["mastodon.en.txt: leftover placeholder '{{ARTICLE_URL}}'"]
        )

    def test_an_em_dash_fails(self) -> None:
        found = _check({"mastodon.en.txt": _mastodon(f" {EM_DASH} now")})
        self.assertEqual(found, ["mastodon.en.txt: em dash"])

    def test_a_length_outside_the_bounds_fails(self) -> None:
        found = _check({"mastodon.en.txt": _mastodon() + " More words." * 3})
        self.assertEqual(len(found), 1)
        self.assertRegex(
            found[0], r"^mastodon\.en\.txt: all is 5\d\d mastodon, needs 470 to 500$"
        )
        short = _check({"whatsapp-channel.en.txt": "", "mastodon.en.txt": "Hi."})
        self.assertEqual(
            short,
            [
                "mastodon.en.txt: all is 3 mastodon, needs 470 to 500",
                "whatsapp-channel.en.txt: all is 0 characters, needs 1 to 500",
            ],
        )

    def test_a_number_absent_from_the_brief_fails(self) -> None:
        found = _check({"mastodon.en.txt": _mastodon(" and 250 apps")})
        self.assertEqual(found, ["mastodon.en.txt: number 250 is not in the brief"])

    def test_a_language_nobody_asked_for_fails(self) -> None:
        found = _check(
            {"whatsapp-message.en.txt": "Hallo, Infinito.Nexus 17.0.0 ist da."}
        )
        self.assertEqual(
            found, ["whatsapp-message.en.txt: language en is not asked for"]
        )

    def test_an_unknown_file_fails(self) -> None:
        self.assertEqual(
            _check({"notes.md": "x"}),
            ["notes.md: not a channel file; name it <channel>.<language>.<ext>"],
        )

    def test_markup_is_not_counted_or_checked(self) -> None:
        page = "<style>.a{width:999px}</style><p>Infinito.Nexus 17.0.0</p>"
        self.assertEqual(measure("Infinito.Nexus 17.0.0", "words"), 2)
        found = _check({"article.en.html": page})
        self.assertEqual(found, ["article.en.html: all is 2 words, needs 500 to 600"])


if __name__ == "__main__":
    unittest.main()
