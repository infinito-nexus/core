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
"""

from __future__ import annotations

import base64
import os
import secrets
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

import sigv4

KEY_PREFIX = "infinito-engine-check/"
CONNECT_TIMEOUT = 10
REQUEST_TIMEOUT = 60


def _b64(name: str) -> str:
    return base64.b64decode(os.environ.get(name, "")).decode("utf-8")


class Engine:
    """One S3 gateway reachable over plain HTTP on this host."""

    def __init__(self, base_url: str, region: str) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        self.scheme = parsed.scheme
        self.host = parsed.netloc
        self.region = region

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: bytes = b"",
        access_key: str = "",
        secret_key: str = "",
    ) -> tuple[int, bytes, dict[str, str]]:
        """Perform one request and return its status, body and headers.

        Args:
            method: HTTP verb, uppercase.
            path: Absolute URI path starting with a slash.
            query: Query parameters, unencoded.
            payload: Request body.
            access_key: Identity to sign as; unsigned when empty.
            secret_key: Matching secret; never logged.

        Returns:
            The status code, the body and the response headers. A transport
            failure yields status 0 and the error text as the body.
        """
        url = f"{self.scheme}://{self.host}{path}"
        if query:
            url = f"{url}?{sigv4.canonical_query(query)}"
        headers = {"Host": self.host}
        if access_key:
            headers = sigv4.sign(
                method,
                self.host,
                path,
                region=self.region,
                access_key=access_key,
                secret_key=secret_key,
                query=query,
                payload=payload,
            )
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"refusing a non-HTTP S3 endpoint: {self.scheme}:")
        req = urllib.request.Request(  # noqa: S310 fixed internal http origin from test.env, scheme asserted above
            url, data=payload or None, method=method, headers=headers
        )
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=REQUEST_TIMEOUT) as res:
                return res.status, res.read(), dict(res.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return 0, str(exc).encode("utf-8"), {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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
            elif os.environ.get("SEAWEEDFS_TEST_PRIMARY_IS_PUBLIC", "false") == "true":
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

    if failures:
        for failure in failures:
            print(f"[FAIL] {failure}", file=sys.stderr)
        return 1
    print(
        "[OK]   seaweedfs engine: unsigned refused, admin round-trip, bucket scoping, "
        "anonymous polarity, console ports unpublished"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
