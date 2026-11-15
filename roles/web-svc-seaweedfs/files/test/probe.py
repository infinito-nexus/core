"""Verify the deployed SeaweedFS engine through its published S3 port.

Every write lands under one reserved key prefix inside a bucket a consumer
already owns. Creating a bucket here would allocate a whole SeaweedFS
collection, and the engine's -volume.max budget is sized for the declared
consumers only, so a probe that creates buckets can exhaust the volume slots
its own consumers write through.

Env (rendered into test.env from templates/test.env.j2):
    SEAWEEDFS_TEST_LOCAL_URL              S3 gateway on this host
    SEAWEEDFS_TEST_REGION                 SigV4 credential-scope region
    SEAWEEDFS_TEST_FILER_PORT             filer port, expected unpublished
    SEAWEEDFS_TEST_MASTER_PORT            master port, expected unpublished
    SEAWEEDFS_TEST_ADMIN_ACCESS_KEY_B64   base64 admin access key
    SEAWEEDFS_TEST_ADMIN_SECRET_KEY_B64   base64 admin secret key
    SEAWEEDFS_TEST_PRIMARY_BUCKET         a non-public consumer's bucket
    SEAWEEDFS_TEST_PRIMARY_ACCESS_KEY_B64 base64 that consumer's access key
    SEAWEEDFS_TEST_PRIMARY_SECRET_KEY_B64 base64 that consumer's secret key
    SEAWEEDFS_TEST_OTHER_BUCKET           a second consumer's bucket, or empty
    SEAWEEDFS_TEST_PUBLIC_BUCKET          a public consumer's bucket, or empty
    SEAWEEDFS_TEST_PUBLIC_ACCESS_KEY_B64  base64 that consumer's access key
    SEAWEEDFS_TEST_PUBLIC_SECRET_KEY_B64  base64 that consumer's secret key
    SEAWEEDFS_TEST_CONTAINER              the engine's container on this host
"""

from __future__ import annotations

import base64
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

from s3_engine import Engine

if TYPE_CHECKING:
    from collections.abc import Callable

KEY_PREFIX = "infinito-engine-check/"
CONNECT_TIMEOUT = 10
RACE_INTERVAL = 0.2
RACE_SETTLE = 5.0
RESTART_TIMEOUT = 300
READY_INTERVAL = 1.0
NO_ANSWER = 0
REFUSED = 400


def _b64(name: str) -> str:
    return base64.b64decode(os.environ.get(name, "")).decode("utf-8")


def check_unsigned_is_refused(engine: Engine) -> list[str]:
    status, body, headers = engine.request("GET", "/")
    if status == 0:
        return [
            f"A: S3 gateway unreachable at {engine.host}: {body.decode(errors='replace')[:200]}"
        ]
    if status in (301, 302, 303, 307, 308):
        return [
            (
                f"A: unsigned GET / redirected ({status}) to {headers.get('Location', '?')} — "
                "the S3 vhost must not be SSO-gated"
            )
        ]
    if status == 200:
        return [
            "A: unsigned GET / answered 200 — anonymous is over-granted at the service root"
        ]
    if status != 403:
        return [f"A: unsigned GET / answered {status}, expected 403"]
    if b"<Error" not in body:
        return [
            f"A: unsigned GET / answered 403 without an S3 <Error> body: {body[:200]!r}"
        ]
    return []


def check_admin_roundtrip(
    engine: Engine, admin: tuple[str, str], bucket: str, key: str, blob: bytes
) -> list[str]:
    ak, sk = admin
    status, body, _ = engine.request(
        "PUT", f"/{bucket}/{key}", payload=blob, access_key=ak, secret_key=sk
    )
    if status not in (200, 204):
        return [f"B: admin could not write {bucket}/{key}: {status} {body[:200]!r}"]

    status, body, _ = engine.request(
        "GET", f"/{bucket}/{key}", access_key=ak, secret_key=sk
    )
    if status != 200:
        return [f"B: admin could not read back {bucket}/{key}: {status}"]
    if body != blob:
        return [f"B: {bucket}/{key} read back {len(body)} bytes, wrote {len(blob)}"]
    return []


def check_consumer_is_bucket_scoped(
    engine: Engine,
    primary: tuple[str, str],
    bucket: str,
    other_bucket: str,
) -> list[str]:
    ak, sk = primary
    failures = []

    status, body, _ = engine.request(
        "GET",
        f"/{bucket}",
        query={"list-type": "2", "max-keys": "1"},
        access_key=ak,
        secret_key=sk,
    )
    if status != 200:
        failures.append(
            f"C: consumer identity cannot list its own bucket {bucket}: {status} {body[:200]!r}"
        )

    if not other_bucket:
        print(
            "SKIP: only one object-store consumer on this host; cross-tenant denial unverified"
        )
        return failures

    status, _, _ = engine.request(
        "GET",
        f"/{other_bucket}",
        query={"list-type": "2", "max-keys": "1"},
        access_key=ak,
        secret_key=sk,
    )
    if status != 403:
        failures.append(
            f"C: the '{bucket}' identity listed the '{other_bucket}' bucket with {status}, "
            "expected 403 — the identity is not bucket-scoped"
        )
    return failures


def check_anonymous_cannot_read_private(
    engine: Engine, bucket: str, key: str
) -> list[str]:
    status, _, _ = engine.request("GET", f"/{bucket}/{key}")
    if status == 404:
        return [
            f"D1: {bucket}/{key} answered 404 unsigned although the signed read succeeded"
        ]
    if status != 403:
        return [f"D1: unsigned read of {bucket}/{key} answered {status}, expected 403"]
    return []


