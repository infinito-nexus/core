"""Webhook intake rules for svc-ai-agent-orchestrator.

The orchestrator accepts a webhook only with a valid signature, drops a
repeated delivery id, and then re-fetches the event by id from the provider's
API and acts on the fetched data, never on the webhook body. This module holds
the deterministic, stack-free parts: the signature check, the delivery-id
deduplication, the API path that re-fetches the object a webhook names, and
the classification of the fetched object into a trigger. The fetch itself is
an I/O step the orchestrator injects.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import string
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.digests import COMMIT

if TYPE_CHECKING:
    from collections.abc import Callable

SIGNATURE_PREFIX = "sha256="
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
MANIFEST = re.compile(
    r"(?:^|/)(?:requirements[^/]*\.txt|pyproject\.toml|poetry\.lock|uv\.lock"
    r"|package(?:-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|Gemfile(?:\.lock)?"
    r"|composer\.(?:json|lock)|go\.(?:mod|sum)|Cargo\.(?:toml|lock))$"
)


@dataclass(frozen=True)
class Event:
    """A trigger read from the re-fetched object, never from the body.

    Args:
        trigger: the trigger name ``agent.yml`` lists.
        repository: the ``owner/name`` the object belongs to.
        outsider: the author is no collaborator, or the run comes from a fork.
        scope: the changed files a scoped run covers; empty for a full run.
    """

    trigger: str
    repository: str
    outsider: bool
    scope: tuple[str, ...] = ()


def verify_signature(secret: bytes, body: bytes, header: str | None) -> bool:
    """Return whether ``header`` is a valid ``sha256=`` HMAC of ``body``.

    Mirrors the ``X-Hub-Signature-256`` scheme GitHub and Gitea use. The
    comparison is constant time; a missing or malformed header is invalid.

    Args:
        secret: the shared webhook secret.
        body: the exact request body bytes the signature covers.
        header: the signature header value, or ``None`` when absent.
    """
    if not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"{SIGNATURE_PREFIX}{digest}", header)


def refetch_required() -> bool:
    """The orchestrator always re-fetches the event by id and acts on the
    fetched data, never on the webhook body."""
    return True


_NAME_CHARACTERS = frozenset(string.ascii_letters + string.digits + "_.-")
_DOT_SEGMENTS = frozenset({".", ".."})


def _repository_name(name: object) -> bool:
    parts = name.split("/") if isinstance(name, str) else []
    return len(parts) == 2 and all(
        part and part not in _DOT_SEGMENTS and set(part) <= _NAME_CHARACTERS
        for part in parts
    )


def _path(kind: str, body: dict) -> str | None:
    repository = body["repository"]
    name = repository["full_name"]
    if not _repository_name(name):
        return None
    action = body.get("action")
    if kind == "workflow_run" and action == "completed":
        return f"/repos/{name}/actions/runs/{int(body['workflow_run']['id'])}"
    if kind == "issues" and action == "opened":
        return f"/repos/{name}/issues/{int(body['issue']['number'])}"
    if kind == "pull_request" and action == "opened":
        return f"/repos/{name}/pulls/{int(body['pull_request']['number'])}"
    if kind == "dependabot_alert" and action == "created":
        return f"/repos/{name}/dependabot/alerts/{int(body['alert']['number'])}"
    if (
        kind == "push"
        and body.get("ref") == f"refs/heads/{repository['default_branch']}"
        and COMMIT.fullmatch(body["after"])
    ):
        return f"/repos/{name}/commits/{body['after']}"
    return None


def refetch_path(kind: str, body: dict) -> str | None:
    """Return the GitHub API path that re-fetches the object a webhook names,
    or ``None`` for an event the orchestrator does not act on. Only ids are
    read from the body; every fact a trigger decides on comes from the fetch.

    Args:
        kind: the ``X-GitHub-Event`` header.
        body: the parsed, signature-checked webhook body.
    """
    try:
        return _path(kind, body)
    except (KeyError, TypeError, ValueError):
        return None


def _repository_of(path: str) -> str:
    return "/".join(path.split("/")[2:4])


def classify(kind: str, path: str, fetched: dict) -> Event | None:
    """Return the trigger the re-fetched object raises, or ``None``.

    A run counts as an outsider's when its head repository is not the
    repository itself (a fork pull request run); an issue or pull request
    when its author is no owner, member or collaborator, or its head is a
    fork.

    Args:
        kind: the ``X-GitHub-Event`` header the path was built for.
        path: the API path ``refetch_path`` returned.
        fetched: the object the provider's API returned for ``path``.
    """
    repository = _repository_of(path)
    trusted = fetched.get("author_association") in TRUSTED_ASSOCIATIONS
    if kind == "workflow_run":
        if fetched.get("conclusion") != "failure":
            return None
        head = (fetched.get("head_repository") or {}).get("full_name")
        return Event("workflow_run_failed", repository, head != repository)
    if kind == "issues":
        if "pull_request" in fetched or fetched.get("state") != "open":
            return None
        return Event("issue_opened", repository, not trusted)
    if kind == "pull_request":
        fork = bool(((fetched.get("head") or {}).get("repo") or {}).get("fork"))
        return Event("pull_request_opened", repository, fork or not trusted)
    if kind == "dependabot_alert":
        if fetched.get("state") != "open":
            return None
        return Event("security_alert", repository, False)
    if kind == "push":
        changed = sorted(
            entry["filename"]
            for entry in fetched.get("files") or []
            if MANIFEST.search(entry.get("filename") or "")
        )
        if not changed:
            return None
        return Event("dependency_manifest_changed", repository, False, tuple(changed))
    return None


def intake(
    kind: str,
    body: dict,
    fetch: Callable[[str], dict],
) -> Event | None:
    """Re-fetch the object a signature-checked, fresh webhook names and
    return the trigger it raises.

    Args:
        kind: the ``X-GitHub-Event`` header.
        body: the parsed webhook body.
        fetch: GETs an API path from the provider and returns the JSON.
    """
    path = refetch_path(kind, body)
    if path is None:
        return None
    return classify(kind, path, fetch(path))


class Deduplicator:
    """Drop a repeated webhook delivery id.

    The deployed orchestrator keeps the seen ids in Postgres; this in-memory
    implementation is the contract and the test double. ``seen`` returns True
    the first time it sees an id (accept) and False on a repeat (drop).
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, delivery_id: str) -> bool:
        if delivery_id in self._seen:
            return False
        self._seen.add(delivery_id)
        return True


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    secret = b"s3cr3t"
    body = b'{"action":"opened"}'
    good = f"{SIGNATURE_PREFIX}{hmac.new(secret, body, hashlib.sha256).hexdigest()}"
    _expect(verify_signature(secret, body, good), "valid signature rejected")
    _expect(not verify_signature(secret, body + b"x", good), "tampered body accepted")
    _expect(not verify_signature(b"wrong", body, good), "wrong secret accepted")
    _expect(not verify_signature(secret, body, None), "missing header accepted")
    _expect(not verify_signature(secret, body, "md5=deadbeef"), "wrong scheme accepted")
    dedup = Deduplicator()
    _expect(dedup.seen("d1") and not dedup.seen("d1"), "delivery id not deduplicated")
    _expect(dedup.seen("d2"), "distinct id dropped")
    _expect(refetch_required(), "refetch not required")
    print("orchestrator webhook self-check ok")


if __name__ == "__main__":
    _demo()
