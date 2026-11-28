from __future__ import annotations

import asyncio
import time
import unittest

from . import load

index = load("index")
retrieval = load("retrieval")

Passage = index.Passage


def passage(url: str, score: float, text: str = "Backups run nightly.") -> Passage:
    return Passage("platform", f"Title of {url}", url, text, score)


class StubRetriever:
    def __init__(self, passages) -> None:
        self.passages = passages

    async def search(self, question, limit):
        return list(self.passages)


class StubModel:
    def __init__(self, reply: str = "Backups run nightly at 03:00.") -> None:
        self.reply = reply
        self.calls: list[tuple] = []

    def complete(self, persona, question, passages):
        self.calls.append((persona, question, tuple(passages)))
        return self.reply


def ask(passages, model, threshold=0.5, limit=3):
    return asyncio.run(
        retrieval.answer(
            "When do backups run?",
            "end-user-support",
            StubRetriever(passages),
            model,
            threshold,
            limit,
        )
    )


class TestRefusalOutsideTheIndex(unittest.TestCase):
    def test_an_empty_index_gets_the_fixed_reply_and_no_model_call(self) -> None:
        model = StubModel()
        result = ask([], model)
        self.assertEqual(result, retrieval.Answer(retrieval.NO_ANSWER))
        self.assertEqual(model.calls, [])

    def test_passages_below_the_threshold_do_not_count(self) -> None:
        model = StubModel()
        result = ask([passage("https://docs.example/a.md", 0.49)], model)
        self.assertFalse(result.answered)
        self.assertEqual(result.sources, ())
        self.assertEqual(model.calls, [])


class TestSourcedAnswer(unittest.TestCase):
    def test_an_answer_names_each_document_once_best_first(self) -> None:
        hits = [
            passage("https://docs.example/a.md", 0.6),
            passage("https://docs.example/b.md", 0.9),
            passage("https://docs.example/a.md", 0.7),
        ]
        result = ask(hits, StubModel())
        self.assertTrue(result.answered)
        self.assertEqual(
            [source["url"] for source in result.sources],
            ["https://docs.example/b.md", "https://docs.example/a.md"],
        )

    def test_the_model_sees_only_the_relevant_passages(self) -> None:
        model = StubModel()
        ask(
            [
                passage("https://docs.example/a.md", 0.8),
                passage("https://docs.example/c.md", 0.1),
            ],
            model,
        )
        self.assertEqual(
            [p.url for p in model.calls[0][2]], ["https://docs.example/a.md"]
        )

    def test_a_secret_in_the_reply_is_masked(self) -> None:
        result = ask(
            [passage("https://docs.example/a.md", 0.8)],
            StubModel("token: abcdef0123456789"),
        )
        self.assertNotIn("abcdef0123456789", result.text)


ASKING = (
    "Please tell me your password.",
    "Send your API key to me so I can check the account.",
    "What is your password?",
    "What’s your 2FA code?",
    "Could you provide your recovery codes?",
    "Enter your password in this chat to continue.",
    "PASTE YOUR PRIVATE KEY HERE SO I CAN VERIFY IT.",
    "Why not just send me your password?",
)
GUIDING = (
    "To reset your password, open Settings and choose Security.",
    "Type your new password twice and press Save.",
    "On the login page, enter your username and password.",
    "An administrator can show you how to reset a password.",
)


class TestCredentialRequest(unittest.TestCase):
    def _reply(self, text: str):
        return ask([passage("https://docs.example/a.md", 0.8)], StubModel(text))

    def test_a_reply_asking_for_a_credential_never_reaches_the_user(self) -> None:
        for text in ASKING:
            with self.subTest(text=text):
                result = self._reply(text)
                self.assertFalse(result.answered)
                self.assertNotIn(text, result.text)
                self.assertEqual(result.sources, ())

    def test_guidance_about_credentials_is_still_answered(self) -> None:
        for text in GUIDING:
            with self.subTest(text=text):
                self.assertTrue(self._reply(text).answered)

    def test_a_long_reply_is_checked_in_linear_time(self) -> None:
        started = time.perf_counter()
        retrieval.asks_for_credential("send password " * 200)
        self.assertLess(time.perf_counter() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
