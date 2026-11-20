"""Verify the deployed SeaweedFS engine through its S3 gateway.

Every write lands under one reserved key prefix inside a bucket a consumer
already owns. Creating a bucket here would allocate a whole SeaweedFS
collection, and the engine's -volume.max budget is sized for the declared
consumers only, so a probe that creates buckets can exhaust the volume slots
its own consumers write through.

Env (rendered into test.env from templates/test.env.j2):
    SEAWEEDFS_TEST_LOCAL_URL              compose only: S3 gateway on its published host port
    SEAWEEDFS_TEST_LOOPBACK_URL           swarm only: S3 gateway inside the engine's container
    SEAWEEDFS_TEST_SWARM_SERVICE          swarm only: the engine's swarm service
    SEAWEEDFS_TEST_BIND_HOST              host address the console ports must not answer on
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
    SEAWEEDFS_TEST_CONTAINER              the engine's compose container on this host
"""

from __future__ import annotations

import base64
import os
import secrets
import sys
from typing import TYPE_CHECKING

from access_checks import (
    check_admin_roundtrip,
    check_anonymous_cannot_read_private,
    check_anonymous_reads_public,
    check_console_ports_unpublished,
    check_consumer_is_bucket_scoped,
    check_unsigned_is_refused,
)
from restart_race import (
    check_restart_serves_no_anonymous_write,
    restart_container,
    restart_service,
    running_container,
)
from s3_engine import ContainerEngine, Engine

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

KEY_PREFIX = "infinito-engine-check/"


def _b64(name: str) -> str:
    return base64.b64decode(os.environ.get(name, "")).decode("utf-8")


def gateway(env: Mapping[str, str]) -> tuple[Engine, Callable[[], list[str]]]:
    """
    Args:
        env: the rendered test.env.

    Returns:
        The S3 gateway as this deploy mode exposes it, and the restart of the
        engine behind it.
    """
    region = env["SEAWEEDFS_TEST_REGION"]
    service = env.get("SEAWEEDFS_TEST_SWARM_SERVICE", "")
    if service:
        engine = ContainerEngine(
            env["SEAWEEDFS_TEST_LOOPBACK_URL"],
            region,
            lambda: running_container(service),
        )
        return engine, lambda: restart_service(service)
    container = env["SEAWEEDFS_TEST_CONTAINER"]
    engine = Engine(env["SEAWEEDFS_TEST_LOCAL_URL"], region)
    return engine, lambda: restart_container(container)


def main() -> int:
    engine, restart = gateway(os.environ)
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
        os.environ["SEAWEEDFS_TEST_BIND_HOST"],
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
        try:
            failures += check_restart_serves_no_anonymous_write(
                engine,
                admin,
                primary_bucket,
                race_key,
                restart,
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
