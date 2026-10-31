"""Ask a tracker whether the issue or pull request a directive names is open.

One adapter per forge reads the tracker's REST API and maps its own state
fields onto a :class:`Status`:

* GitHub: ``GET /repos/<owner>/<repo>/issues/<n>`` on api.github.com, which
  answers for pull requests too. ``GITHUB_TOKEN``, else ``GH_TOKEN``, is sent
  when set.
* GitLab: ``GET /api/v4/projects/<path>/(issues|merge_requests)/<n>`` on the
  item's host. ``GITLAB_TOKEN`` is sent when set, to gitlab.com only, because a
  token of gitlab.com means nothing to a self-hosted instance and must not leak
  to one.
* Forgejo or Gitea: ``GET /api/v1/repos/<owner>/<repo>/(issues|pulls)/<n>`` on
  the item's host, without a token.

An answer about the item is ``OPEN`` or ``CLOSED``, and HTTP 404 or 410 is
``MISSING``. A timeout, a connection error, HTTP 429 and a 5xx answer are
retried with a doubling pause before they count. An exhausted rate limit (a
429 that survives the retries, or a 403 that carries ``X-RateLimit-Remaining:
0`` or ``Retry-After``) is ``RATE_LIMITED``, with the reset time the tracker
announced. Everything else that still fails is ``UNVERIFIED``: a network error,
an auth wall, any other status, a body that is not a JSON object and a state the
adapter does not know. A tracker that could not be asked therefore never reads
as one that said the item is still open.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple
from urllib.parse import quote

import requests

from utils.upstream.directive import GITEA, GITHUB, GITLAB, PULL

if TYPE_CHECKING:
    from collections.abc import Callable

    from utils.upstream.directive import Reference

OPEN = "open"
CLOSED = "closed"
MISSING = "missing"
RATE_LIMITED = "rate_limited"
UNVERIFIED = "unverified"

TIMEOUT_SECONDS = 10
USER_AGENT = "infinito-nexus-upstream-reference"

_GITHUB_API = "https://api.github.com"
_GITLAB_COM = "gitlab.com"
_GONE = frozenset({404, 410})
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.0
_RESET_HEADERS = ("X-RateLimit-Reset", "RateLimit-Reset")


class Status(NamedTuple):
    """What a tracker said about one item.

    Attributes:
        verdict: ``open``, ``closed``, ``missing``, ``rate_limited`` or
            ``unverified``.
        state: the tracker's state in words, such as ``merged``,
            ``closed (not planned)`` or ``rate limited (HTTP 403)``.
        date: the merge or close timestamp the tracker reported; for a rate
            limit, when it resets (``at <ISO time>``, ``in <n> s`` or
            ``at an unknown time``); else ``""``.
    """

    verdict: str
    state: str
    date: str


class _NoAnswerError(Exception):
    """The tracker gave no usable answer; carries the :class:`Status` to report."""

    def __init__(self, status: Status) -> None:
        super().__init__(status.state)
        self.status = status


def api_url(reference: Reference) -> str:
    """The REST URL that answers for one item.

    Args:
        reference: the item a directive names.
    """
    if reference.forge == GITHUB:
        return f"{_GITHUB_API}/repos/{reference.project}/issues/{reference.number}"
    if reference.forge == GITLAB:
        collection = "merge_requests" if reference.kind == PULL else "issues"
        project = quote(reference.project, safe="")
        return (
            f"https://{reference.host}/api/v4/projects/{project}"
            f"/{collection}/{reference.number}"
        )
    collection = "pulls" if reference.kind == PULL else "issues"
    return (
        f"https://{reference.host}/api/v1/repos/{reference.project}"
        f"/{collection}/{reference.number}"
    )


def _headers(reference: Reference) -> dict[str, str]:
    """Request headers for one item's tracker, the token included when set.

    Args:
        reference: the item a directive names.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if reference.forge == GITHUB:
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif reference.forge == GITLAB and reference.host == _GITLAB_COM:
        token = os.environ.get("GITLAB_TOKEN")
        if token:
            headers["PRIVATE-TOKEN"] = token
    return headers


def _rate_limited(response: requests.Response) -> bool:
    """Whether an answer is an exhausted rate limit rather than a refusal.

    Args:
        response: the tracker's answer, after the retries.
    """
    if response.status_code == 429:
        return True
    headers = response.headers
    return response.status_code == 403 and (
        headers.get("X-RateLimit-Remaining") == "0" or "Retry-After" in headers
    )


def _reset(response: requests.Response) -> str:
    """When the rate limit behind *response* resets, in words.

    Args:
        response: a rate-limited answer; ``X-RateLimit-Reset`` (GitHub, Gitea)
            and ``RateLimit-Reset`` (GitLab) carry epoch seconds,
            ``Retry-After`` a delay in seconds.
    """
    for name in _RESET_HEADERS:
        value = response.headers.get(name)
        if value and value.isdigit():
            return f"at {datetime.fromtimestamp(int(value), tz=UTC).isoformat()}"
    delay = response.headers.get("Retry-After")
    if delay and delay.isdigit():
        return f"in {delay} s"
    return "at an unknown time"


