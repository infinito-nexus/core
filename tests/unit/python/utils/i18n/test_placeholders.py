import unittest

from utils.i18n.placeholders import (
    MARKUP,
    TOKEN,
    Rejected,
    mask,
    resegment,
    tighten,
    unmask,
)


class TestMaskRoundTrip(unittest.TestCase):
    def test_translation_with_every_token_restores_the_spans(self):
        source = "Run ``make setup`` for {role}, see https://docs.infinito.nexus/?a=1&b=2 & more."
        masked = mask(source)

        self.assertEqual(len(masked.spans), 3)
        self.assertNotIn("make setup", masked.text)
        translated = masked.text.replace("Run", "Starte").replace(
            "&amp; more", "&amp; mehr"
        )

        self.assertEqual(
            unmask(translated, masked, source),
            "Starte ``make setup`` for {role}, see https://docs.infinito.nexus/?a=1&b=2 & mehr.",
        )

    def test_tokens_may_move(self):
        source = "{done} of {total} services signed out"
        masked = mask(source)
        translated = (
            f'Abgemeldet: {masked.text.split(" of ")[0]} von <x id="1"></x> Diensten'
        )

        self.assertEqual(
            unmask(translated, masked, source),
            "Abgemeldet: {done} von {total} Diensten",
        )

    def test_dotted_names_stay_whole(self):
        source = "Infinito.Nexus serves main.yml, e.g. here."
        masked = mask(source)

        self.assertEqual(masked.spans, ("Infinito.Nexus", "main.yml"))
        self.assertIn("e.g. here", masked.text)


class TestMaskRejects(unittest.TestCase):
    def _rejection(self, translated: str, source: str) -> Rejected:
        rejected = unmask(translated, mask(source), source)
        self.assertIsInstance(rejected, Rejected)
        return rejected

    def test_dropped_token_discards_the_translation(self):
        source = "Signed out, except {failed} of {total} services."

        self.assertEqual(
            self._rejection(
                'Abgemeldet, außer <x id="0"></x> Diensten.', source
            ).reason,
            "lost-token",
        )

    def test_duplicated_token_discards_the_translation(self):
        source = "Open {url}"

        self.assertEqual(
            self._rejection('<x id="0"></x> <x id="0"></x> öffnen', source).reason,
            "lost-token",
        )

    def test_unknown_token_discards_the_translation(self):
        source = "Open {url}"

        self.assertEqual(
            self._rejection('<x id="7"></x> öffnen', source).reason, "unknown-token"
        )

    def test_translator_inventing_a_placeholder_discards_the_translation(self):
        source = "Plain sentence."
        rejected = self._rejection("Satz mit {extra}.", source)

        self.assertEqual(
            (rejected.reason, rejected.text), ("protected-span", "Satz mit {extra}.")
        )


class TestPathsStayIntact(unittest.TestCase):
    def test_a_markdown_target_and_its_path_survive_translation(self):
        source = "![Infinito.Nexus Logo](assets/img/logo.png)"
        masked = mask(source)

        self.assertIn("(assets/img/logo.png)", masked.spans)
        self.assertEqual(
            unmask(
                '!<x id="0"></x><x id="1"></x> Logo<x id="2"></x><x id="3"></x>',
                masked,
                source,
            ),
            source,
        )

    def test_a_markdown_bracket_stays_balanced_for_the_translator(self):
        masked = mask("Generates a new [RSA 4096-bit](https://example.org/a_(b)) key.")

        self.assertEqual(masked.text.count("["), masked.text.count("]"))

    def test_a_repository_path_is_masked_whole(self):
        masked = mask("See utils/i18n/placeholders.py for it.")

        self.assertIn("utils/i18n/placeholders.py", masked.spans)

    def test_prose_with_a_slash_stays_translatable(self):
        source = "'enabled' is missing/undefined (treated as active)"

        self.assertNotIn("missing/undefined", mask(source).spans)
        self.assertIn("missing/undefined", mask(source).text)


class TestIdentifiersStayIntact(unittest.TestCase):
    def test_an_underscored_identifier_is_masked_whole(self):
        masked = mask("Set application_id before the first run.")

        self.assertEqual(masked.spans, ("application_id",))

    def test_a_screaming_identifier_keeps_every_underscore(self):
        source = "X_CONTAINER_ADDRESS: \"{{ lookup('container_address', x) }}\""
        masked = mask(source)

        self.assertIn("X_CONTAINER_ADDRESS", masked.spans)
        self.assertIn("{{ lookup('container_address', x) }}", masked.spans)

    def test_a_jinja_statement_is_masked_whole(self):
        masked = mask("Wrap it in {% if enabled %} to gate the block.")

        self.assertIn("{% if enabled %}", masked.spans)

    def test_prose_without_an_underscore_stays_translatable(self):
        source = "The deploy writes a file to the host and then restarts it."

        self.assertEqual(mask(source).spans, ())

    def test_a_jinja_fragment_without_its_closing_braces_is_masked(self):
        masked = mask("# Mixed conditions. {{ lookup('depends_on', {DB: 'ser")

        self.assertEqual(masked.spans, ("{{ lookup('depends_on', {DB: 'ser",))


