"""Unit tests for the repairs a restored translation goes through.

Every case is a shape measured in the catalogs: a bracket that moved in front of
a protected span and took the full stop with it, an opening word the translator
lower-cased, and a run of spaces it opened around a span.
"""

from __future__ import annotations

import unittest
from typing import ClassVar

from utils.i18n.placeholders import (
    collapse,
    harms,
    mask,
    recapitalise,
    resegment,
    terminate,
    tighten,
    truncated,
    unmask,
)


def _round_trip(source: str, translated: str) -> str | None:
    """Send ``translated`` back through the unmasking a real answer goes through.

    Args:
        source: the source message.
        translated: what the translator returned for the masked request.
    """
    return unmask(translated, mask(source), source)


class TestCollapse(unittest.TestCase):
    def test_a_run_the_source_lacks_is_closed(self) -> None:
        self.assertEqual(
            collapse("Works  with the helper", "Works with it"), "Works with the helper"
        )

    def test_a_run_the_source_carries_is_left_alone(self) -> None:
        source = "column  aligned"

        self.assertEqual(
            collapse("Spalte  ausgerichtet", source), "Spalte  ausgerichtet"
        )

    def test_a_tab_in_the_source_disables_the_repair(self) -> None:
        self.assertEqual(collapse("a  b", "a\tb"), "a  b")


class TestTerminate(unittest.TestCase):
    def test_a_lost_full_stop_comes_back(self) -> None:
        source = "Return whether the paths match (as os.path.samefile() does)."

        self.assertEqual(
            terminate("Ob die Pfade gleich sind (wie) os.path.samefile()", source),
            "Ob die Pfade gleich sind (wie) os.path.samefile().",
        )

    def test_a_question_mark_comes_back(self) -> None:
        self.assertEqual(terminate("Ist es bereit", "Is it ready?"), "Ist es bereit?")

    def test_a_translation_that_kept_one_is_untouched(self) -> None:
        self.assertEqual(terminate("Fertig!", "Done."), "Fertig!")

    def test_a_source_without_one_adds_nothing(self) -> None:
        self.assertEqual(terminate("Backup", "Backup"), "Backup")


class TestRecapitalise(unittest.TestCase):
    def test_a_lower_cased_opening_is_restored(self) -> None:
        self.assertEqual(
            recapitalise("alle `alpha` Kriterien.", "All `alpha` criteria."),
            "Alle `alpha` Kriterien.",
        )

    def test_a_lowercase_source_keeps_its_case(self) -> None:
        self.assertEqual(
            recapitalise("alle Kriterien", "all criteria"), "alle Kriterien"
        )

    def test_an_already_capital_opening_is_untouched(self) -> None:
        self.assertEqual(
            recapitalise("Alle Kriterien", "All criteria"), "Alle Kriterien"
        )

    def test_an_opening_protected_span_is_untouched(self) -> None:
        self.assertEqual(
            recapitalise("`alpha` zuerst", "`alpha` first"), "`alpha` zuerst"
        )


class TestUnmaskAppliesTheRepairs(unittest.TestCase):
    def test_a_lower_cased_opening_is_repaired_on_the_way_back(self) -> None:
        restored = _round_trip(
            "All `alpha` criteria.", 'alle <x id="0"></x> Kriterien.'
        )

        self.assertEqual(restored, "Alle `alpha` Kriterien.")

    def test_a_missing_full_stop_is_repaired_on_the_way_back(self) -> None:
        restored = _round_trip("All `alpha` criteria.", 'Alle <x id="0"></x> Kriterien')

        self.assertEqual(restored, "Alle `alpha` Kriterien.")

    def test_a_space_run_is_repaired_on_the_way_back(self) -> None:
        restored = _round_trip(
            "All `alpha` criteria.", 'Alle  <x id="0"></x>  Kriterien.'
        )

        self.assertEqual(restored, "Alle `alpha` Kriterien.")


class TestResegmentLeavesNamesAlone(unittest.TestCase):
    def test_a_suffixed_name_keeps_its_word(self) -> None:
        source = "Adapter to Baserow: the endpoint key"

        self.assertEqual(
            resegment("Baserowo-r shathe", mask(source).spans, source),
            "Baserowo-r shathe",
        )

    def test_a_swallowed_boundary_behind_a_delimiter_is_still_put_back(self) -> None:
        source = "See `compose.yml`. The next sentence."

        self.assertEqual(
            resegment(
                "Siehe `compose.yml`Der naechste Satz.", mask(source).spans, source
            ),
            "Siehe `compose.yml`. Der naechste Satz.",
        )


class TestTruncated(unittest.TestCase):
    def test_a_short_entry_may_shrink(self) -> None:
        self.assertFalse(truncated("Situation", "Lage"))

    def test_a_long_passage_that_halved_is_reported(self) -> None:
        source = "A" * 200

        self.assertTrue(truncated(source, "B" * 80))

    def test_a_long_passage_that_kept_its_body_is_not(self) -> None:
        source = "A" * 200

        self.assertFalse(truncated(source, "B" * 180))


