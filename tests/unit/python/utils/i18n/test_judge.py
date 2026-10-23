"""The chat judge places a translation on a named level, or refuses to answer."""

from __future__ import annotations

import io
import json
import unittest
import unittest.mock

from utils.i18n import judge
from utils.i18n.judge import LEVELS, MIDDLE, ChatJudge, parse_level, question


def _answer(content):
    payload = {"choices": [{"message": {"content": content}}]}
    return io.BytesIO(json.dumps(payload).encode())


class QuestionTestCase(unittest.TestCase):
    def test_both_texts_reach_the_model(self) -> None:
        asked = question("The backup runs at two.", "Das Backup läuft um zwei.")

        self.assertIn("The backup runs at two.", asked)
        self.assertIn("Das Backup läuft um zwei.", asked)

    def test_every_level_is_offered_under_its_index(self) -> None:
        asked = question("a", "b")

        for index, level in enumerate(LEVELS):
            with self.subTest(level=index):
                self.assertIn(f"{index} {level}", asked)

    def test_the_middle_level_is_the_one_the_suite_compares_against(self) -> None:
        self.assertEqual(LEVELS[MIDDLE], LEVELS[1])


class ParseLevelTestCase(unittest.TestCase):
    def test_a_bare_digit_is_the_level(self) -> None:
        self.assertEqual(parse_level("2"), 2)

    def test_a_digit_inside_a_sentence_still_counts(self) -> None:
        self.assertEqual(parse_level("Level 1, it distorts a detail."), 1)

    def test_an_answer_without_a_digit_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_level("I cannot judge this pair.")

    def test_an_empty_answer_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_level("")

    def test_a_level_outside_the_scale_is_refused(self) -> None:
        """Clamping would put a score on a non-answer: a model replying 7 has
        not placed the pair on this scale at all."""
        with self.assertRaises(ValueError):
            parse_level("7")


class ScoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.judge = ChatJudge("http://gateway:4000/", "chat", api_key="k")

    def _call(self, content):
        with unittest.mock.patch.object(judge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = _answer(content)
            result = self.judge.score("source", "translation")
        self.request = urlopen.call_args[0][0]
        self.sent = json.loads(self.request.data)
        return result

    def test_it_returns_the_level_the_model_named(self) -> None:
        self.assertEqual(self._call("0"), 0)

    def test_the_trailing_slash_of_the_base_url_is_not_doubled(self) -> None:
        self._call("2")

        self.assertEqual(self.request.full_url, "http://gateway:4000/chat/completions")

    def test_the_key_travels_as_a_bearer_token(self) -> None:
        self._call("2")

        self.assertEqual(self.request.get_header("Authorization"), "Bearer k")

    def test_the_judge_is_asked_without_sampling(self) -> None:
        self._call("2")

        self.assertEqual(self.sent["temperature"], 0)

    def test_an_empty_completion_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._call("   ")


if __name__ == "__main__":
    unittest.main()
