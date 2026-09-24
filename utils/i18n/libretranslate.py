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
from typing import TYPE_CHECKING, NamedTuple

from utils.cache.yaml import load_yaml
from utils.i18n.languages import SOURCE_LANGUAGE
from utils.i18n.placeholders import has_words, mask, unmask
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

class Outcome(NamedTuple):
    """What one translation call produced, and why anything is missing.

    Args:
        values: one translation per source, None where it was discarded.
        refused: requests the server turned down, retries included.
        damaged: translations that altered a protected span.
        refusal: the last refusal's message, empty when none happened.
    """

    values: list[str | None]
    refused: int
    damaged: int
    refusal: str


def merge(outcomes: Iterable[Outcome]) -> Outcome:
    """Fold per-text outcomes back into one for the whole batch."""
    values: list[str | None] = []
    refused = damaged = 0
    refusal = ""
    for outcome in outcomes:
        values += outcome.values
        refused += outcome.refused
        damaged += outcome.damaged
        refusal = outcome.refusal or refusal
    return Outcome(values, refused, damaged, refusal)


ROLE = "web-svc-libretranslate"
# LibreTranslate names a few targets by script rather than by the bare ISO
# 639-1 code the catalogs use. A code missing from this map simply never turns
# up in /languages, and the readiness wait then spins until its timeout.
SERVER_CODES = {"zh": "zh-Hans"}
SERVICES_FILE = Path("roles") / ROLE / ROLE_FILE_META_SERVICES
CONTAINER_PORT = 5000
MODELS_VOLUME = "infinito-i18n-libretranslate"
MODELS_TARGET = "/home/libretranslate/.local"
CUDA_SUFFIX = "-cuda"
BATCH_SIZE = 20
POLL_SECONDS = 5
READY_TIMEOUT_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 600
DEPLOYED_TIMEOUT_SECONDS = 5
DEPLOY_TIMEOUT_SECONDS = 4 * 3600
RUNNER_TIMEOUT_SECONDS = 300
SERVICE_TIMEOUT_SECONDS = 300
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2
INVENTORY_DIR = Path.home() / "inventories" / "infinito-i18n"
DEPLOY_PID_FILE = Path("build") / "deploy.pid"
GPU_STAMP = Path("build") / "i18n-gpu.stamp"
INVENTORY_VARS = Path("i18n") / "inventory.yml"


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


def deployed(root: Path) -> str:
    """Return the URL of the deployed LibreTranslate, empty when it does not answer.

    Args:
        root: repository root.
    """
    service = load_yaml(root / SERVICES_FILE)["libretranslate"]
    host = environment(root)["INFINITO_BIND_IP"]
    url = f"http://{host}:{service['ports']['local']['http']}"
    try:
        with urllib.request.urlopen(  # noqa: S310 - the URL is this repository's own service definition
            f"{url}/languages", timeout=DEPLOYED_TIMEOUT_SECONDS
        ):
            return url
    except OSError:
        return ""


def await_service(root: Path) -> str:
    """Poll the deployed LibreTranslate until it answers, or give up.

    A service the playbook just created needs longer than one probe's timeout
    to serve its first request, and a single miss would send the caller off to
    spawn a throwaway container beside the one it just deployed.

    Args:
        root: repository root.

    Returns:
        The base URL, empty when nothing answered before the deadline.
    """
    deadline = time.monotonic() + SERVICE_TIMEOUT_SECONDS
    while True:
        running = deployed(root)
        if running or time.monotonic() > deadline:
            return running
        time.sleep(POLL_SECONDS)


def unaccelerated(root: Path) -> bool:
    """Return whether the running LibreTranslate predates this host's GPU.

    A container built before the GPU wiring landed stays healthy and answers
    every request, so the probe alone cannot tell the two apart; the stamp the
    last accelerated deploy left behind can.

    Args:
        root: repository root.
    """
    return accelerated() and not (root / GPU_STAMP).is_file()


def deploying(root: Path) -> bool:
    """Return whether the deploy router still holds the machine.

    Args:
        root: repository root.
    """
    try:
        raw = (
            root / DEPLOY_PID_FILE
        ).read_text()  # nocheck: cache-read - the router rewrites this file per run; the cached reader is an lru_cache without mtime invalidation
        os.kill(int(raw), 0)
    except (OSError, ValueError):
        return False
    return True