class TestWriterAndGateAgree(unittest.TestCase):
    """The client must reject exactly what the release gate reports.

    A criterion on one side only makes every run rewrite what the other side
    then condemns, so `make i18n-prune` and `make i18n-translate` never
    converge.
    """

    SOURCE: ClassVar[str] = (
        "The deployment registers each service with the reverse proxy and then "
        "waits until every container reports itself healthy before it continues."
    )

    def test_the_client_drops_a_translation_the_gate_would_report(self) -> None:
        halved = "Der Dienst wartet."

        self.assertTrue(harms(self.SOURCE, halved))
        self.assertIsNone(_round_trip(self.SOURCE, halved))

    def test_the_client_keeps_a_translation_the_gate_accepts(self) -> None:
        faithful = (
            "Die Bereitstellung meldet jeden Dienst beim Reverse Proxy an und "
            "wartet dann, bis jeder Container sich als gesund meldet."
        )

        self.assertFalse(harms(self.SOURCE, faithful))
        self.assertEqual(_round_trip(self.SOURCE, faithful), faithful)

    def test_prune_can_clear_what_the_repository_lint_reports(self) -> None:
        source = "**bold** text here and more words to say"
        spaced = "** fett ** Text hier und mehr Worte zu sagen"

        self.assertNotEqual(tighten(spaced), spaced, "the lint would report this")
        self.assertTrue(harms(source, spaced), "so damaged() must report it too")

    def test_a_repaired_translation_is_not_reported_by_the_widened_predicate(
        self,
    ) -> None:
        source = "All `alpha` criteria."
        restored = _round_trip(source, 'alle  <x id="0"></x>  Kriterien')

        self.assertEqual(restored, "Alle `alpha` Kriterien.")
        self.assertFalse(
            harms(source, restored),
            "the repairs run before harms(), so a written entry must stay clean",
        )

    def test_a_word_free_entry_equal_to_its_source_damaged_nothing(self) -> None:
        word_free = "** ``x`` **"

        self.assertNotEqual(tighten(word_free), word_free, "the source breaks the rule")
        self.assertFalse(
            harms(word_free, word_free),
            "the client answers a word-free entry with its own source, and an "
            "identity mapping cannot have damaged anything",
        )

    def test_a_short_label_may_come_back_unchanged(self) -> None:
        for label in ("RBAC", "n8n", "Cloud", "DNS Resolvers"):
            with self.subTest(label):
                self.assertFalse(harms(label, label))

    def test_a_sentence_that_comes_back_unchanged_is_a_failed_translation(self) -> None:
        sentence = (
            "Centralized database service shared across applications via Docker."
        )

        self.assertTrue(
            harms(sentence, sentence),
            "the server answers with its input when it fails, and the client "
            "seeds every entry with the source, so an echoed sentence would "
            "count as translated and never be retried",
        )

    def test_a_stuttered_word_is_reported(self) -> None:
        self.assertTrue(harms("Cloud", "Cloud Cloud Cloud"))
        self.assertTrue(
            harms("Marketing for teams", "Marketing Marketing Marketing für Teams")
        )

    def test_a_word_the_source_repeats_is_not_a_stutter(self) -> None:
        source = "very very very slow"

        self.assertFalse(harms(source, source.replace("slow", "langsam")))

    def test_a_non_latin_catalog_that_came_back_in_english_is_reported(self) -> None:
        english = "Core NGINX webserver with stream support and tuned defaults"

        self.assertTrue(harms(english, english.replace("tuned", "tunned"), "ar"))
        self.assertFalse(
            harms(english, english.replace("tuned", "tunned"), "de"),
            "a latin-script target needs a language detector, which does not exist here",
        )

    def test_a_non_latin_translation_keeping_a_few_terms_is_not_reported(self) -> None:
        source = "Core NGINX webserver with HTTP stream support and tuned defaults"
        arabic = "خادم NGINX الأساسي مع دعم HTTP وإعدادات افتراضية مضبوطة للأداء"

        self.assertFalse(harms(source, arabic, "ar"))

    def test_every_criterion_of_the_gate_reaches_the_client(self) -> None:
        named = "Deploy web-app-docs before the documentation site answers anything."
        for label, source, translation in (
            ("truncated", self.SOURCE, "Kurz."),
            ("structure", self.SOURCE, f"{self.SOURCE} ["),
            (
                "protected span",
                self.SOURCE,
                self.SOURCE.replace("reverse proxy", "``rp``"),
            ),
            ("missing name", named, "Stelle die Dokumentationsseite bereit."),
        ):
            with self.subTest(label):
                self.assertTrue(harms(source, translation))
                self.assertIsNone(_round_trip(source, translation))


if __name__ == "__main__":
    unittest.main()
