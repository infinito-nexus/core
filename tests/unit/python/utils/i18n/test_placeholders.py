import unittest

from utils.i18n.placeholders import mask, unmask


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
    def test_dropped_token_discards_the_translation(self):
        source = "Signed out, except {failed} of {total} services."
        masked = mask(source)

        self.assertIsNone(
            unmask('Abgemeldet, außer <x id="0"></x> Diensten.', masked, source)
        )

    def test_duplicated_token_discards_the_translation(self):
        source = "Open {url}"
        masked = mask(source)

        self.assertIsNone(
            unmask('<x id="0"></x> <x id="0"></x> öffnen', masked, source)
        )

    def test_unknown_token_discards_the_translation(self):
        source = "Open {url}"
        masked = mask(source)

        self.assertIsNone(unmask('<x id="7"></x> öffnen', masked, source))

    def test_translator_inventing_a_placeholder_discards_the_translation(self):
        source = "Plain sentence."

        self.assertIsNone(unmask("Satz mit {extra}.", mask(source), source))


class TestPathsStayIntact(unittest.TestCase):
    def test_a_markdown_target_and_its_path_survive_translation(self):
        source = "![Infinito.Nexus Logo](assets/img/logo.png)"
        masked = mask(source)

        self.assertIn("](assets/img/logo.png)", masked.spans)
        self.assertEqual(
            unmask('![<x id="0"></x> Logo<x id="1"></x>', masked, source),
            source,
        )

    def test_a_repository_path_is_masked_whole(self):
        masked = mask("See utils/i18n/placeholders.py for it.")

        self.assertIn("utils/i18n/placeholders.py", masked.spans)

    def test_prose_with_a_slash_stays_translatable(self):
        source = "'enabled' is missing/undefined (treated as active)"

        self.assertEqual(mask(source).spans, ())


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


if __name__ == "__main__":
    unittest.main()
