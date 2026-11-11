"""The deployed assistant: every part built from what the role rendered."""

# nocheck: mirrored-unit-test - the module only wires environment variables into objects their own tests cover, and it imports fastapi and asyncpg, which exist in the assistant image alone

from __future__ import annotations

import os

from assistant import logs
from assistant.app import create_app
from assistant.environment import dsn, models, settings
from assistant.ratelimit import RateLimiter
from assistant.service import Assistant, Retriever
from assistant.store import Store


def build():
    """The ASGI application this image serves."""
    logs.configure()
    env = os.environ
    gateway = models(env)
    assistant = Assistant(
        settings(env),
        RateLimiter(
            int(env["ASSISTANT_RATE_LIMIT_REQUESTS"]),
            float(env["ASSISTANT_RATE_LIMIT_WINDOW"]),
        ),
        Retriever(gateway, Store(dsn(env), env["ASSISTANT_INDEX_TABLE"])),
        gateway,
    )
    return create_app(assistant, env["ASSISTANT_PATH"])


app = build()
