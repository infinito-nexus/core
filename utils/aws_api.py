from __future__ import annotations

import hashlib
import hmac
import time
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit

from ansible.module_utils.urls import open_url

ALGORITHM = "AWS4-HMAC-SHA256"
IAM = {"url": "https://iam.amazonaws.com", "region": "us-east-1", "service": "iam"}
IAM_VERSION = "2010-05-08"
ROUTE53 = {
    "url": "https://route53.amazonaws.com",  # nocheck: url  Reason: the Route 53 API endpoint; GET / answers 404, the API paths answer
    "region": "us-east-1",
    "service": "route53",
}
FORM = "application/x-www-form-urlencoded; charset=utf-8"
TIMEOUT = 30


class AwsError(Exception):
    """Args:
    status: the HTTP status of the answer.
    code: the AWS error code, ``HTTP <status>`` when the answer holds none.
    message: the AWS error message.
    """

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{code} (HTTP {status}): {message}")
        self.status = status
        self.code = code


def _encode(value: str) -> str:
    return quote(str(value), safe="-_.~")


def canonical_query(query: dict) -> str:
    """Args:
        query: the query parameters, unencoded.

    Returns:
        The query string the signature commits to, which the request URL
        MUST carry as it is.
    """
    return "&".join(
        f"{name}={value}"
        for name, value in sorted((_encode(k), _encode(v)) for k, v in query.items())
    )


def sign(
    method: str,
    host: str,
    path: str,
    *,
    query: dict,
    headers: dict,
    body: bytes,
    api: dict,
    credentials: dict,
    amz_date: str,
) -> dict:
    """Args:
        method: the HTTP verb, uppercase.
        host: the Host header the request carries.
        path: the absolute URI path, already percent-encoded.
        query: the query parameters, unencoded.
        headers: the headers to sign beside ``host`` and ``x-amz-date``.
        body: the exact request body.
        api: ``region`` and ``service`` of the credential scope.
        credentials: ``access_key_id`` and ``secret_access_key``.
        amz_date: the signing time as ``YYYYMMDDTHHMMSSZ`` in UTC.

    Returns:
        ``headers`` with ``X-Amz-Date`` and ``Authorization`` added; no
        value derived from the secret but the signature.
    """
    signed = {name.lower(): " ".join(str(v).split()) for name, v in headers.items()}
    signed["host"] = host
    signed["x-amz-date"] = amz_date
    names = sorted(signed)
    canonical = "\n".join(
        [
            method,
            path,
            canonical_query(query),
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            hashlib.sha256(body).hexdigest(),
        ]
    )
    day = amz_date[:8]
    scope = f"{day}/{api['region']}/{api['service']}/aws4_request"
    to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )
    key = f"AWS4{credentials['secret_access_key']}".encode()
    for part in (day, api["region"], api["service"], "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        **headers,
        "X-Amz-Date": amz_date,
        "Authorization": (
            f"{ALGORITHM} Credential={credentials['access_key_id']}/{scope}, "
            f"SignedHeaders={';'.join(names)}, Signature={signature}"
        ),
    }


def send(method: str, url: str, headers: dict, body: bytes) -> tuple[int, bytes]:
    """Args:
        method: the HTTP verb.
        url: the full request URL.
        headers: the signed headers.
        body: the request body.

    Returns:
        The HTTP status and the body of the answer, an error answer included.
    """
    try:
        with open_url(
            url,
            data=body or None,
            headers=headers,
            method=method,
            timeout=TIMEOUT,
            follow_redirects="none",
            use_netrc=False,
            http_agent="infinito-nexus",
        ) as answer:
            return answer.getcode(), answer.read()
    except HTTPError as error:
        return error.code, error.read()


def _parsed(payload: bytes):
    try:
        root = ET.fromstring(payload)  # noqa: S314 - answer of the AWS API over verified TLS; expat resolves no external entity
    except ET.ParseError:
        return None
    for element in root.iter():
        element.tag = element.tag.rpartition("}")[2]
    return root


def _call(api, credentials, method, path, query, headers, body):
    host = urlsplit(api["url"]).netloc
    signed = sign(
        method,
        host,
        path,
        query=query,
        headers=headers,
        body=body,
        api=api,
        credentials=credentials,
        amz_date=time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
    )
    suffix = f"?{canonical_query(query)}" if query else ""
    status, payload = send(method, f"https://{host}{path}{suffix}", signed, body)
    root = _parsed(payload)
    if status >= 300 or root is None:
        error = root.find(".//Error") if root is not None else None
        raise AwsError(
            status,
            error.findtext("Code") if error is not None else f"HTTP {status}",
            error.findtext("Message") if error is not None else "no AWS answer",
        )
    return root


def iam(credentials: dict, action: str, params: dict):
    """Args:
        credentials: ``access_key_id`` and ``secret_access_key``.
        action: the IAM Query API action.
        params: its parameters.

    Returns:
        The root of the answer, without XML namespaces.

    Raises:
        AwsError: AWS refused the call.
    """
    body = urlencode({"Action": action, "Version": IAM_VERSION, **params}).encode()
    return _call(IAM, credentials, "POST", "/", {}, {"Content-Type": FORM}, body)


def route53(credentials: dict, path: str, query: dict):
    """Args:
        credentials: ``access_key_id`` and ``secret_access_key``.
        path: the Route 53 API path.
        query: its query parameters, unencoded.

    Returns:
        The root of the answer, without XML namespaces.

    Raises:
        AwsError: AWS refused the call.
    """
    return _call(ROUTE53, credentials, "GET", path, query, {}, b"")
