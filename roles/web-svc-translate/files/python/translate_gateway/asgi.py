"""The deployed gateway: every part built from what the role rendered."""

# nocheck: mirrored-unit-test - the module only reads environment variables into the objects their own tests cover, and it imports fastapi and asyncpg, which exist in the gateway image alone

from __future__ import annotations

import json
import os
import urllib.parse

from infinito_decider import Decider, History, Sampler

from translate_gateway.app import create_app
from translate_gateway.cache import TranslationCache
from translate_gateway.db import Database
from translate_gateway.engines import ChatModelEngine, LibreTranslateEngine
from translate_gateway.failures import FailureLog
from translate_gateway.gateway import Gateway
from translate_gateway.memory import WeblateClient, WeblateGlossary, WeblateMemory
from translate_gateway.router import Router


def _engine(entry, timeout):
    pairs = [tuple(pair) for pair in entry.get("pairs") or []] or None
    if entry.get("kind") == "chat":
        return ChatModelEngine(
            entry["name"],
            entry["url"],
            entry["model"],
            api_key=entry.get("api_key") or None,
            timeout=timeout,
            languages=pairs,
        )
    return LibreTranslateEngine(
        entry["name"],
        entry["url"],
        api_key=entry.get("api_key") or None,
        timeout=timeout,
        languages=pairs,
    )


def _engines(timeout):
    """``{name: engine}`` from the backends the role declared as reachable."""
    declared = json.loads(os.environ.get("TRANSLATE_ENGINES") or "[]")
    return {entry["name"]: _engine(entry, timeout) for entry in declared}


def _dsn():
    """The connection string, assembled so a credential may hold anything.

    The parts arrive as separate variables rather than as one URL because a
    password with a ``@`` or a ``/`` in it would otherwise be parsed as the
    host, which fails as an authentication error and reads as a wrong secret.
    """
    host = os.environ.get("TRANSLATE_DATABASE_HOST") or ""
    if not host:
        return ""
    user = urllib.parse.quote(os.environ.get("TRANSLATE_DATABASE_USER") or "", safe="")
    secret = urllib.parse.quote(
        os.environ.get("TRANSLATE_DATABASE_PASSWORD") or "", safe=""
    )
    port = os.environ.get("TRANSLATE_DATABASE_PORT") or "5432"
    name = os.environ.get("TRANSLATE_DATABASE_NAME") or ""
    return f"postgresql://{user}:{secret}@{host}:{port}/{name}"


def _decider():
    url = os.environ.get("TRANSLATE_S1_URL") or ""
    if not url:
        return None
    return Decider(
        url,
        os.environ.get("TRANSLATE_S1_KEY") or "",
        os.environ.get("TRANSLATE_S1_MODEL") or "",
        int(os.environ.get("TRANSLATE_S1_TIMEOUT") or 20),
        int(os.environ.get("TRANSLATE_S1_MAX_STATE_CHARS") or 4000),
    )


def _weblate():
    """``(memory, glossary)``, both None when Weblate is not deployed."""
    url = os.environ.get("TRANSLATE_WEBLATE_URL") or ""
    token = os.environ.get("TRANSLATE_WEBLATE_TOKEN") or ""
    project = os.environ.get("TRANSLATE_WEBLATE_PROJECT") or ""
    if not (url and token):
        return None, None
    client = WeblateClient(
        url, token, timeout=int(os.environ.get("TRANSLATE_WEBLATE_TIMEOUT") or 10)
    )
    glossary = WeblateGlossary(client, project) if project else None
    return WeblateMemory(client), glossary


def build():
    """The ASGI application this image serves."""
    engines = _engines(int(os.environ.get("TRANSLATE_ENGINE_TIMEOUT") or 30))
    dsn = _dsn()
    database = Database(dsn) if dsn else None
    memory, glossary = _weblate()
    router = Router(
        engines,
        decider=_decider(),
        history=(
            History(database, os.environ["TRANSLATE_HISTORY_TABLE"])
            if database
            else None
        ),
        cache=(
            TranslationCache(database, os.environ["TRANSLATE_CACHE_TABLE"])
            if database
            else None
        ),
        failures=(
            FailureLog(database, os.environ["TRANSLATE_FAILURE_TABLE"])
            if database
            else None
        ),
        sampler=Sampler(
            os.environ.get("TRANSLATE_SAMPLE_TRIGGER") or "requests",
            int(os.environ.get("TRANSLATE_SAMPLE_INTERVAL") or 20),
        ),
        order=[
            name
            for name in (os.environ.get("TRANSLATE_ROUTER_ORDER") or "").split(",")
            if name
        ],
        question=os.environ.get("TRANSLATE_ROUTER_QUESTION") or "translation-verdict",
        saturation=(
            int(os.environ.get("TRANSLATE_SATURATION_MINIMUM") or 10),
            float(os.environ.get("TRANSLATE_SATURATION_SHARE") or 0.8),
        ),
        strategy=os.environ.get("TRANSLATE_ROUTER_STRATEGY") or "preference",
        failure_threshold=int(os.environ.get("TRANSLATE_FAILURE_THRESHOLD") or 3),
        pairs={name: engine.pairs for name, engine in engines.items()},
    )
    return create_app(
        Gateway(router, memory=memory, glossary=glossary),
        engines,
    )


app = build()
