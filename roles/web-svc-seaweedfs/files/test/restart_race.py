from __future__ import annotations

import subprocess
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from s3_engine import Engine

RACE_INTERVAL = 0.2
RACE_SETTLE = 5.0
RACE_REQUEST_TIMEOUT = 2.0
RESTART_TIMEOUT = 300
READY_INTERVAL = 1.0
NO_ANSWER = 0
FOUND = 200
REFUSED = 400
MISSING = 404


def _container(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["container", *args],
        capture_output=True,
        text=True,
        timeout=RESTART_TIMEOUT,
        check=False,
    )


def restart_container(container: str) -> list[str]:
    """
    Args:
        container: the engine's container id or name on this host.

    Returns:
        The failures; empty once the container runs with a new start time.
    """
    started = "{{.State.StartedAt}}"
    before = _container("inspect", "--format", started, container).stdout.strip()
    restarted = _container("restart", container)
    if restarted.returncode != 0:
        return [
            f"F: container restart {container} failed: {restarted.stderr.strip()[:200]}"
        ]
    after = _container("inspect", "--format", started, container).stdout.strip()
    if not after or after == before:
        return [
            f"F: {container} kept its start time {before or '?'}, so it never restarted"
        ]
    return []


def running_container(service: str) -> str:
    """
    Args:
        service: the engine's swarm service.

    Returns:
        The id of the service's running container on this node, or an empty
        string while none runs or the lookup fails.

    Raises:
        RuntimeError: when several containers of the service run here at once.
    """
    try:
        listed = _container(
            "ps",
            "--filter",
            f"label=com.docker.swarm.service.name={service}",
            "--filter",
            "status=running",
            "--format",
            "{{.ID}}",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    running = listed.stdout.split()
    if len(running) > 1:
        raise RuntimeError(
            f"{len(running)} containers of {service} run on this node at once "
            f"({', '.join(running)}): two engines share one data directory"
        )
    return next(iter(running), "")


def restart_service(service: str) -> list[str]:
    """
    Args:
        service: the engine's swarm service, whose task runs on this node.

    Returns:
        The failures; empty once a new container of the service runs here.
    """
    before = running_container(service)
    updated = _container("service", "update", "--force", "--quiet", service)
    if updated.returncode != 0:
        return [
            f"F: container service update --force {service} failed: {updated.stderr.strip()[:200]}"
        ]
    after = running_container(service)
    if not after:
        return [f"F: no container of {service} runs on this node after its update"]
    if after == before:
        return [
            f"F: {service} still runs {before} here, so its task was never replaced"
        ]
    return []


def wait_until_loaded(
    engine: Engine,
    admin: tuple[str, str],
    *,
    timeout: float = RESTART_TIMEOUT,
    interval: float = READY_INTERVAL,
) -> bool:
    """
    Args:
        engine: the S3 gateway.
        admin: the admin identity, which answers 200 only once identities are loaded.
        timeout: seconds to wait.
        interval: seconds between two attempts.

    Returns:
        Whether the admin identity listed the buckets before the timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        status, _, _ = engine.request(
            "GET", "/", access_key=admin[0], secret_key=admin[1]
        )
        if status == 200:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def _anonymous_puts(
    engine: Engine,
    path: str,
    answers: list[int],
    stop: threading.Event,
    interval: float,
) -> None:
    while not stop.is_set():
        status, _, _ = engine.request(
            "PUT", path, payload=b"restart-race", timeout=RACE_REQUEST_TIMEOUT
        )
        answers.append(status)
        stop.wait(interval)


def check_no_write_landed(
    engine: Engine, admin: tuple[str, str], path: str
) -> list[str]:
    """
    Args:
        engine: the S3 gateway.
        admin: the admin identity, which may read every bucket.
        path: the object the anonymous writes targeted.

    Returns:
        The failures: the object exists, or the admin read gave no 404, so a
        landed write cannot be ruled out.
    """
    status, _, _ = engine.request("GET", path, access_key=admin[0], secret_key=admin[1])
    if status == MISSING:
        return []
    if status == FOUND:
        return [f"F: an anonymous write landed during the restart: {path} exists"]
    return [
        f"F: the admin read of {path} answered {status or 'nothing'} instead of "
        f"{MISSING}, so an anonymous write that landed during the restart is not "
        "ruled out"
    ]


def check_restart_serves_no_anonymous_write(
    engine: Engine,
    admin: tuple[str, str],
    bucket: str,
    key: str,
    restart: Callable[[], list[str]],
    *,
    interval: float = RACE_INTERVAL,
    settle: float = RACE_SETTLE,
    timeout: float = RESTART_TIMEOUT,
) -> list[str]:
    """
    Args:
        engine: the S3 gateway.
        admin: the admin identity, used to tell when identities are loaded.
        bucket: a bucket that exists, so a served write would land.
        key: the object key the anonymous writes target.
        restart: restarts the engine and returns its failures.
        interval: seconds between two anonymous writes, each of which gives
            up after RACE_REQUEST_TIMEOUT seconds.
        settle: seconds the writes go on once the admin identity answers.
        timeout: seconds the engine has to load its identities again.

    Returns:
        The failures: a write that was served or landed, a restart that failed
        or was never seen by the writes, and an engine that did not come back.
    """
    path = f"/{bucket}/{key}"
    answers: list[int] = []
    stop = threading.Event()
    writer = threading.Thread(
        target=_anonymous_puts,
        args=(engine, path, answers, stop, interval),
        daemon=True,
    )
    writer.start()
    try:
        failures = restart()
        if not failures:
            if wait_until_loaded(engine, admin, timeout=timeout, interval=interval):
                time.sleep(settle)
            else:
                failures.append(
                    f"F: the engine loaded no identities within {timeout:g}s of its restart"
                )
    finally:
        stop.set()
        writer.join()
    if not failures:
        failures += check_no_write_landed(engine, admin, path)
    served = sorted({status for status in answers if NO_ANSWER < status < REFUSED})
    if served:
        failures.append(
            f"F: an anonymous PutObject to {path} answered {', '.join(map(str, served))} "
            "around the restart; every answer must be a refusal or no answer"
        )
    if NO_ANSWER not in answers:
        failures.append(
            f"F: none of {len(answers)} anonymous PutObject calls to {path} met the "
            "engine down, so the loop never spanned the restart"
        )
    elif all(status == NO_ANSWER for status in answers[answers.index(NO_ANSWER) :]):
        failures.append(
            f"F: no anonymous PutObject to {path} was answered after the engine went "
            "down, so the loop never saw it start again"
        )
    return failures
