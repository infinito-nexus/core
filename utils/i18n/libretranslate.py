"""Deploy a LibreTranslate the translator can reach, or run a throwaway one."""

from __future__ import annotations

import os
import secrets
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml
from utils.i18n.client import LibreTranslate, Outcome, merge
from utils.i18n.languages import SOURCE_LANGUAGE
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["LibreTranslate", "Outcome", "merge", "server"]

ROLE = "web-svc-libretranslate"
SERVICES_FILE = Path("roles") / ROLE / ROLE_FILE_META_SERVICES
CONTAINER_PORT = 5000
MODELS_VOLUME = "infinito-i18n-libretranslate"
MODELS_TARGET = "/home/libretranslate/.local"
CUDA_SUFFIX = "-cuda"
POLL_SECONDS = 5
READY_TIMEOUT_SECONDS = 3600
DEPLOYED_TIMEOUT_SECONDS = 5
DEPLOY_TIMEOUT_SECONDS = 4 * 3600
RUNNER_TIMEOUT_SECONDS = 300
SERVICE_TIMEOUT_SECONDS = 300
INVENTORY_DIR = Path.home() / "inventories" / "infinito-i18n"
DEPLOY_PID_FILE = Path("build") / "deploy.pid"
DEPLOY_ROUTER = "deploy/main.sh"
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
    """Return whether Docker can hand an NVIDIA GPU to a container.

    ``INFINITO_GPU_COUNT`` is the single point of truth the deploys read, so an
    operator who sets it to 0 turns the GPU off here too. It is only derived
    from the daemon where the variable is absent.
    """
    reserved = (os.environ.get("INFINITO_GPU_COUNT") or "").strip()
    if reserved:
        return reserved not in ("0", "none")
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

    A live pid is not proof on its own: the router records the pid it has in
    its own namespace, and every sandboxed command gets a fresh one where the
    low numbers belong to that sandbox's own shell and children. A stale file
    then names a process that exists and is not a deploy, which blocked every
    translation run until the file was deleted by hand. The recorded process
    has to name the router in its command line to count.

    Args:
        root: repository root.
    """
    try:
        raw = (
            root / DEPLOY_PID_FILE
        ).read_text()  # nocheck: cache-read - the router rewrites this file per run; the cached reader is an lru_cache without mtime invalidation
        pid = int(raw)
        os.kill(pid, 0)
        command = Path(
            f"/proc/{pid}/cmdline"
        ).read_bytes()  # nocheck: cache-read - /proc is per-pid and vanishes with the process; a cached cmdline would answer for whatever holds that pid next
    except (OSError, ValueError):
        return False
    return DEPLOY_ROUTER.encode() in command


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
    name = f"infinito-i18n-libretranslate-{secrets.token_hex(4)}"
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
