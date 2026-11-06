"""The decider is asked one typed choice, and judges answers without their source."""

from __future__ import annotations

import io
import json
import unittest
import unittest.mock
from typing import ClassVar

from . import JUDGE

Decider = JUDGE.Decider


def _answer(payload):
    return io.BytesIO(json.dumps(payload).encode())


class DeciderAskTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.decider = Decider("http://s1:8000", "key", "model", 5, 20)

    def _ask(self, reply, **kwargs):
        with unittest.mock.patch.object(JUDGE.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = _answer(reply)
            result = self.decider.ask(
                kwargs.get("state", "state"),
                "q",
                "instructions",
                kwargs.get("criteria", {"a": "one"}),
            )
        self.sent = json.loads(urlopen.call_args[0][0].data)
        self.request = urlopen.call_args[0][0]
        return result

    def test_it_returns_the_answer_block_for_the_question_it_asked(self) -> None:
        self.assertEqual(
            self._ask({"answers": {"q": {"choice": "a"}}}), {"choice": "a"}
        )

    def test_the_state_is_cut_to_the_configured_length(self) -> None:
        self._ask({"answers": {"q": {"choice": "a"}}}, state="x" * 50)

        self.assertEqual(len(self.sent["state"]), 20)

    def test_it_posts_one_typed_choice_with_the_bearer_token(self) -> None:
        self._ask({"answers": {"q": {"choice": "a"}}})

        self.assertEqual(self.request.get_method(), "POST")
        self.assertEqual(self.request.headers["Authorization"], "Bearer key")
        self.assertEqual(self.sent["questions"]["q"]["type"], "choice")
        self.assertEqual(self.sent["model"], "model")

    def test_an_answer_to_a_different_question_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._ask({"answers": {"other": {"choice": "a"}}})

        self.assertIn("no answer to 'q'", str(caught.exception))

    def test_an_empty_answer_block_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._ask({"answers": {}})


class JudgeAnswersTestCase(unittest.TestCase):
    REPLIES: ClassVar[dict[str, str]] = {
        "alpha": "first reply",
        "beta": "second reply",
    }

    def setUp(self) -> None:
        self.decider = Decider("http://s1:8000", "key", "model", 5, 200)

    def _judge(self, choice):
        with unittest.mock.patch.object(JUDGE.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = _answer(
                {"answers": {"verdict": {"choice": choice}}}
            )
            result = self.decider.judge_answers("text", self.REPLIES, "verdict")
        self.sent = json.loads(urlopen.call_args[0][0].data)
        return result

    def test_the_chosen_label_maps_back_to_its_option(self) -> None:
        self.assertEqual(self._judge("option-0"), "alpha")
        self.assertEqual(self._judge("option-1"), "beta")

    def test_the_decider_never_sees_which_option_produced_which_reply(self) -> None:
        self._judge("option-0")

        criteria = self.sent["questions"]["verdict"]["criteria"]
        self.assertEqual(sorted(criteria), ["option-0", "option-1"])
        self.assertNotIn("alpha", json.dumps(criteria))
        self.assertEqual(criteria["option-0"], "first reply")

    def test_a_label_that_was_not_offered_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._judge("option-9")

        self.assertIn("option-9", str(caught.exception))

    def test_the_labels_follow_the_sorted_options_so_a_rerun_agrees(self) -> None:
        self._judge("option-0")
        first = self.sent["questions"]["verdict"]["criteria"]

        self.decider = Decider("http://s1:8000", "key", "model", 5, 200)
        self._judge("option-0")

        self.assertEqual(first, self.sent["questions"]["verdict"]["criteria"])


if __name__ == "__main__":
    unittest.main()
