"""Service logs that cannot carry a question or an answer.

The formatter renders a fixed event name and a fixed set of fields and drops
everything else: the message arguments, unknown event texts and exception
messages, any of which could quote what a user asked.
"""

from __future__ import annotations

import logging

EVENTS = frozenset(
    {
        "answered",
        "index_built",
        "model_failed",
        "no_answer",
        "rate_limited",
        "rejected",
    }
)
FIELDS = ("persona", "status", "sources", "passages", "retry_after", "duration_ms")
UNLISTED = "unlisted"
SERVER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class QuestionFreeFormatter(logging.Formatter):
    """Render ``<time> <level> <logger> event=<name> <field>=<value> ...``."""

    def format(self, record: logging.LogRecord) -> str:
        event = (
            record.msg
            if isinstance(record.msg, str) and record.msg in EVENTS
            else UNLISTED
        )
        parts = [
            self.formatTime(record),
            record.levelname,
            record.name,
            f"event={event}",
        ]
        parts.extend(
            f"{name}={getattr(record, name)}"
            for name in FIELDS
            if hasattr(record, name)
        )
        if record.exc_info and record.exc_info[0] is not None:
            parts.append(f"error={record.exc_info[0].__name__}")
        return " ".join(parts)


def configure(level: str = "INFO") -> None:
    """Route every logger of the process through :class:`QuestionFreeFormatter`.

    uvicorn installs its own handlers before it imports the application, so
    they are dropped here and its records reach the root handler instead.

    Args:
        level: the lowest level written.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(QuestionFreeFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in SERVER_LOGGERS:
        server = logging.getLogger(name)
        server.handlers[:] = []
        server.propagate = True
