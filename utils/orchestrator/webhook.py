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
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.agents.accounts import repository_entry
from utils.digests import COMMIT

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

GITHUB = "github"
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


def served_repositories(agents: Mapping[str, Mapping]) -> frozenset[str]:
    """Return the ``owner/name`` of every GitHub repository an agent role
    lists: an entry naming no account, or one naming a ``github/`` account.

    Args:
        agents: every role's configuration, each with its ``repositories``.

    Raises:
        ValueError: an entry is malformed or has an all-dot segment.
    """
    served = set()
    for agent in agents.values():
        for raw in agent["repositories"]:
            entry = repository_entry(raw)
            account = entry["account"]
            if account is None or account.partition("/")[0] == GITHUB:
                served.add(str(entry["repo"]))
    return frozenset(served)


def _served(name: object, served: Iterable[str]) -> str | None:
    return next((repository for repository in served if repository == name), None)


def _id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{value!r} is no positive integer id")
    return int(value)


def _path(kind: str, body: dict, served: Iterable[str]) -> str | None:
    repository = body["repository"]
    name = _served(repository["full_name"], served)
    if name is None:
        return None
    action = body.get("action")
    if kind == "workflow_run" and action == "completed":
        return f"/repos/{name}/actions/runs/{_id(body['workflow_run']['id'])}"
    if kind == "issues" and action == "opened":
        return f"/repos/{name}/issues/{_id(body['issue']['number'])}"
    if kind == "pull_request" and action == "opened":
        return f"/repos/{name}/pulls/{_id(body['pull_request']['number'])}"
    if kind == "dependabot_alert" and action == "created":
        return f"/repos/{name}/dependabot/alerts/{_id(body['alert']['number'])}"
    if (
        kind == "push"
        and body.get("ref") == f"refs/heads/{repository['default_branch']}"
    ):
        after = body["after"]
        if re.fullmatch(COMMIT, after):
            return f"/repos/{name}/commits/{after}"
    return None


def refetch_path(kind: str, body: dict, served: Iterable[str]) -> str | None:
    """Return the GitHub API path that re-fetches the object a webhook names,
    or ``None`` for an event the orchestrator does not act on. Only ids are
    read from the body; every fact a trigger decides on comes from the fetch.

    Args:
        kind: the ``X-GitHub-Event`` header.
        body: the parsed, signature-checked webhook body.
        served: the ``owner/name`` of every repository the agent roles list;
            a body naming any other is never fetched, and the path carries
            the listed value, not the body's.
    """
    try:
        return _path(kind, body, served)
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
    served: Iterable[str],
) -> Event | None:
    """Re-fetch the object a signature-checked, fresh webhook names and
    return the trigger it raises.

    Args:
        kind: the ``X-GitHub-Event`` header.
        body: the parsed webhook body.
        fetch: GETs an API path from the provider and returns the JSON.
        served: the ``owner/name`` of every repository the agent roles list.
    """
    path = refetch_path(kind, body, served)
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
