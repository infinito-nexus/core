"""A short-lived LibreTranslate container and a client for its HTTP API."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml
from utils.i18n.languages import SOURCE_LANGUAGE
from utils.i18n.placeholders import has_words, mask, unmask
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterator

SERVICES_FILE = Path("roles") / "web-svc-libretranslate" / ROLE_FILE_META_SERVICES
CONTAINER_PORT = 5000
MODELS_VOLUME = "infinito-i18n-libretranslate"
MODELS_TARGET = "/home/libretranslate/.local"
CUDA_SUFFIX = "-cuda"
BATCH_SIZE = 20
POLL_SECONDS = 5
READY_TIMEOUT_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 600


def pinned_image(root: Path) -> str:
    """Return the image reference web-svc-libretranslate deploys.

    Args:
        root: repository root.
    """
    service = load_yaml(root / SERVICES_FILE)["libretranslate"]
    return f"{service['image']}:{service['version']}"


def accelerated() -> bool:
    """Return whether Docker can hand an NVIDIA GPU to a container."""
    runtimes = subprocess.run(
        ["docker", "info", "--format", "{{json .Runtimes}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "nvidia" in runtimes.stdout


@contextmanager
def container(image: str, codes: list[str], threads: int) -> Iterator[str]:
    """Run LibreTranslate for ``codes`` and remove the container afterwards.

    Args:
        image: image reference to run.
        codes: target languages to load next to the source language.
        threads: translation threads of the server.

    Yields:
        The base URL of the running server.
    """
    name = f"infinito-i18n-libretranslate-{os.getpid()}"
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        name,
        "--publish",
        f"127.0.0.1::{CONTAINER_PORT}",
        "--volume",
        f"{MODELS_VOLUME}:{MODELS_TARGET}",
        "--env",
        f"LT_LOAD_ONLY={','.join([SOURCE_LANGUAGE, *codes])}",
        "--env",
        "LT_UPDATE_MODELS=true",
        "--env",
        f"LT_THREADS={threads}",
    ]
    if accelerated():
        command += ["--gpus", "all"]
        image = f"{image}{CUDA_SUFFIX}"
    subprocess.run([*command, image], check=True, capture_output=True)
    try:
        mapping = subprocess.run(
            ["docker", "port", name, f"{CONTAINER_PORT}/tcp"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()[0]
        yield f"http://{mapping}"
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, check=False
        )


class LibreTranslate:
    """Client for the LibreTranslate HTTP API.

    Args:
        url: base URL of the server.
        workers: parallel translation requests.
    """

    def __init__(self, url: str, workers: int):
        self.url = url.rstrip("/")
        self.workers = workers

    def _call(self, path: str, payload: dict | None = None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - the URL is the LibreTranslate container this process started
            f"{self.url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(  # noqa: S310 - the URL is the LibreTranslate container this process started
            request, timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            return json.load(response)

    def targets(self) -> set[str]:
        """Return the languages the server translates English into."""
        for language in self._call("/languages"):
            if language["code"] == SOURCE_LANGUAGE:
                return set(language["targets"])
        return set()

    def wait(self, codes: list[str], timeout: float) -> None:
        """Block until the server translates into every language of ``codes``.

        Args:
            codes: required target languages.
            timeout: seconds to wait before giving up.
        """
        deadline = time.monotonic() + timeout
        missing = set(codes)
        while True:
            try:
                missing = set(codes) - self.targets()
                if not missing:
                    return
            except (OSError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"LibreTranslate at {self.url} does not offer {sorted(missing)}"
                )
            time.sleep(POLL_SECONDS)

    def _batch(self, texts: list[str], target: str) -> list[str | None]:
        masked = [mask(text) for text in texts]
        try:
            result = self._call(
                "/translate",
                {
                    "q": [item.text for item in masked],
                    "source": SOURCE_LANGUAGE,
                    "target": target,
                    "format": "html",
                },
            )["translatedText"]
        except (urllib.error.HTTPError, ValueError, KeyError, TypeError):
            result = None
        if not isinstance(result, list) or len(result) != len(texts):
            if len(texts) == 1:
                return [None]
            return [self._batch([text], target)[0] for text in texts]
        return [
            unmask(translated, item, text)
            for translated, item, text in zip(result, masked, texts, strict=True)
        ]

    def translate(self, texts: list[str], target: str) -> list[str | None]:
        """Translate ``texts`` from English into ``target``.

        Args:
            texts: source messages.
            target: ISO 639-1 code.

        Returns:
            One translation per source; ``None`` where the server rejected the
            request or the translation damaged a protected span.

        Raises:
            OSError: the server is unreachable; every further request would
                fail too, so the run stops instead of discarding the rest.
        """
        results: list[str | None] = list(texts)
        wordy = [index for index, text in enumerate(texts) if has_words(text)]
        batches = [wordy[i : i + BATCH_SIZE] for i in range(0, len(wordy), BATCH_SIZE)]
        with ThreadPoolExecutor(self.workers) as pool:
            translated = pool.map(
                lambda batch: self._batch([texts[index] for index in batch], target),
                batches,
            )
            for batch, texts_out in zip(batches, translated, strict=True):
                for index, text in zip(batch, texts_out, strict=True):
                    results[index] = text
        return results