class TestNoMarkupReachesTheTranslator(unittest.TestCase):
    """Whatever the construct, the text handed over carries no markup to reformat."""

    def _leaked(self, source: str) -> list[str]:
        rest = TOKEN.sub("", mask(source).text)
        return [character for character in rest if character in MARKUP]

    def test_bold_around_prose_hands_over_the_prose_alone(self):
        self.assertEqual(self._leaked("**Clean up** the stale files."), [])

    def test_a_link_labelled_with_code_hands_over_no_bracket(self):
        source = "Dashboards behind [`web-app-keycloak`](../roles/kc/) are public."

        self.assertEqual(self._leaked(source), [])

    def test_an_unpaired_backtick_is_handed_over_masked(self):
        self.assertEqual(self._leaked("A stray ` backtick in prose."), [])

    def test_prose_survives_the_delimiter_masking(self):
        masked = mask("**Clean up** the stale files.")

        self.assertIn("Clean up", masked.text)


class TestEmphasisStaysTight(unittest.TestCase):
    """Markdown renders no emphasis when a space follows the opening delimiter."""

    def test_a_space_after_the_opener_is_dropped(self):
        self.assertEqual(tighten("** Hinzugefügt**"), "**Hinzugefügt**")

    def test_a_space_before_the_closer_is_dropped_next_to_a_spaced_opener(self):
        self.assertEqual(
            tighten("Wählen Sie **Custom Token **"), "Wählen Sie **Custom Token**"
        )

    def test_a_bullet_list_keeps_its_space(self):
        self.assertEqual(
            tighten("* Punkt eins mit *kursiv*"), "* Punkt eins mit *kursiv*"
        )

    def test_tight_emphasis_is_left_alone(self):
        self.assertEqual(
            tighten("**Fett** und `code` hier"), "**Fett** und `code` hier"
        )


class TestSentenceBoundariesSurvive(unittest.TestCase):
    """A translator reads a trailing token as sentence-final and swallows what follows."""

    def test_a_dropped_full_stop_behind_a_span_comes_back(self):
        restored = resegment(
            "fallen zurück zu `created_at`Ein Wiederholungslauf",
            ("`created_at`",),
            "fall back to `created_at`. A re-run keeps it",
        )

        self.assertEqual(
            restored, "fallen zurück zu `created_at`. Ein Wiederholungslauf"
        )

    def test_a_translation_that_kept_the_boundary_is_left_alone(self):
        restored = resegment(
            "nutze `code` normal weiter", ("`code`",), "use `code` normally here"
        )

        self.assertEqual(restored, "nutze `code` normal weiter")

    def test_a_span_ending_the_sentence_is_left_alone(self):
        restored = resegment("Ende mit `code`.", ("`code`",), "ends with `code`.")

        self.assertEqual(restored, "Ende mit `code`.")


class TestQuotedLiteralsStayIntact(unittest.TestCase):
    """A quoted identifier is a value, not a word: translating it changes what it names."""

    def test_a_single_quoted_identifier_is_masked(self):
        masked = mask("**galaxy_tags**: ['assets', 'nginx', 'static']")

        self.assertIn("'assets'", masked.spans)
        self.assertIn("'static'", masked.spans)

    def test_a_double_quoted_key_is_masked(self):
        masked = mask('"app1": {"in_roles": False}')

        self.assertIn('"in_roles"', masked.spans)

    def test_an_apostrophe_in_prose_is_left_alone(self):
        source = "The role doesn't recreate what it didn't change."

        self.assertEqual(mask(source).spans, ())

    def test_a_quoted_sentence_stays_translatable(self):
        masked = mask('"Re-read the manual and apply every update."')

        self.assertIn("Re-read the manual", masked.text)

    def test_a_bare_double_quote_never_reaches_the_translator(self):
        source = '"epoch"        -> returns "<mtime>"'

        self.assertNotIn('"', TOKEN.sub("", mask(source).text))

    def test_an_english_contraction_keeps_its_apostrophe(self):
        masked = mask("Cloudflare's runtime and the agent's sandbox.")

        self.assertIn("Cloudflare's", masked.text)


class TestNumbersStayIntact(unittest.TestCase):
    """A translator that renumbers a version documents an upgrade that never happened."""

    def test_a_version_pair_is_masked(self):
        masked = mask("*web-app-pgadmin*: 9.17 to 9.18")

        self.assertIn("9.17", masked.spans)
        self.assertIn("9.18", masked.spans)

    def test_a_resource_figure_is_masked(self):
        masked = mask("capped at 4 CPUs and 8 GB of memory")

        self.assertIn("4", masked.spans)
        self.assertIn("8", masked.spans)

    def test_no_digit_reaches_the_translator(self):
        rest = TOKEN.sub("", mask("Wait 30 seconds, then retry 3 times.").text)

        self.assertFalse(any(character.isdigit() for character in rest))


if __name__ == "__main__":
    unittest.main()
