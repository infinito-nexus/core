from __future__ import annotations

import functools
import http.client
import ipaddress
import json
import shutil
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING

from crossposter import retry

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

TIMEOUT_SECONDS = 60
UPLOAD_TIMEOUT_SECONDS = 1800
CHUNK_BYTES = 1024 * 1024
FETCHABLE_SCHEMES = frozenset({"http", "https"})
CREDENTIAL_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie"})
REFUSED = 400
THIS_NETWORK = ipaddress.ip_network("0.0.0.0/8")
UNREADABLE = (OSError, ValueError, http.client.HTTPException)


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> object:
        return json.loads(self.body.decode()) if self.body else None


class RequestError(RuntimeError):
    def __init__(
        self, url: str, status: int | None, headers: dict[str, str], detail: str
    ) -> None:
        shown = status if status is not None else "unreachable"
        super().__init__(f"{url}: HTTP {shown} {detail[:300]}")
        self.status = status
        self.headers = headers
        self.detail = detail

    @property
    def transient(self) -> bool:
        return retry.transient(self.status)


class RefusedError(RequestError):
    def __init__(self, url: str, detail: str) -> None:
        super().__init__(url, REFUSED, {}, f"refused: {detail}")


def origin(url: str) -> tuple[str, str]:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme, parts.netloc


def _hostname(url: str) -> str:
    return urllib.parse.urlsplit(url).hostname or ""


def fetchable(url: str) -> bool:
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme in FETCHABLE_SCHEMES and bool(parts.hostname) and port != 0


def require_fetchable(url: str) -> None:
    if not fetchable(url):
        raise RefusedError(url, "only http and https URLs with a host and a valid port")


def _unmapped(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    checked = ipaddress.ip_address(address)
    if isinstance(checked, ipaddress.IPv6Address) and checked.ipv4_mapped:
        return checked.ipv4_mapped
    return checked


def _internal(address: str) -> bool:
    checked = _unmapped(address)
    return (
        checked.is_loopback
        or checked.is_link_local
        or checked.is_unspecified
        or checked.is_multicast
        or checked in THIS_NETWORK
    )


def _not_public(address: str) -> bool:
    checked = _unmapped(address)
    return not checked.is_global or checked.is_multicast


def _dial(
    refused: Callable[[str], bool],
    address: tuple[str, int],
    timeout: float | None,
    source: tuple[str, int] | None,
) -> socket.socket:
    host, port = address
    resolved = [
        info[4][0] for info in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    ]
    blocked = [candidate for candidate in resolved if refused(candidate)]
    if blocked:
        raise RefusedError(f"{host}:{port}", f"{host} resolves to {blocked[0]}")
    failure = OSError(f"{host} resolves to no address")
    for candidate in dict.fromkeys(resolved):
        try:
            return socket.create_connection((candidate, port), timeout, source)
        except OSError as error:
            failure = error
    raise failure


class _Dialled:
    def __init__(
        self, *args: object, refused: Callable[[str], bool], **kwargs: object
    ) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = functools.partial(_dial, refused)


class _Connection(_Dialled, http.client.HTTPConnection):
    pass


class _TLSConnection(_Dialled, http.client.HTTPSConnection):
    pass


class _Guarded:
    def __init__(self, refused: Callable[[str], bool]) -> None:
        super().__init__()
        self.refused = refused


class _HTTPHandler(_Guarded, urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_Connection, req, refused=self.refused)


class _HTTPSHandler(_Guarded, urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(
            _TLSConnection, req, context=self._context, refused=self.refused
        )


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, *, cross_host: bool) -> None:
        super().__init__()
        self.cross_host = cross_host

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request:
        require_fetchable(newurl)
        if not self.cross_host and _hostname(newurl) != _hostname(req.full_url):
            raise RefusedError(
                newurl, f"a redirect away from {_hostname(req.full_url)}"
            )
        follow = super().redirect_request(req, fp, code, msg, headers, newurl)
        if origin(newurl) != origin(req.full_url):
            for name in [
                name for name in follow.headers if name.lower() in CREDENTIAL_HEADERS
            ]:
                follow.remove_header(name)
        return follow


def _opener(
    refused: Callable[[str], bool], *, cross_host: bool
) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _HTTPHandler(refused),
        _HTTPSHandler(refused),
        _Redirects(cross_host=cross_host),
    )


_OPENER = _opener(_internal, cross_host=False)
_MEDIA_OPENER = _opener(_not_public, cross_host=True)


def _outgoing(
    url: str, method: str, headers: dict[str, str], body: bytes | IO[bytes] | None
) -> urllib.request.Request:
    require_fetchable(url)
    return urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310 require_fetchable() limits the scheme to http and https


def _open(
    opener: urllib.request.OpenerDirector,
    outgoing: urllib.request.Request,
    timeout: float,
) -> http.client.HTTPResponse:
    return opener.open(outgoing, timeout=timeout)


def _exchange(
    outgoing: urllib.request.Request, timeout: float, accepted: tuple[int, ...]
) -> Response:
    url = outgoing.full_url
    try:
        with _open(_OPENER, outgoing, timeout) as answer:
            response = Response(
                answer.status, dict(answer.headers.items()), answer.read()
            )
    except urllib.error.HTTPError as error:
        response = Response(error.code, dict(error.headers.items()), error.read())
    except UNREADABLE as error:
        raise RequestError(url, None, {}, str(error)) from error
    if response.status not in accepted:
        raise RequestError(
            url,
            response.status,
            response.headers,
            response.body.decode(errors="replace"),
        )
    return response


def request(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    accepted: tuple[int, ...],
) -> Response:
    return _exchange(_outgoing(url, method, headers, body), TIMEOUT_SECONDS, accepted)


def get_json(url: str, headers: dict[str, str]) -> object:
    return request(
        "GET", url, {**headers, "Accept": "application/json"}, None, (200,)
    ).json()


def download(url: str, headers: dict[str, str], target: Path) -> Path:
    try:
        with (
            _open(
                _MEDIA_OPENER, _outgoing(url, "GET", headers, None), TIMEOUT_SECONDS
            ) as answer,
            target.open("wb") as sink,
        ):
            shutil.copyfileobj(answer, sink, CHUNK_BYTES)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RequestError(
            url, error.code, dict(error.headers.items()), detail
        ) from error
    except UNREADABLE as error:
        raise RequestError(url, None, {}, str(error)) from error
    return target


def upload(
    method: str,
    url: str,
    headers: dict[str, str],
    source: Path,
    accepted: tuple[int, ...],
) -> Response:
    sized = {**headers, "Content-Length": str(source.stat().st_size)}
    with source.open("rb") as body:
        return _exchange(
            _outgoing(url, method, sized, body), UPLOAD_TIMEOUT_SECONDS, accepted
        )