def check_anonymous_reads_public(
    engine: Engine, public: tuple[str, str], bucket: str, key: str, blob: bytes
) -> list[str]:
    ak, sk = public
    status, body, _ = engine.request(
        "PUT", f"/{bucket}/{key}", payload=blob, access_key=ak, secret_key=sk
    )
    if status not in (200, 204):
        return [f"D2: consumer could not write {bucket}/{key}: {status} {body[:200]!r}"]

    status, body, _ = engine.request("GET", f"/{bucket}/{key}")
    if status != 200:
        return [
            (
                f"D2: unsigned read of public {bucket}/{key} answered {status}, expected 200 — "
                "the anonymous Read grant is missing"
            )
        ]
    if body != blob:
        return [
            f"D2: public {bucket}/{key} read back {len(body)} bytes, wrote {len(blob)}"
        ]
    return []


def check_console_ports_unpublished(engine: Engine, ports: dict[str, int]) -> list[str]:
    host = engine.host.rsplit(":", 1)[0]
    failures = []
    for name, port in ports.items():
        try:
            with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT):
                failures.append(
                    f"E: {name} port {port} accepts connections on {host} — the engine must not "
                    "publish it, the console proxies it over the shared network"
                )
        except OSError:
            continue
    return failures


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
        status, _, _ = engine.request("PUT", path, payload=b"restart-race")
        answers.append(status)
        stop.wait(interval)


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
        interval: seconds between two anonymous writes.
        settle: seconds the writes go on once the admin identity answers.
        timeout: seconds the engine has to load its identities again.

    Returns:
        The failures: a write that was served, a restart that failed or was
        never seen by the writes, and an engine that did not come back.
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


def main() -> int:
    engine = Engine(
        os.environ["SEAWEEDFS_TEST_LOCAL_URL"], os.environ["SEAWEEDFS_TEST_REGION"]
    )
    admin = (
        _b64("SEAWEEDFS_TEST_ADMIN_ACCESS_KEY_B64"),
        _b64("SEAWEEDFS_TEST_ADMIN_SECRET_KEY_B64"),
    )
    primary = (
        _b64("SEAWEEDFS_TEST_PRIMARY_ACCESS_KEY_B64"),
        _b64("SEAWEEDFS_TEST_PRIMARY_SECRET_KEY_B64"),
    )
    public = (
        _b64("SEAWEEDFS_TEST_PUBLIC_ACCESS_KEY_B64"),
        _b64("SEAWEEDFS_TEST_PUBLIC_SECRET_KEY_B64"),
    )
    primary_bucket = os.environ.get("SEAWEEDFS_TEST_PRIMARY_BUCKET", "")
    other_bucket = os.environ.get("SEAWEEDFS_TEST_OTHER_BUCKET", "")
    public_bucket = os.environ.get("SEAWEEDFS_TEST_PUBLIC_BUCKET", "")

    run_id = secrets.token_hex(8)
    probe_key = f"{KEY_PREFIX}{run_id}"
    blob = secrets.token_bytes(64)

    failures: list[str] = check_unsigned_is_refused(engine)

    if not primary_bucket:
        print(
            "SKIP: no private object-store consumer on this host; only the service root was probed"
        )
    else:
        try:
            roundtrip = check_admin_roundtrip(
                engine, admin, primary_bucket, probe_key, blob
            )
            failures += roundtrip
            if roundtrip:
                pass
            elif os.environ["SEAWEEDFS_TEST_PRIMARY_IS_PUBLIC"] == "true":
                print(
                    "SKIP: every consumer on this host is public; the private-read denial has no bucket to run in"
                )
            else:
                failures += check_anonymous_cannot_read_private(
                    engine, primary_bucket, probe_key
                )
            failures += check_consumer_is_bucket_scoped(
                engine, primary, primary_bucket, other_bucket
            )
        finally:
            engine.request(
                "DELETE",
                f"/{primary_bucket}/{probe_key}",
                access_key=admin[0],
                secret_key=admin[1],
            )

    if not public_bucket:
        print(
            "SKIP: no public object-store consumer on this host; anonymous read unverified"
        )
    else:
        try:
            failures += check_anonymous_reads_public(
                engine, public, public_bucket, probe_key, blob
            )
        finally:
            engine.request(
                "DELETE",
                f"/{public_bucket}/{probe_key}",
                access_key=public[0],
                secret_key=public[1],
            )

    failures += check_console_ports_unpublished(
        engine,
        {
            "filer": int(os.environ["SEAWEEDFS_TEST_FILER_PORT"]),
            "master": int(os.environ["SEAWEEDFS_TEST_MASTER_PORT"]),
        },
    )

    if not primary_bucket:
        print(
            "SKIP: no object-store consumer on this host; the restart race has no bucket to write into"
        )
    else:
        race_key = f"{probe_key}-restart-race"
        container = os.environ["SEAWEEDFS_TEST_CONTAINER"]
        try:
            failures += check_restart_serves_no_anonymous_write(
                engine,
                admin,
                primary_bucket,
                race_key,
                lambda: restart_container(container),
            )
        finally:
            engine.request(
                "DELETE",
                f"/{primary_bucket}/{race_key}",
                access_key=admin[0],
                secret_key=admin[1],
            )

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}", file=sys.stderr)
        return 1
    print(
        "[OK]   seaweedfs engine: unsigned refused, admin round-trip, bucket scoping, "
        "anonymous polarity, console ports unpublished, no anonymous write served "
        "across a restart"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
