"""Tag listings of the registries :mod:`utils.update.docker` bumps images on:
Docker Hub, GHCR and MCR."""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode

from utils.docker.image.ref import (
    GHCR_REGISTRY,
    MCR_REGISTRY,
    dockerhub_repo,
    split_registry_and_name,
)


def fetch_dockerhub_tags(image: str, max_pages: int = 5) -> list[str]:
    repo = dockerhub_repo(image)
    tags: list[str] = []
    for page in range(1, max_pages + 1):
        url = (
            f"https://hub.docker.com/v2/repositories/{repo}/tags/"
            f"?page_size=100&page={page}"
        )
        req = urllib.request.Request(
            url, headers={"User-Agent": "infinito-nexus-version-updater"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                if resp.status == 429:
                    time.sleep(2)
                    continue
                body = json.loads(resp.read().decode())
        except (
            urllib.error.URLError,
            OSError,
            http.client.HTTPException,
            json.JSONDecodeError,
        ):
            break
        tags.extend(item["name"] for item in body.get("results", []))
        if not body.get("next"):
            break
    return tags


def is_ghcr(image: str) -> bool:
    parsed = split_registry_and_name(image)
    return parsed is not None and parsed[0] == GHCR_REGISTRY


def ghcr_repo(image: str) -> str:
    parsed = split_registry_and_name(image)
    if parsed is None or parsed[0] != GHCR_REGISTRY:
        raise ValueError(f"Image is not a GHCR reference: {image!r}")
    return parsed[1]


def fetch_ghcr_tags(image: str) -> list[str]:
    name = ghcr_repo(image)
    token_query = urlencode(
        {"scope": f"repository:{name}:pull", "service": GHCR_REGISTRY}
    )
    token_url = f"https://{GHCR_REGISTRY}/token?{token_query}"
    try:
        req = urllib.request.Request(
            token_url, headers={"User-Agent": "infinito-nexus-version-updater"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            token_body = json.loads(resp.read().decode())
        token = token_body.get("token") or token_body.get("access_token")
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
        json.JSONDecodeError,
    ):
        return []

    if not token:
        return []

    tags_url = f"https://{GHCR_REGISTRY}/v2/{quote(name, safe='/')}/tags/list"
    req = urllib.request.Request(
        tags_url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "infinito-nexus-version-updater",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
        json.JSONDecodeError,
    ):
        return []

    return body.get("tags") or []


def is_mcr(image: str) -> bool:
    parsed = split_registry_and_name(image)
    return parsed is not None and parsed[0] == MCR_REGISTRY


def is_supported_registry(image: str) -> bool:
    """Whether *image* resolves to a registry the generic v2 client can query."""
    return split_registry_and_name(image) is not None


def mcr_repo(image: str) -> str:
    parsed = split_registry_and_name(image)
    if parsed is None or parsed[0] != MCR_REGISTRY:
        raise ValueError(f"Image is not an MCR reference: {image!r}")
    return parsed[1]


_LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"', re.IGNORECASE)


def fetch_mcr_tags(image: str, max_pages: int = 10) -> list[str]:
    name = mcr_repo(image)
    base = f"https://{MCR_REGISTRY}"
    url = f"{base}/v2/{quote(name, safe='/')}/tags/list?n=100"
    tags: list[str] = []
    for _ in range(max_pages):
        req = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": "infinito-nexus-version-updater"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                body = json.loads(resp.read().decode())
                link_header = resp.headers.get("Link", "")
        except (
            urllib.error.URLError,
            OSError,
            http.client.HTTPException,
            json.JSONDecodeError,
        ):
            break
        tags.extend(body.get("tags") or [])
        match = _LINK_NEXT_RE.search(link_header)
        if not match:
            break
        next_link = match.group(1)
        url = next_link if next_link.startswith("http") else f"{base}{next_link}"
    return tags
