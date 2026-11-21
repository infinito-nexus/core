from __future__ import annotations

import logging
import unittest

from . import load

logs = load("logs")

QUESTION = "what is the password of zebra-quokka"


def record(msg, args=(), exc_info=None, **fields) -> logging.LogRecord:
    entry = logging.LogRecord(
        "assistant", logging.INFO, __file__, 1, msg, args, exc_info
    )
    for name, value in fields.items():
        setattr(entry, name, value)
    return entry


class TestQuestionFreeFormatter(unittest.TestCase):
    def setUp(self) -> None:
        self.formatter = logs.QuestionFreeFormatter()

    def test_a_listed_event_keeps_its_fields(self) -> None:
        line = self.formatter.format(
            record("answered", persona="end-user-support", status=200)
        )
        self.assertIn("event=answered persona=end-user-support status=200", line)

    def test_message_arguments_are_dropped(self) -> None:
        line = self.formatter.format(record("answered %s", (QUESTION,)))
        self.assertNotIn("zebra-quokka", line)
        self.assertIn("event=unlisted", line)

    def test_a_message_quoting_the_question_is_unlisted(self) -> None:
        line = self.formatter.format(record(f"question: {QUESTION}"))
        self.assertNotIn("zebra-quokka", line)

    def test_unknown_fields_are_dropped(self) -> None:
        line = self.formatter.format(record("answered", question=QUESTION))
        self.assertNotIn("zebra-quokka", line)

    def test_an_exception_keeps_its_type_and_loses_its_message(self) -> None:
        error = ValueError(QUESTION)
        line = self.formatter.format(
            record("model_failed", exc_info=(ValueError, error, None))
        )
        self.assertIn("error=ValueError", line)
        self.assertNotIn("zebra-quokka", line)


class TestConfigure(unittest.TestCase):
    def test_the_server_loggers_reach_the_root_formatter(self) -> None:
        root = logging.getLogger()
        saved = (root.handlers[:], root.level)
        try:
            logs.configure()
            self.assertIsInstance(
                root.handlers[0].formatter, logs.QuestionFreeFormatter
            )
            self.assertTrue(
                all(logging.getLogger(name).propagate for name in logs.SERVER_LOGGERS)
            )
            self.assertEqual(logging.getLogger("uvicorn.access").handlers, [])
        finally:
            root.handlers[:], level = saved
            root.setLevel(level)


if __name__ == "__main__":
    unittest.main()
