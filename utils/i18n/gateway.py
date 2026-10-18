"""Deploy the translation gateway the catalog translator reaches.

The gateway speaks the LibreTranslate API, so the client this module hands a
URL to is the same one that used to talk to the engine. What changes is what
answers: several engines instead of one, System One picking between them per
language pair, and a learning log that carries the verdict into the next run.
"""

from __future__ import annotations

import json
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml
from utils.i18n.libretranslate import (
    DEPLOYED_TIMEOUT_SECONDS,
    deploy,
    deploying,
    environment,
    probe,
    unaccelerated,
)
from utils.i18n.libretranslate import READY_TIMEOUT_SECONDS as READY_TIMEOUT_SECONDS
from utils.i18n.libretranslate import LibreTranslate as LibreTranslate
from utils.i18n.libretranslate import download_status as download_status
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterator

ROLE = "web-svc-translate"
SERVICE_KEY = "translate"
SERVICES_FILE = Path("roles") / ROLE / ROLE_FILE_META_SERVICES
ENGINE_ROLE = "svc-ai-libretranslate-engine"
BUNDLE = (
    ENGINE_ROLE,
    "svc-ai-ltengine",
    "svc-ai-ollama",
    "svc-ai-litellm",
    "svc-ai-s1",
    ROLE,
)


def service_url(root: Path) -> str:
    """Return the base URL the gateway serves on.

    Args:
        root: repository root.
    """
    service = load_yaml(root / SERVICES_FILE)[SERVICE_KEY]
    host = environment(root)["INFINITO_BIND_IP"]
    return f"http://{host}:{service['ports']['local']['http']}"


def deployed(root: Path) -> str:
    """Return the URL of the deployed gateway, empty when it cannot serve.

    A gateway answering ``/languages`` with an empty catalogue counts as
    absent. It is a router: without a backend that names a language it can
    serve nothing, and treating the bare 200 as ready skips the deploy that
    would give it one, which is how a stale container survives a code change.

    Args:
        root: repository root.
    """
    url = service_url(root)
    if not probe(url):
        return ""
    try:
        with urllib.request.urlopen(  # noqa: S310 - the URL is this repository's own service definition
            f"{url}/languages", timeout=DEPLOYED_TIMEOUT_SECONDS
        ) as answer:
            return url if json.loads(answer.read()) else ""
    except (OSError, ValueError):
        return ""


@contextmanager
def server(root: Path, *, redeploy: bool = False) -> Iterator[str]:
    """Yield the gateway's URL, deploying the whole bundle when it is absent.

    Args:
        root: repository root.
        redeploy: deploy even when a gateway already serves. The reuse check
            asks whether a gateway answers, which cannot see that the bundle
            or the gateway's own code changed since it started, so an
            iteration on either reaches a container that keeps the old one.

    Yields:
        The base URL to translate against.

    Raises:
        RuntimeError: a deploy is already running, and translating would race
            it for the same container stack.
    """
    if deploying(root):
        raise RuntimeError(
            "A deploy is running; it shares the container stack this translation "
            "would touch. Wait for it to finish and re-run. The running deploy is "
            "left untouched."
        )
    running = "" if redeploy or unaccelerated(root) else deployed(root)
    if not running:
        deploy(root, roles=BUNDLE)
    yield running or service_url(root)
