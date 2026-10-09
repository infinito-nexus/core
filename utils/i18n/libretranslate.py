"""Deploy the dedicated LibreTranslate the translator reaches."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml
from utils.i18n.client import LibreTranslate, Outcome, merge
from utils.inventory.tools import LANE_SERVICE
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["LibreTranslate", "Outcome", "merge", "server"]

ROLE = "svc-ai-libretranslate-engine"
SERVICE_KEY = "libretranslate-engine"
SERVICES_FILE = Path("roles") / ROLE / ROLE_FILE_META_SERVICES
POLL_SECONDS = 5
READY_TIMEOUT_SECONDS = 3600
DEPLOYED_TIMEOUT_SECONDS = 5
DEPLOY_TIMEOUT_SECONDS = 4 * 3600
RUNNER_TIMEOUT_SECONDS = 300
SERVICE_TIMEOUT_SECONDS = READY_TIMEOUT_SECONDS
INVENTORY_DIR = Path.home() / "inventories" / "infinito-tools"
DEPLOY_PID_FILE = Path("build") / "deploy.pid"
DEPLOY_ROUTER = "deploy/main.sh"
GPU_STAMP = Path("build") / "tools-gpu.stamp"
PIVOT_LANGUAGE = "en"


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


def service_url(root: Path) -> str:
    """Return the base URL the dedicated LibreTranslate serves on.

    Args:
        root: repository root.
    """
    service = load_yaml(root / SERVICES_FILE)[SERVICE_KEY]
    host = environment(root)["INFINITO_BIND_IP"]
    return f"http://{host}:{service['ports']['local']['http']}"


def probe(url: str) -> str:
    """Return *url* when it serves the LibreTranslate API, empty when it does not.

    Args:
        url: base URL of an engine or of the gateway in front of several.
    """
    try:
        with urllib.request.urlopen(  # noqa: S310 - the URL is this repository's own service definition
            f"{url}/languages", timeout=DEPLOYED_TIMEOUT_SECONDS
        ):
            return url
    except OSError:
        return ""


def deployed(root: Path) -> str:
    """Return the URL of the deployed LibreTranslate, empty when it does not answer.

    Args:
        root: repository root.
    """
    return probe(service_url(root))


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
    """Block until the tools runner is up, so no exec falls back to another container.

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
    raise RuntimeError(f"The tools runner {name} did not reach the running state.")


def baked_languages(root: Path) -> list[str]:
    """Return every code the lane's image prefetches models for.

    Args:
        root: repository root.
    """
    from utils.i18n.languages import DOMAINS, load_languages, translatable

    languages = load_languages(root)
    codes = {PIVOT_LANGUAGE}
    for domain in DOMAINS:
        codes.update(translatable(languages, domain))
    return sorted(codes)


def _vars_file(root: Path) -> Path:
    """Write the lane's host vars pinning which models the image bakes.

    ``load_only`` reaches the Dockerfile as a build ARG, so a value that
    follows the batch rebuilds the prefetch layer on every run and refetches
    every model in it. Pinning the whole set keeps the ARG constant.

    Args:
        root: repository root.

    Returns:
        The rendered file, beside the template so the container sees it.
    """
    from utils.inventory.tools import render

    return render(root, baked_languages(root))


def deploy(root: Path, roles: tuple[str, ...] = (ROLE,)) -> str:
    """Deploy the named roles into the tools lane's own inventory.

    Args:
        root: repository root.
        roles: the application ids to provision and deploy. Defaults to the
            translation engine, so the i18n targets are unaffected by callers
            that bring up a different tool.

    Returns:
        The translation engine's base URL, empty when it stays unreachable.
    """
    from cli.administration.deploy.development.env import compose_file_args

    loaded = environment(root)
    inside = [
        "docker",
        "compose",
        *compose_file_args(),
        "exec",
        "-T",
        "-w",
        loaded["INFINITO_SRC_DIR"],
        LANE_SERVICE,
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
            LANE_SERVICE,
            "up",
            "-d",
            LANE_SERVICE,
        ],
        [*inside[:-2], "sh", "-lc", "/usr/local/bin/package-frontend-ca.sh"],
        [*inside[:-2], "systemctl", "daemon-reload"],
        [*inside[:-2], "bash", f"{loaded['INFINITO_SRC_DIR']}/{bootstrap}"],
        [
            *inside,
            "cli.administration.inventory.provision",
            str(INVENTORY_DIR),
            "--include",
            *roles,
            "--vars-file",
            f"{loaded['INFINITO_SRC_DIR']}/{_vars_file(root).relative_to(root)}",
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
    outer = {
        **loaded,
        "PYTHONUNBUFFERED": "1",
        "INFINITO_IMAGE": loaded.get("INFINITO_IMAGE") or local_image(root, loaded),
    }
    name = lane_container(loaded)
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
    if accelerated():
        (root / GPU_STAMP).parent.mkdir(exist_ok=True)
        (root / GPU_STAMP).touch()
    return service_url(root)


@contextmanager
def server(root: Path) -> Iterator[str]:
    """Yield the URL of the dedicated LibreTranslate, deploying it when absent.

    Args:
        root: repository root.

    Yields:
        The base URL to translate against. The service answers only once it
        has installed its models, which the caller's readiness wait covers.

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
    yield running or deploy(root)


def lane_container(env: dict[str, str]) -> str:
    """Return the name of the container the tools lane deploys into.

    Args:
        env: the process environment the deploy CLIs expect.
    """
    return f"{env['INFINITO_CONTAINER']}_{LANE_SERVICE}"


def download_status(root: Path) -> str:
    """Return what the dedicated LibreTranslate has pulled so far.

    Its first start installs the argos models, which no cache covers today
    (docs/contributing/environment/cache.md, "App container runtime traffic"),
    so it downloads gigabytes before it answers. The service runs inside the
    lane's own docker, invisible to this daemon, so the figures are the lane
    container's, which carries that traffic.

    Args:
        root: repository root.

    Returns:
        ``lane in <received>, written <written>``, empty when the lane is not
        running or docker does not answer. The figures cover everything the
        lane does, the deploy included, not the model download alone.
    """
    stats = subprocess.run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.NetIO}}|{{.BlockIO}}",
            lane_container(environment(root)),
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if "|" not in stats:
        return ""
    net, block = stats.split("|", 1)
    return (
        f"lane in {net.split('/')[0].strip()}, written {block.split('/')[-1].strip()}"
    )
