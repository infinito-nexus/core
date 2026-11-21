from __future__ import annotations

import socket
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from s3_engine import Engine

CONNECT_TIMEOUT = 10


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


def check_console_ports_unpublished(host: str, ports: dict[str, int]) -> list[str]:
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
