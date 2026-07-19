"""Generic Docker Registry HTTP API v2 client.

Lists tags and checks tag reachability for ANY registry that speaks the
standard v2 API (Docker Hub, GHCR, MCR, Quay, GitLab/opencode, …) via the
RFC-standard ``WWW-Authenticate: Bearer`` token-challenge flow, so no
per-registry special case is needed. ``docker.io`` resolves to
``registry-1.docker.io`` and bare official names are prefixed with
``library/``.

Reachability (:func:`manifest_exists`) distinguishes three outcomes:
``True`` (tag present), ``False`` (registry answered 404 — tag absent),
and ``None`` (indeterminate: network error, auth wall, rate limit) so
callers can fail on a genuinely broken pin without flaking on a slow or
private registry.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode, urlparse

from utils.docker.image.ref import DOCKER_HUB_REGISTRIES, split_registry_and_name

_UA = "infinito-nexus-version-updater"
_LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"', re.IGNORECASE)
_CHALLENGE_PARAM_RE = re.compile(r'(\w+)="([^"]*)"')
_MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


def _registry_host(registry: str | None) -> str:
    if registry is None or registry in DOCKER_HUB_REGISTRIES:
        return "registry-1.docker.io"
    return registry


def _canonical_repo(registry: str | None, name: str) -> str:
    if (registry is None or registry in DOCKER_HUB_REGISTRIES) and "/" not in name:
        return f"library/{name}"
    return name


def _resolve(image: str) -> tuple[str, str] | None:
    """Return ``(registry_host, repository)`` for *image*, or ``None``."""
    parsed = split_registry_and_name(image)
    if parsed is None:
        return None
    registry, name = parsed
    return _registry_host(registry), _canonical_repo(registry, name)


def _bearer_token(challenge: str, repo: str) -> str | None:
    params = dict(_CHALLENGE_PARAM_RE.findall(challenge or ""))
    realm = params.get("realm")
    if not realm:
        return None
    query = {"scope": params.get("scope") or f"repository:{repo}:pull"}
    if params.get("service"):
        query["service"] = params["service"]
    try:
        req = urllib.request.Request(  # noqa: S310 - https request to a trusted registry host
            f"{realm}?{urlencode(query)}", headers={"User-Agent": _UA}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - https request to a trusted registry host
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None
    return body.get("token") or body.get("access_token")


def _request(url: str, repo: str, method: str, accept: str | None):
    """Authenticated v2 request with a single 401 bearer-challenge retry.

    Returns ``(status, headers, body|None)``, or ``None`` when the host is
    unreachable (connection/timeout).
    """
    token: str | None = None
    for _attempt in (0, 1):
        headers = {"User-Agent": _UA}
        if accept:
            headers["Accept"] = accept
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers, method=method)  # noqa: S310 - https request to a trusted registry host
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 - https request to a trusted registry host
                return (
                    resp.status,
                    resp.headers,
                    resp.read() if method != "HEAD" else None,
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and token is None:
                token = _bearer_token(exc.headers.get("WWW-Authenticate", ""), repo)
                if token:
                    continue
            return exc.code, exc.headers, None
        except (urllib.error.URLError, OSError):
            return None
    return None


def fetch_registry_tags(
    image: str, max_pages: int = 10, last: str | None = None
) -> list[str]:
    """Return all tags for *image* from its registry (empty on any failure).

    ``last`` seeds the OCI pagination cursor: only tags sorting lexically
    after it are returned. Repos like GitLab CNG carry tens of thousands
    of commit-sha tags before the ``v*`` release tags, so an unseeded
    scan exhausts ``max_pages`` without ever reaching them.
    """
    resolved = _resolve(image)
    if resolved is None:
        return []
    host, repo = resolved
    url = f"https://{host}/v2/{quote(repo, safe='/')}/tags/list?n=1000"
    if last:
        url += f"&last={quote(last, safe='')}"
    tags: list[str] = []
    for _page in range(max_pages):
        result = _request(url, repo, method="GET", accept="application/json")
        if result is None:
            break
        status, resp_headers, body = result
        if status != 200 or not body:
            break
        try:
            data = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            break
        tags.extend(data.get("tags") or [])
        match = _LINK_NEXT_RE.search(resp_headers.get("Link", "") or "")
        if not match:
            break
        nxt = match.group(1)
        if nxt.startswith("http"):
            url = nxt
        else:
            parsed = urlparse(url)
            url = f"{parsed.scheme}://{parsed.netloc}{nxt}"
    return tags


def manifest_exists(image: str, reference: str) -> bool | None:
    """Whether ``image:reference`` resolves to a manifest.

    ``True`` present, ``False`` registry said 404, ``None`` indeterminate
    (network error, 401/403 auth wall, 429 rate limit, 5xx).
    """
    resolved = _resolve(image)
    if resolved is None:
        return None
    host, repo = resolved
    url = f"https://{host}/v2/{quote(repo, safe='/')}/manifests/{quote(reference, safe='')}"
    result = _request(url, repo, method="HEAD", accept=_MANIFEST_ACCEPT)
    if result is None:
        return None
    status = result[0]
    if status == 200:
        return True
    if status == 404:
        return False
    return None
