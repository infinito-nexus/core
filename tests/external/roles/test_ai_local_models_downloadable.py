"""Every declared local AI model still resolves to a file upstream serves.

``group_vars/all/16_ai.yml`` pins each model by repository, file name and
sha256 so a deploy fetches it with a checksum instead of trusting whatever a
search term resolves to. A pin that upstream no longer matches becomes a deploy
that transfers half a gigabyte on every host and then fails on the digest, with
nothing in the failure naming the declaration as the cause.

The declaration's own shape is a repository fact and is asserted. Whether the
file is still served is a network fact, so a timeout or a refused connection is
reported as unverified rather than failing, the way the sibling external checks
do: a firewalled runner must not turn a good pin red. An answer that contradicts
the pin is a defect in the repository and does fail.
"""

from __future__ import annotations

import concurrent.futures
import re
import unittest
from urllib.parse import urlsplit

import requests

from utils.annotations.message import warning
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_AI_VARS_FILE = "group_vars/all/16_ai.yml"
_HUGGINGFACE_PREFIX = "https://huggingface.co/"
_USER_AGENT = "infinito-nexus-model-pin-check"
_TIMEOUT_SECONDS = 20
_MAX_WORKERS = 4
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _models() -> list[dict]:
    data = load_yaml_any(str(PROJECT_ROOT / _AI_VARS_FILE)) or {}
    entries = data.get("AI_LOCAL_MODELS") if isinstance(data, dict) else None
    return [entry for entry in (entries or []) if isinstance(entry, dict)]


def _repo_path(source: str) -> str:
    """Return ``user/repo`` for a HuggingFace source, else the empty string."""
    if not source.startswith(_HUGGINGFACE_PREFIX):
        return ""
    return source[len(_HUGGINGFACE_PREFIX) :].strip("/")


def _download_url(entry: dict) -> str:
    return f"{entry['source'].rstrip('/')}/resolve/main/{entry['file']}"


def _upstream_digests(repo_path: str) -> tuple[str, object]:
    """Return (kind, payload) with kind one of ok, warn, unverified.

    On ``ok`` the payload maps each published file name to its sha256, which is
    what the pin is compared against without transferring the file itself.
    """
    url = f"{_HUGGINGFACE_PREFIX}api/models/{repo_path}"
    try:
        response = requests.get(
            url,
            params={"blobs": "true"},
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        return "unverified", f"Timeout: {exc}"
    except requests.RequestException as exc:
        return "unverified", f"{type(exc).__name__}: {exc}"

    if response.status_code != 200:
        return "warn", f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError as exc:
        return "unverified", f"unparsable answer: {exc}"

    digests = {}
    for sibling in payload.get("siblings") or []:
        if not isinstance(sibling, dict):
            continue
        name = sibling.get("rfilename")
        digest = (sibling.get("lfs") or {}).get("sha256")
        if isinstance(name, str) and isinstance(digest, str):
            digests[name] = digest
    return "ok", digests


def _reachable(url: str) -> tuple[str, str]:
    """Return (kind, detail); a redirect to the CDN counts as reachable."""
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Range": "bytes=0-0"},
            stream=True,
            timeout=_TIMEOUT_SECONDS,
        )
        try:
            status = response.status_code
        finally:
            response.close()
    except requests.Timeout as exc:
        return "unverified", f"Timeout: {exc}"
    except requests.RequestException as exc:
        return "unverified", f"{type(exc).__name__}: {exc}"

    if status < 400:
        return "ok", f"HTTP {status}"
    return "warn", f"HTTP {status}"


class TestAiLocalModelsDownloadable(unittest.TestCase):
    def test_every_declared_model_is_pinned(self) -> None:
        models = _models()
        self.assertTrue(models, f"{_AI_VARS_FILE} declares no AI_LOCAL_MODELS")

        unpinned = []
        for entry in models:
            alias = str(entry.get("alias") or "<no alias>")
            source = entry.get("source")
            file_name = entry.get("file")
            digest = entry.get("sha256")
            if not isinstance(source, str) or not urlsplit(source).scheme:
                unpinned.append(f"{alias}: 'source' is not an absolute URL")
            if not isinstance(file_name, str) or not file_name:
                unpinned.append(f"{alias}: 'file' is missing")
            if not isinstance(digest, str) or not _SHA256.match(digest):
                unpinned.append(f"{alias}: 'sha256' is not 64 hex characters")

        self.assertFalse(
            unpinned,
            f"{len(unpinned)} model declaration(s) in {_AI_VARS_FILE} cannot be "
            f"fetched with a checksum. Each entry needs 'source', 'file' and "
            f"'sha256':\n" + "\n".join(f"  {line}" for line in unpinned),
        )

    def test_every_pin_matches_what_upstream_serves(self) -> None:
        models = [
            entry
            for entry in _models()
            if isinstance(entry.get("source"), str)
            and isinstance(entry.get("file"), str)
            and isinstance(entry.get("sha256"), str)
        ]
        self.assertTrue(models, f"{_AI_VARS_FILE} declares no pinned model")

        repo_paths = [_repo_path(entry["source"]) for entry in models]
        with concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            api = list(pool.map(_upstream_digests, repo_paths))
            reach = list(pool.map(_reachable, [_download_url(e) for e in models]))

        mismatched = []
        for entry, repo_path, (kind, payload), (rkind, rdetail) in zip(
            models, repo_paths, api, reach, strict=True
        ):
            alias = entry["alias"]
            url = _download_url(entry)
            if rkind != "ok":
                warning(
                    f"{alias}: {url} answered {rdetail}"
                    if rkind == "warn"
                    else f"{alias}: {url} was not checked ({rdetail})",
                    title="Model unreachable"
                    if rkind == "warn"
                    else "Model unverified",
                    file=_AI_VARS_FILE,
                )
            if not repo_path:
                continue
            if kind != "ok":
                warning(
                    f"{alias}: {repo_path} was not checked ({payload})",
                    title="Model pin unverified",
                    file=_AI_VARS_FILE,
                )
                continue
            published = payload.get(entry["file"])
            if published is None:
                mismatched.append(
                    f"{alias}: {repo_path} no longer publishes {entry['file']}"
                )
            elif published != entry["sha256"]:
                mismatched.append(
                    f"{alias}: {entry['file']} is {published} upstream, "
                    f"pinned as {entry['sha256']}"
                )

        self.assertFalse(
            mismatched,
            f"{len(mismatched)} model pin(s) in {_AI_VARS_FILE} no longer match "
            f"what upstream publishes. Update 'file' and 'sha256' to the value "
            f"the repository serves today:\n"
            + "\n".join(f"  {line}" for line in mismatched),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
