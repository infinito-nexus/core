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

import hashlib
import http.client
import json
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

from utils.docker.image.ref import DOCKER_HUB_REGISTRIES, split_registry_and_name
from utils.docker.mirror import mirror_image

_UA = "infinito-nexus-version-updater"
_CACHE_ROOT = Path(tempfile.gettempdir()) / "infinito-registry-probe"
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
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
        json.JSONDecodeError,
    ):
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
        except (urllib.error.URLError, OSError, http.client.HTTPException):
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


def fetch_manifest(image: str, reference: str) -> dict | None:
    """Return the parsed manifest (or index) for ``image:reference``.

    ``None`` on any indeterminate outcome: unresolvable name, network error,
    auth wall, rate limit, non-200 status, or unparsable body.
    """
    resolved = _resolve(image)
    if resolved is None:
        return None
    host, repo = resolved
    url = f"https://{host}/v2/{quote(repo, safe='/')}/manifests/{quote(reference, safe='')}"
    result = _request(url, repo, method="GET", accept=_MANIFEST_ACCEPT)
    if result is None:
        return None
    status, _resp_headers, body = result
    if status != 200 or not body:
        return None
    try:
        parsed = json.loads(body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _cache_path(kind: str, *parts: str) -> Path:
    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()
    return _CACHE_ROOT / kind / digest[:2] / f"{digest}.json"


def _cache_read(kind: str, *parts: str):
    try:
        return json.loads(
            _cache_path(kind, *parts).read_text()  # nocheck: cache-read
        )
    except (OSError, json.JSONDecodeError):
        return None


def _cache_write(kind: str, value, *parts: str) -> None:
    """Persist a *positive* probe result; indeterminate answers are never stored."""
    path = _cache_path(kind, *parts)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    except OSError:
        return


def _probe_order(image: str) -> list[str]:
    """Return *image* addressed at the mirror first, upstream second."""
    mirrored = mirror_image(image)
    if mirrored is None or mirrored == image:
        return [image]
    return [mirrored, image]


def _platform_digest(manifests: list, os_name: str, architecture: str) -> str | None:
    for entry in manifests:
        if not isinstance(entry, dict):
            continue
        platform = entry.get("platform") or {}
        if (
            platform.get("os") == os_name
            and platform.get("architecture") == architecture
        ):
            digest = entry.get("digest")
            if isinstance(digest, str) and digest:
                return digest
    return None


def manifest_transfer_size(
    image: str,
    reference: str,
    *,
    os_name: str = "linux",
    architecture: str = "amd64",
) -> int | None:
    """Return the compressed transfer size of ``image:reference`` in bytes.

    The size is the config blob plus every layer blob, i.e. what a pull moves
    over the wire. A multi-platform index is resolved to the
    ``os_name``/``architecture`` manifest first.

    ``None`` on any indeterminate outcome (see :func:`fetch_manifest`), on an
    index without a matching platform, and on a manifest that carries no layers.

    Read from the GHCR mirror when one is configured, falling back to the
    upstream registry only for images the mirror does not carry. Measured sizes
    are cached on disk (see :func:`_cache_dir`).
    """
    cached = _cache_read("size", image, reference, os_name, architecture)
    if isinstance(cached, int):
        return cached
    for candidate in _probe_order(image):
        size = _transfer_size_at(candidate, reference, os_name, architecture)
        if size is not None:
            _cache_write("size", size, image, reference, os_name, architecture)
            return size
    return None


def _transfer_size_at(
    image: str, reference: str, os_name: str, architecture: str
) -> int | None:
    doc = fetch_manifest(image, reference)
    if doc is None:
        return None
    manifests = doc.get("manifests")
    if isinstance(manifests, list) and manifests:
        digest = _platform_digest(manifests, os_name, architecture)
        if digest is None:
            return None
        doc = fetch_manifest(image, digest)
        if doc is None or doc.get("manifests"):
            return None
    layers = doc.get("layers")
    if not isinstance(layers, list) or not layers:
        return None
    total = int((doc.get("config") or {}).get("size") or 0)
    for layer in layers:
        if not isinstance(layer, dict):
            return None
        total += int(layer.get("size") or 0)
    return total


def _fetch_blob(image: str, digest: str) -> dict | None:
    """Return a parsed JSON blob of *image*, or None on any failure."""
    resolved = _resolve(image)
    if resolved is None:
        return None
    host, repo = resolved
    url = f"https://{host}/v2/{quote(repo, safe='/')}/blobs/{quote(digest, safe='')}"
    result = _request(url, repo, method="GET", accept="application/json")
    if result is None:
        return None
    status, _resp_headers, body = result
    if status != 200 or not body:
        return None
    try:
        parsed = json.loads(body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _healthcheck_at(
    image: str, reference: str, os_name: str, architecture: str
) -> dict | None:
    doc = fetch_manifest(image, reference)
    if doc is None:
        return None
    manifests = doc.get("manifests")
    if isinstance(manifests, list) and manifests:
        digest = _platform_digest(manifests, os_name, architecture)
        if digest is None:
            return None
        doc = fetch_manifest(image, digest)
        if doc is None or doc.get("manifests"):
            return None
    config_digest = (doc.get("config") or {}).get("digest")
    if not isinstance(config_digest, str) or not config_digest:
        return None
    blob = _fetch_blob(image, config_digest)
    if blob is None:
        return None
    return (blob.get("config") or {}).get("Healthcheck") or {}


def image_healthcheck(
    image: str,
    reference: str,
    *,
    os_name: str = "linux",
    architecture: str = "amd64",
) -> dict | None:
    """Return the ``HEALTHCHECK`` baked into ``image:reference``.

    Args:
        image: image name, with or without registry host.
        reference: tag or digest.
        os_name: platform to resolve a multi-arch index to.
        architecture: platform to resolve a multi-arch index to.

    Returns:
        The image's healthcheck config, ``{}`` when the image definitively
        declares none, and ``None`` when the answer is indeterminate - an
        unresolvable name, a network error, an auth wall, a rate limit, or an
        index without a matching platform. A caller must not read ``{}`` and
        ``None`` as the same thing: only the former is evidence.

    Reads from the mirror first and falls back to the upstream registry only
    for images the mirror does not carry, so a full sweep does not spend the
    upstream's rate limit. Determinate answers are cached on disk.
    """
    return image_healthcheck_probed(
        image, reference, os_name=os_name, architecture=architecture
    )[0]


def image_healthcheck_probed(
    image: str,
    reference: str,
    *,
    os_name: str = "linux",
    architecture: str = "amd64",
) -> tuple[dict | None, str]:
    """:func:`image_healthcheck` plus which address answered.

    Returns:
        ``(healthcheck, source)`` where source is ``cache``, ``mirror``,
        ``upstream`` or ``none``. Reading upstream is the documented fallback
        for images the mirror does not carry; a caller that sweeps many images
        can use the counts to tell a fallback from a mirror that stopped
        working.
    """
    cached = _cache_read("healthcheck", image, reference, os_name, architecture)
    if isinstance(cached, dict):
        return cached, "cache"
    mirrored = mirror_image(image)
    for candidate in _probe_order(image):
        found = _healthcheck_at(candidate, reference, os_name, architecture)
        if found is not None:
            _cache_write("healthcheck", found, image, reference, os_name, architecture)
            return found, "mirror" if candidate == mirrored else "upstream"
    return None, "none"


def manifest_exists(image: str, reference: str) -> bool | None:
    """Whether ``image:reference`` resolves to a manifest.

    ``True`` present, ``False`` registry said 404, ``None`` indeterminate
    (network error, 401/403 auth wall, 429 rate limit, 5xx).

    A confirmed hit is cached on disk. The probe stays on the upstream registry:
    it exists to prove the declared pin is still pullable from where the deploy
    pulls it, which a mirrored copy cannot answer for.
    """
    if _cache_read("exists", image, reference) is True:
        return True
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
        _cache_write("exists", True, image, reference)
        return True
    if status == 404:
        return False
    return None