def _refusal(response: requests.Response) -> str:
    """Name why a non-200 answer says nothing about the item.

    Args:
        response: the tracker's answer.
    """
    code = response.status_code
    if code in (401, 403):
        return f"auth wall (HTTP {code})"
    if code >= 500:
        return f"server error (HTTP {code})"
    return f"unexpected answer (HTTP {code})"


def _get(url: str, headers: dict[str, str]) -> requests.Response:
    """Fetch one item, retrying a timeout, a connection error, 429 and 5xx.

    Args:
        url: the API URL of one item.
        headers: the complete request headers.

    Raises:
        _NoAnswerError: no attempt reached the tracker.
    """
    for attempt in range(_RETRY_ATTEMPTS):
        last = attempt == _RETRY_ATTEMPTS - 1
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)
        except (requests.Timeout, requests.ConnectionError) as exc:
            if last:
                raise _NoAnswerError(
                    Status(UNVERIFIED, f"{type(exc).__name__}: {exc}", "")
                ) from exc
        except requests.RequestException as exc:
            raise _NoAnswerError(
                Status(UNVERIFIED, f"{type(exc).__name__}: {exc}", "")
            ) from exc
        else:
            if response.status_code not in _RETRY_STATUS or last:
                return response
        time.sleep(_RETRY_BACKOFF_SECONDS * 2**attempt)
    raise AssertionError("unreachable")


def _json(url: str, headers: dict[str, str]) -> dict:
    """Return the JSON object a tracker answers for *url*.

    Args:
        url: the API URL of one item.
        headers: the complete request headers.

    Raises:
        _NoAnswerError: the tracker gave no usable answer.
    """
    response = _get(url, headers)
    if response.status_code in _GONE:
        raise _NoAnswerError(Status(MISSING, f"HTTP {response.status_code}", ""))
    if _rate_limited(response):
        raise _NoAnswerError(
            Status(
                RATE_LIMITED,
                f"rate limited (HTTP {response.status_code})",
                _reset(response),
            )
        )
    if response.status_code != 200:
        raise _NoAnswerError(Status(UNVERIFIED, _refusal(response), ""))
    try:
        body = response.json()
    except ValueError as exc:
        raise _NoAnswerError(Status(UNVERIFIED, "the answer is not JSON", "")) from exc
    if not isinstance(body, dict):
        raise _NoAnswerError(Status(UNVERIFIED, "the answer is not a JSON object", ""))
    return body


def _unknown(state: object) -> Status:
    """The status of an answer whose state field no adapter maps.

    Args:
        state: the state field as the tracker sent it.
    """
    return Status(UNVERIFIED, f"unknown state {state!r}", "")


def github_status(body: dict) -> Status:
    """Map a GitHub issue object onto a :class:`Status`.

    Args:
        body: the object ``/repos/<owner>/<repo>/issues/<n>`` returns; for a
            pull request it carries a ``pull_request`` object with ``merged_at``.
    """
    state = body.get("state")
    if state == "open":
        return Status(OPEN, "open", "")
    if state != "closed":
        return _unknown(state)
    pull = body.get("pull_request")
    if isinstance(pull, dict):
        if pull.get("merged_at"):
            return Status(CLOSED, "merged", pull["merged_at"])
        return Status(CLOSED, "closed unmerged", body.get("closed_at") or "")
    reason = body.get("state_reason")
    words = f"closed ({reason.replace('_', ' ')})" if reason else "closed"
    return Status(CLOSED, words, body.get("closed_at") or "")


def gitlab_status(body: dict) -> Status:
    """Map a GitLab issue or merge request object onto a :class:`Status`.

    Args:
        body: the object ``/projects/<path>/issues/<n>`` or
            ``/projects/<path>/merge_requests/<n>`` returns. A ``locked``
            merge request is one being merged right now, so it is still open.
    """
    state = body.get("state")
    if state in ("opened", "locked"):
        return Status(OPEN, state, "")
    if state == "merged":
        return Status(CLOSED, "merged", body.get("merged_at") or "")
    if state == "closed":
        return Status(CLOSED, "closed", body.get("closed_at") or "")
    return _unknown(state)


def gitea_status(body: dict) -> Status:
    """Map a Forgejo or Gitea issue or pull request object onto a :class:`Status`.

    Args:
        body: the object ``/repos/<owner>/<repo>/issues/<n>`` or
            ``/repos/<owner>/<repo>/pulls/<n>`` returns; a pull request
            carries ``merged`` itself, an issue that is a pull request carries
            it in ``pull_request``.
    """
    state = body.get("state")
    if state == "open":
        return Status(OPEN, "open", "")
    if state != "closed":
        return _unknown(state)
    pull = body.get("pull_request")
    meta = pull if isinstance(pull, dict) else body
    if meta.get("merged"):
        return Status(CLOSED, "merged", meta.get("merged_at") or "")
    return Status(CLOSED, "closed", body.get("closed_at") or "")


_MAPPERS: dict[str, Callable[[dict], Status]] = {
    GITHUB: github_status,
    GITLAB: gitlab_status,
    GITEA: gitea_status,
}


def status_of(reference: Reference) -> Status:
    """Ask the item's tracker whether it is still open.

    Args:
        reference: the item a directive names.
    """
    try:
        body = _json(api_url(reference), _headers(reference))
    except _NoAnswerError as no_answer:
        return no_answer.status
    return _MAPPERS[reference.forge](body)
