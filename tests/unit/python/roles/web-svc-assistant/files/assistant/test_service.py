"""The request path end to end with a stub model."""

from __future__ import annotations

import asyncio
import io
import logging
import unittest

from . import load

index = load("index")
logs = load("logs")
persona = load("persona")
ratelimit = load("ratelimit")
service = load("service")

ADMIN_GROUP = "/roles/web-svc-assistant/administrator"
QUESTION = "How do I restore the backup of my calendar zebra-quokka?"
SETTINGS = service.Settings(
    admin_group=ADMIN_GROUP, threshold=0.5, passages=3, max_chars=200
)
ANONYMOUS = {"X-Real-IP": "198.51.100.7"}
ADMINISTRATOR = {
    "X-Real-IP": "198.51.100.9",
    "X-Forwarded-Preferred-Username": "administrator",
    "X-Forwarded-Groups": ADMIN_GROUP,
}


class Clock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now


class StubRetriever:
    def __init__(self, passages) -> None:
        self.passages = passages

    async def search(self, question, limit):
        return list(self.passages)


class StubModel:
    def __init__(self) -> None:
        self.personas: list[str] = []

    def complete(self, persona_name, question, passages):
        self.personas.append(persona_name)
        return "Open the backup page and pick the calendar."


def build(passages=None, limit=2):
    clock = Clock()
    model = StubModel()
    found = (
        passages
        if passages is not None
        else [
            index.Passage(
                "platform",
                "Backup",
                "https://docs.example/backup.md",
                "Restore from the backup page.",
                0.8,
            )
        ]
    )
    assistant = service.Assistant(
        SETTINGS,
        ratelimit.RateLimiter(limit, 60, clock=clock),
        StubRetriever(found),
        model,
        clock=clock,
    )
    return assistant, model, clock


def ask(assistant, headers, question=QUESTION):
    return asyncio.run(assistant.ask(headers, question))


class TestRateLimit(unittest.TestCase):
    def test_anonymous_requests_over_the_limit_get_429_with_retry_after(self) -> None:
        assistant, _, clock = build(limit=2)
        ask(assistant, ANONYMOUS)
        clock.now += 15
        ask(assistant, ANONYMOUS)
        reply = ask(assistant, ANONYMOUS)
        self.assertEqual(reply.status, service.TOO_MANY)
        self.assertEqual(reply.headers, {"Retry-After": "45"})
        self.assertEqual(reply.body, {"error": "rate_limited", "retry_after": 45})

    def test_a_signed_in_user_does_not_spend_the_anonymous_budget(self) -> None:
        assistant, _, _ = build(limit=1)
        replies = [ask(assistant, ADMINISTRATOR) for _ in range(3)]
        self.assertEqual([r.status for r in replies], [service.OK] * 3)


class TestPersonaByGroup(unittest.TestCase):
    def test_the_administrator_group_gets_the_consultant(self) -> None:
        assistant, model, _ = build()
        reply = ask(assistant, ADMINISTRATOR)
        self.assertEqual(reply.body["persona"], persona.CONSULTANT)
        self.assertEqual(model.personas, [persona.CONSULTANT])

    def test_everyone_else_gets_end_user_support(self) -> None:
        assistant, model, _ = build()
        signed_in = {
            **ANONYMOUS,
            "X-Forwarded-Preferred-Username": "biber",
            "X-Forwarded-Groups": "/roles/web-app-gitea/user",
        }
        ask(assistant, ANONYMOUS)
        ask(assistant, signed_in)
        self.assertEqual(model.personas, [persona.END_USER, persona.END_USER])


class TestRefusalOutsideTheIndex(unittest.TestCase):
    def test_nothing_relevant_gets_the_fixed_reply_without_sources(self) -> None:
        assistant, model, _ = build(passages=[])
        reply = ask(assistant, ANONYMOUS)
        self.assertEqual(reply.status, service.OK)
        self.assertFalse(reply.body["answered"])
        self.assertEqual(reply.body["sources"], [])
        self.assertEqual(model.personas, [])

    def test_an_answer_carries_its_source_links(self) -> None:
        assistant, _, _ = build()
        reply = ask(assistant, ANONYMOUS)
        self.assertEqual(
            reply.body["sources"],
            [{"title": "Backup", "url": "https://docs.example/backup.md"}],
        )


class TestRejectedQuestions(unittest.TestCase):
    def test_an_empty_question_is_rejected(self) -> None:
        assistant, _, _ = build()
        self.assertEqual(ask(assistant, ANONYMOUS, "  ").status, service.UNPROCESSABLE)

    def test_an_overlong_question_is_rejected(self) -> None:
        assistant, _, _ = build()
        self.assertEqual(
            ask(assistant, ANONYMOUS, "x" * 201).status, service.UNPROCESSABLE
        )


class TestNoQuestionInTheLogs(unittest.TestCase):
    def setUp(self) -> None:
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(logs.QuestionFreeFormatter())
        self.logger = logging.getLogger("assistant")
        self.logger.addHandler(self.handler)
        self.level = self.logger.level
        self.logger.setLevel(logging.INFO)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self.level)

    def test_answered_refused_and_limited_requests_log_no_question_text(self) -> None:
        assistant, _, _ = build(limit=1)
        ask(assistant, ANONYMOUS)
        ask(assistant, ANONYMOUS)
        ask(assistant, ADMINISTRATOR)
        written = self.stream.getvalue()
        self.assertIn("event=answered", written)
        self.assertIn("event=rate_limited", written)
        self.assertNotIn("zebra-quokka", written)


if __name__ == "__main__":
    unittest.main()
