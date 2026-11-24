from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlparse

from utils.update.base import captured_versions
from utils.update.docker import (
    dockerhub_repo,
    fetch_dockerhub_tags,
    fetch_ghcr_tags,
    fetch_mcr_tags,
    is_dockerhub,
    is_ghcr,
    is_mcr,
)
from utils.update.fetch import TIMEOUT_SECONDS, documents, get

if TYPE_CHECKING:
    from pathlib import Path


def dockerhub_named_tags(image: str, match: str) -> list[str]:
    """Return the Docker Hub tags of *image* whose name contains *match*.

    Args:
        image: Docker Hub reference.
        match: substring the registry filters on, reaching tags beyond the
            first pages of the unfiltered listing.
    """
    query = urlencode({"name": match, "page_size": 100})
    url = f"https://hub.docker.com/v2/repositories/{dockerhub_repo(image)}/tags?{query}"
    try:
        payload = json.loads(get(url))
    except (OSError, ValueError):
        return []
    return [str(result["name"]) for result in payload.get("results") or []]


def registry_v2_tags(image: str, match: str = "") -> list[str]:
    """Return the tags of *image* from its registry's v2 API.

    Args:
        image: reference including the registry host, e.g.
            ``gcr.io/cadvisor/cadvisor``.
        match: when set and the registry can filter server-side, the
            substring every returned tag carries.
    """
    if is_dockerhub(image):
        return (
            dockerhub_named_tags(image, match) if match else fetch_dockerhub_tags(image)
        )
    if is_ghcr(image):
        return fetch_ghcr_tags(image)
    if is_mcr(image):
        return fetch_mcr_tags(image)
    host, _, repository = image.partition("/")
    url = f"https://{host}/v2/{repository}/tags/list"
    try:
        return list(json.loads(get(url)).get("tags") or [])
    except urllib.error.HTTPError as error:
        if error.code != 401:
            return []
        challenge = error.headers.get("WWW-Authenticate", "")
    except (OSError, ValueError):
        return []
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    realm = fields.pop("realm", "")
    if not realm or urlparse(realm).scheme != "https":
        return []
    query = "&".join(f"{name}={value}" for name, value in fields.items())
    try:
        token = json.loads(get(f"{realm}?{query}")).get("token", "")
        payload = get(url, {"Authorization": f"Bearer {token}"})
        return list(json.loads(payload).get("tags") or [])
    except (OSError, ValueError):
        return []


def npm_versions(package: str) -> list[str]:
    """Return every published version of an npm *package*."""
    try:
        payload = json.loads(get(f"https://registry.npmjs.org/{package}"))
    except (OSError, ValueError):
        return []
    return list((payload.get("versions") or {}).keys())


def http_regex_versions(
    urls: str | list[str], pattern: str, template: str = ""
) -> list[str]:
    """Return every version *pattern* names in the documents at *urls*."""
    try:
        body = documents(urls)
    except OSError:
        return []
    return captured_versions(body, pattern, template)


def _role_script(repo_root: Path, role: str, path: str) -> Path | None:
    """Args:
        repo_root: repository root.
        role: role the script belongs to.
        path: role-relative path of the script.

    Returns:
        The resolved script, or ``None`` when *path* resolves outside
        ``roles/<role>/`` (absolute, ``..``, or a symlink pointing out) or to
        anything but a regular file.
    """
    role_root = (repo_root / "roles" / role).resolve()
    script = (role_root / path).resolve()
    return script if script.is_relative_to(role_root) and script.is_file() else None


def script_versions(repo_root: Path, role: str, path: str, current: str) -> list[str]:
    """Return what a role-local updater prints for its pin.

    Args:
        repo_root: repository root.
        role: role the script belongs to.
        path: role-relative path of the script.
        current: the version currently pinned, passed as the first argument.

    Returns:
        The versions the script prints; nothing when it fails, and nothing,
        reported on stderr before anything runs, when *path* is not a regular
        file inside ``roles/<role>/``.
    """
    script = _role_script(repo_root, role, path)
    if script is None:
        print(
            f"[source] WARN {role}: refusing update script '{path}', it is not "
            f"a regular file inside roles/{role}/",
            file=sys.stderr,
        )
        return []
    try:
        proc = subprocess.run(
            [str(script), current],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return proc.stdout.split() if proc.returncode == 0 else []
