"""AWS SigV4 signing for path-style S3 requests, standard library only.

The test-e2e-cli runner installs pymysql, psycopg2-binary and ldap3 and
nothing else, so boto3 is unavailable to a role-local probe.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote

_ALGORITHM = "AWS4-HMAC-SHA256"
_SERVICE = "s3"
_UNSIGNED_HEADERS = ("host", "x-amz-content-sha256", "x-amz-date")


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    key = _sign(f"AWS4{secret_key}".encode(), date_stamp)
    key = _sign(key, region)
    key = _sign(key, _SERVICE)
    return _sign(key, "aws4_request")


def canonical_query(query: dict[str, str] | None) -> str:
    """Return the query string in the exact form the signature commits to.

    Callers MUST build the request URL from this, not from ``urlencode``:
    the latter emits ``+`` for a space where SigV4 requires ``%20``, so the
    wire query would no longer match the signed one.

    Args:
        query: Query parameters, unencoded.
    """
    if not query:
        return ""
    return "&".join(
        f"{quote(name, safe='-_.~')}={quote(str(query[name]), safe='-_.~')}"
        for name in sorted(query)
    )


def sign(
    method: str,
    host: str,
    path: str,
    *,
    region: str,
    access_key: str,
    secret_key: str,
    query: dict[str, str] | None = None,
    payload: bytes = b"",
    now: datetime | None = None,
) -> dict[str, str]:
    """Return the headers that authenticate one path-style S3 request.

    Args:
        method: HTTP verb, uppercase.
        host: Host header value, including a non-default port.
        path: Absolute URI path, already percent-encoded where needed.
        region: SigV4 credential-scope region.
        access_key: S3 identity access key.
        secret_key: S3 identity secret key; never returned or logged.
        query: Query parameters to canonicalize, unencoded.
        payload: Exact request body the signature commits to.
        now: Signing timestamp; defaults to the current UTC time.

    Returns:
        A header mapping to merge into the request.
    """
    stamp = now or datetime.now(UTC)
    amz_date = stamp.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = stamp.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()

    canonical_headers = (
        f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
    )
    signed_headers = ";".join(_UNSIGNED_HEADERS)
    canonical_request = "\n".join(
        [
            method,
            path,
            canonical_query(query),
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    scope = f"{date_stamp}/{region}/{_SERVICE}/aws4_request"
    to_sign = "\n".join(
        [
            _ALGORITHM,
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region),
        to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "Host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": (
            f"{_ALGORITHM} Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }
