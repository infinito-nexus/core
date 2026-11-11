"""The settings the role renders into the container environment."""

from __future__ import annotations

import urllib.parse

from assistant.models import Models
from assistant.persona import CONSULTANT, END_USER
from assistant.service import Settings


def dsn(env) -> str:
    """Return the PostgreSQL connection string, each part quoted on its own.

    The parts arrive as separate variables because a password holding ``@`` or
    ``/`` would otherwise be parsed as the host.

    Args:
        env: the process environment.
    """
    user = urllib.parse.quote(env["ASSISTANT_DATABASE_USER"], safe="")
    secret = urllib.parse.quote(env["ASSISTANT_DATABASE_PASSWORD"], safe="")
    host = env["ASSISTANT_DATABASE_HOST"]
    port = env["ASSISTANT_DATABASE_PORT"]
    name = env["ASSISTANT_DATABASE_NAME"]
    return f"postgresql://{user}:{secret}@{host}:{port}/{name}"


def settings(env) -> Settings:
    """Return the answering settings.

    Args:
        env: the process environment.
    """
    return Settings(
        admin_group=env["ASSISTANT_ADMIN_GROUP"],
        threshold=float(env["ASSISTANT_THRESHOLD"]),
        passages=int(env["ASSISTANT_PASSAGES"]),
        max_chars=int(env["ASSISTANT_MAX_CHARS"]),
    )


def chat_models(env) -> dict[str, str]:
    """Return persona name to pinned chat model reference.

    Args:
        env: the process environment.
    """
    return {
        END_USER: env["ASSISTANT_MODEL_END_USER"],
        CONSULTANT: env["ASSISTANT_MODEL_CONSULTANT"],
    }


def models(env) -> Models:
    """Return the gateway client for the pinned persona and embedding models.

    Args:
        env: the process environment.
    """
    return Models(
        env["ASSISTANT_MODEL_URL"],
        env["ASSISTANT_MODEL_KEY"],
        chat_models(env),
        env["ASSISTANT_MODEL_EMBEDDING"],
        float(env["ASSISTANT_MODEL_TIMEOUT"]),
    )
