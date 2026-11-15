from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

import sigv4

REQUEST_TIMEOUT = 60


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
