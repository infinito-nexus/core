from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

import sigv4

if TYPE_CHECKING:
    from collections.abc import Callable

REQUEST_TIMEOUT = 60
EXEC_GRACE = 30
AUTHORIZATION_VARIABLE = "SEAWEEDFS_TEST_AUTHORIZATION"


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
        return self._send(method, url, headers, payload)

    def _send(
        self, method: str, url: str, headers: dict[str, str], payload: bytes
    ) -> tuple[int, bytes, dict[str, str]]:
        req = urllib.request.Request(  # noqa: S310 fixed internal http origin from test.env, scheme asserted in request()
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


class ContainerEngine(Engine):
    def __init__(self, base_url: str, region: str, resolve: Callable[[], str]) -> None:
        """
        Args:
            base_url: the gateway as the container itself reaches it.
            region: SigV4 credential-scope region.
            resolve: returns the engine's running container on this node, or
                an empty string while none runs; called again only after an
                exec into the last one failed.
        """
        super().__init__(base_url, region)
        self.resolve = resolve
        self.cid = ""

    def _send(
        self, method: str, url: str, headers: dict[str, str], payload: bytes
    ) -> tuple[int, bytes, dict[str, str]]:
        exec_argv = ["container", "exec", "-i"]
        curl = ["curl", "-sS", "-i", "--max-time", str(REQUEST_TIMEOUT)]
        curl += ["-X", method, "-H", "Expect:"]
        env = None
        for name, value in headers.items():
            if name != "Authorization":
                curl += ["-H", f"{name}: {value}"]
        if "Authorization" in headers:
            env = {**os.environ, AUTHORIZATION_VARIABLE: headers["Authorization"]}
            exec_argv += ["-e", AUTHORIZATION_VARIABLE]
            curl += [
                "--variable",
                f"%{AUTHORIZATION_VARIABLE}",
                "--expand-header",
                "Authorization: {{" + AUTHORIZATION_VARIABLE + "}}",
            ]
        if payload or method in ("PUT", "POST"):
            curl += ["--data-binary", "@-"]
        container = self.cid or self.resolve()
        if not container:
            return 0, b"no running container of the engine on this node", {}
        try:
            done = subprocess.run(
                [*exec_argv, container, *curl, url],
                input=payload,
                capture_output=True,
                env=env,
                timeout=REQUEST_TIMEOUT + EXEC_GRACE,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.cid = ""
            return 0, str(exc).encode("utf-8"), {}
        if done.returncode != 0:
            self.cid = ""
            return 0, done.stderr.strip() or f"exit {done.returncode}".encode(), {}
        self.cid = container
        return parse_response(done.stdout)


def parse_response(raw: bytes) -> tuple[int, bytes, dict[str, str]]:
    """Split what ``curl -i`` printed into status, body and headers.

    Args:
        raw: the status line, the header block and the body, as curl wrote them.

    Returns:
        The status code, the body and the headers; status 0 when no HTTP
        status line arrived.
    """
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1").split("\r\n")
    status = lines[0].split()
    if len(status) < 2 or not status[0].startswith("HTTP/") or not status[1].isdigit():
        return 0, raw[:200], {}
    headers = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip()] = value.strip()
    return int(status[1]), body, headers
