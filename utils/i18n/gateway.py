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

from utils.i18n.libretranslate import (
    DEPLOYED_TIMEOUT_SECONDS,
    deploy,
    deploying,
    environment,
    probe,
    service_url,
    unaccelerated,
)
from utils.i18n.libretranslate import READY_TIMEOUT_SECONDS as READY_TIMEOUT_SECONDS
from utils.i18n.libretranslate import LibreTranslate as LibreTranslate
from utils.i18n.libretranslate import download_status as download_status
from utils.inventory.tools_idle import session, stamp_dir
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
    "svc-ai-nllb-engine",
    "svc-ai-ollama",
    "svc-ai-litellm",
    "svc-ai-s1",
    ROLE,
)


def deployed(root: Path) -> str:
    """Return the URL of the deployed gateway, empty when it cannot serve.

    Args:
        root: repository root.
    """
    return serving(service_url(root))


def serving(url: str) -> str:
    """Return ``url`` when a gateway there names a language, empty otherwise.

    A gateway answering ``/languages`` with an empty catalogue counts as
    absent. It is a router: without a backend that names a language it can
    serve nothing, and treating the bare 200 as ready skips the deploy that
    would give it one, which is how a stale container survives a code change.

    Args:
        url: base URL of a gateway.
    """
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
def server(root: Path, *, redeploy: bool = False, shared: str = "") -> Iterator[str]:
    """Yield the gateway's URL, deploying the whole bundle when it is absent.

    Args:
        root: repository root.
        redeploy: deploy even when a gateway already serves. The reuse check
            asks whether a gateway answers, which cannot see that the bundle
            or the gateway's own code changed since it started, so an
            iteration on either reaches a container that keeps the old one.
        shared: base URL of the shared gateway; empty for this checkout's
            own. It is used as it is and never deployed from here.

    Yields:
        The base URL to translate against, while the run is stamped in the
        machine-wide tools stamp directory.

    Raises:
        RuntimeError: a deploy is already running, and translating would race
            it for the same container stack; or ``shared`` names no language,
            or is combined with ``redeploy``.
    """
    if shared:
        if redeploy:
            raise RuntimeError(
                "redeploy deploys this checkout's own gateway; redeploy the "
                f"shared one at {shared} from the checkout that runs it."
            )
        if not serving(shared):
            raise RuntimeError(f"No gateway at {shared} names a language.")
        with session(stamp_dir(environment(root))):
            yield shared
        return
    if deploying(root):
        raise RuntimeError(
            "A deploy is running; it shares the container stack this translation "
            "would touch. Wait for it to finish and re-run. The running deploy is "
            "left untouched."
        )
    with session(stamp_dir(environment(root))):
        running = "" if redeploy or unaccelerated(root) else deployed(root)
        if not running:
            deploy(root, roles=BUNDLE)
        yield running or service_url(root)
