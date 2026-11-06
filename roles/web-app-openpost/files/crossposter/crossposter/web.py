from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING

from crossposter import retry

if TYPE_CHECKING:
    from http.client import HTTPResponse
    from pathlib import Path

TIMEOUT_SECONDS = 60
UPLOAD_TIMEOUT_SECONDS = 1800
CHUNK_BYTES = 1024 * 1024


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


def _outgoing(
    url: str, method: str, headers: dict[str, str], body: bytes | IO[bytes] | None
) -> urllib.request.Request:
    return urllib.request.Request(url, data=body, method=method, headers=headers)  # noqa: S310 validated route and OpenPost URLs


def _open(outgoing: urllib.request.Request, timeout: float) -> HTTPResponse:
    return urllib.request.urlopen(outgoing, timeout=timeout)  # noqa: S310 validated route and OpenPost URLs


def _exchange(
    outgoing: urllib.request.Request, timeout: float, accepted: tuple[int, ...]
) -> Response:
    url = outgoing.full_url
    try:
        with _open(outgoing, timeout) as answer:
            response = Response(
                answer.status, dict(answer.headers.items()), answer.read()
            )
    except urllib.error.HTTPError as error:
        response = Response(error.code, dict(error.headers.items()), error.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
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
            _open(_outgoing(url, "GET", headers, None), TIMEOUT_SECONDS) as answer,
            target.open("wb") as sink,
        ):
            shutil.copyfileobj(answer, sink, CHUNK_BYTES)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RequestError(
            url, error.code, dict(error.headers.items()), detail
        ) from error
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
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