def environment(root: Path) -> dict[str, str]:
    """Return the process environment the deploy CLIs expect.

    Args:
        root: repository root.

    Returns:
        ``os.environ`` widened by every assignment ``.env`` makes; an already
        exported value wins, matching what ``scripts/meta/env/load.sh`` does.
    """
    loaded = dict(os.environ)
    dotenv = root / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(
            encoding="utf-8"
        ).splitlines():  # nocheck: cache-read - `make dotenv` regenerates .env mid-session and utils.cache.files.read_text is an lru_cache without mtime invalidation
            if line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            loaded.setdefault(key, value)
    return loaded


def local_image(root: Path, env: dict[str, str]) -> str:
    """Return the image tag the infinito service builds, so the runner reuses it.

    Args:
        root: repository root.
        env: environment the resolver script reads its distro from.
    """
    resolver = root / "scripts" / "meta" / "resolve" / "image" / "local.sh"
    return subprocess.run(
        ["bash", str(resolver)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def await_runner(name: str, env: dict[str, str]) -> None:
    """Block until the i18n runner is up, so no exec falls back to another container.

    Args:
        name: container name of the runner.
        env: environment the docker CLI runs with.

    Raises:
        RuntimeError: the runner never reached the running state.
    """
    deadline = time.monotonic() + RUNNER_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        state = subprocess.run(
            ["docker", "inspect", name, "--format", "{{.State.Running}}"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if state.stdout.strip() == "true":
            return
        time.sleep(POLL_SECONDS)
    raise RuntimeError(f"The i18n runner {name} did not reach the running state.")


def deploy(root: Path) -> str:
    """Deploy web-svc-libretranslate alone into its own inventory and return its URL.

    Args:
        root: repository root.

    Returns:
        The base URL, empty when the service stays unreachable.
    """
    from cli.administration.deploy.development.env import compose_file_args

    inside = [
        "docker",
        "compose",
        *compose_file_args(),
        "exec",
        "-T",
        "-w",
        environment(root)["INFINITO_SRC_DIR"],
        "i18n",
        "python",
        "-m",
    ]
    bootstrap = "scripts/tests/deploy/local/utils/entry-bootstrap.sh"
    steps = [
        [
            "docker",
            "compose",
            *compose_file_args(),
            "--profile",
            "i18n",
            "up",
            "-d",
            "--force-recreate",
            "i18n",
        ],
        [*inside[:-2], "sh", "-lc", "/usr/local/bin/package-frontend-ca.sh"],
        [*inside[:-2], "systemctl", "daemon-reload"],
        [*inside[:-2], "bash", f"{environment(root)['INFINITO_SRC_DIR']}/{bootstrap}"],
        [
            *inside,
            "cli.administration.inventory.provision",
            str(INVENTORY_DIR),
            "--include",
            ROLE,
            "--vars-file",
            f"{environment(root)['INFINITO_SRC_DIR']}/{INVENTORY_VARS}",
        ],
        [
            *inside,
            "cli.administration.deploy.dedicated",
            str(INVENTORY_DIR / "devices.yml"),
            "--id",
            ROLE,
            "--password-file",
            str(INVENTORY_DIR / ".password"),
            "--skip-backup",
            "--skip-cleanup",
        ],
    ]
    loaded = environment(root)
    outer = {
        **loaded,
        "PYTHONUNBUFFERED": "1",
        "INFINITO_IMAGE": loaded.get("INFINITO_IMAGE") or local_image(root, loaded),
    }
    name = f"{loaded['INFINITO_CONTAINER']}_i18n"
    runner = {**outer, "INFINITO_CONTAINER": name}
    for index, step in enumerate(steps):
        subprocess.run(
            step,
            cwd=root,
            check=True,
            timeout=DEPLOY_TIMEOUT_SECONDS,
            env=outer if index == 0 else runner,
        )
        if index == 0:
            await_runner(name, outer)
    running = await_service(root)
    if running and accelerated():
        (root / GPU_STAMP).parent.mkdir(exist_ok=True)
        (root / GPU_STAMP).touch()
    return running


@contextmanager
def server(root: Path, codes: list[str], threads: int) -> Iterator[str]:
    """Yield a LibreTranslate URL, preferring the deployed service over a new container.

    Args:
        root: repository root.
        codes: target languages to load next to the source language.
        threads: translation threads of a container this starts itself.

    Yields:
        The base URL to translate against.

    Raises:
        RuntimeError: a deploy is already running, and translating would race it
            for the same container stack.
    """
    if deploying(root):
        raise RuntimeError(
            "A deploy is running; it shares the container stack this translation "
            "would touch. Wait for it to finish and re-run. The running deploy is "
            "left untouched."
        )
    running = "" if unaccelerated(root) else deployed(root)
    running = running or deploy(root)
    if running:
        yield running
        return
    with container(pinned_image(root), codes, threads) as spawned:
        yield spawned


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
    started = subprocess.run(
        [*command, image], capture_output=True, text=True, check=False
    )
    if started.returncode:
        raise RuntimeError(
            f"docker run exited with {started.returncode}: {started.stderr.strip()}"
        )
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

    @staticmethod
    def server_code(code: str) -> str:
        """Return the target code the server knows this catalog code by."""
        return SERVER_CODES.get(code, code)

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
        wanted = {self.server_code(code) for code in codes}
        missing = set(wanted)
        while True:
            try:
                missing = wanted - self.targets()
                if not missing:
                    return
            except (OSError, ValueError):
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"LibreTranslate at {self.url} does not offer {sorted(missing)}"
                )
            time.sleep(POLL_SECONDS)

    def _post(self, masked: list, target: str) -> list | None:
        """Return the server's translations, or None once the retries run out.

        The server refuses a share of the requests while every lane hammers it
        at once, and those refusals used to discard their entries for good.
        """
        refusals = 0
        refusal = ""
        for attempt in range(RETRY_ATTEMPTS):
            try:
                result = self._call(
                    "/translate",
                    {
                        "q": [item.text for item in masked],
                        "source": SOURCE_LANGUAGE,
                        "target": self.server_code(target),
                        "format": "html",
                    },
                )["translatedText"]
            except (urllib.error.HTTPError, ValueError, KeyError, TypeError) as exc:
                refusals += 1
                refusal = f"{type(exc).__name__}: {exc}"
                result = None
            if isinstance(result, list) and len(result) == len(masked):
                return result, refusals, refusal
            time.sleep(RETRY_BACKOFF_SECONDS * 2**attempt)
        return None, refusals, refusal

    def _batch(self, texts: list[str], target: str) -> Outcome:
        masked = [mask(text) for text in texts]
        result, refused, refusal = self._post(masked, target)
        if result is None:
            if len(texts) == 1:
                return Outcome([None], refused, 0, refusal)
            return merge(self._batch([text], target) for text in texts)
        values = [
            unmask(translated, item, text)
            for translated, item, text in zip(result, masked, texts, strict=True)
        ]
        damaged = sum(1 for text in values if text is None)
        return Outcome(values, refused, damaged, refusal)

    def translate(self, texts: list[str], target: str) -> Outcome:
        """Translate ``texts`` from English into ``target``.

        Args:
            texts: source messages.
            target: ISO 639-1 code.

        Returns:
            One translation per source, ``None`` where it was discarded, plus
            the counts that say which of the two reasons applied. The counts
            belong to this call: lanes share the client, so a field on the
            client would mix another catalog's numbers into this one's.

        Raises:
            OSError: the server is unreachable; every further request would
                fail too, so the run stops instead of discarding the rest.
        """
        results: list[str | None] = list(texts)
        wordy = [index for index, text in enumerate(texts) if has_words(text)]
        batches = [wordy[i : i + BATCH_SIZE] for i in range(0, len(wordy), BATCH_SIZE)]
        refused = damaged = 0
        refusal = ""
        with ThreadPoolExecutor(self.workers) as pool:
            translated = pool.map(
                lambda batch: self._batch([texts[index] for index in batch], target),
                batches,
            )
            for batch, outcome in zip(batches, translated, strict=True):
                for index, text in zip(batch, outcome.values, strict=True):
                    results[index] = text
                refused += outcome.refused
                damaged += outcome.damaged
                refusal = outcome.refusal or refusal
        return Outcome(results, refused, damaged, refusal)
