from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from ansible.errors import AnsibleFilterError

RFC3339_NUMERIC_OFFSET = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}"
)
INTEGER = re.compile(r"-?\d+")
FLAGS = {"0": False, "1": True}
ROW_WIDTH = 7
USER_TYPE_BOT = 4
VISIBILITY_PRIVATE = 2
ACCESS_MODES = {0: "none", 1: "read", 2: "write", 3: "admin", 4: "owner"}
ACCESS_READ = 1
DEPLOY_KEY_WRITE = 2
OWNERS_TEAM = "owners"
CODE_UNIT = "repo.code"
MAX_DEPLOY_KEYS = 2
MAX_WRITING_KEYS = 1
UNITS = {
    1: "repo.code",
    2: "repo.issues",
    3: "repo.pulls",
    4: "repo.releases",
    5: "repo.wiki",
    6: "repo.ext_wiki",
    7: "repo.ext_issues",
    8: "repo.projects",
    9: "repo.packages",
    10: "repo.actions",
}


def _int(value: str) -> int:
    if not INTEGER.fullmatch(str(value).strip()):
        raise AnsibleFilterError(f"gitea_workspaces_snapshot: {value!r} is no integer")
    return int(value)


def _flag(value: str) -> bool:
    if str(value).strip() not in FLAGS:
        raise AnsibleFilterError(f"gitea_workspaces_snapshot: {value!r} is no flag")
    return FLAGS[str(value).strip()]


def _empty_snapshot() -> dict[str, Any]:
    return {
        "account": None,
        "organization": None,
        "owned_repositories": [],
        "memberships": [],
        "team_memberships": [],
        "teams": {},
        "repositories": {},
    }


def _team(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    return snapshot["teams"].setdefault(
        name,
        {
            "authorize": 0,
            "includes_all_repositories": False,
            "can_create_org_repo": False,
            "units": {},
            "members": [],
        },
    )


def _repository(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    return snapshot["repositories"].setdefault(
        name, {"deploy_keys": [], "collaborators": []}
    )


def _read_account(snapshot: dict[str, Any], row: list[str]) -> None:
    snapshot["account"] = {
        "type": _int(row[2]),
        "is_admin": _flag(row[3]),
        "max_repo_creation": _int(row[4]),
        "login_source": _int(row[5]),
        "external_logins": _int(row[6]),
    }


def _read_team(snapshot: dict[str, Any], row: list[str]) -> None:
    team = _team(snapshot, row[1])
    team["authorize"] = _int(row[2])
    team["includes_all_repositories"] = _flag(row[3])
    team["can_create_org_repo"] = _flag(row[4])


def _read_team_unit(snapshot: dict[str, Any], row: list[str]) -> None:
    unit = UNITS.get(_int(row[2]), f"unit {row[2]}")
    _team(snapshot, row[1])["units"][unit] = _int(row[3])


def _read_deploy_key(snapshot: dict[str, Any], row: list[str]) -> None:
    _repository(snapshot, row[1])["deploy_keys"].append(
        {"name": row[2], "mode": _int(row[3])}
    )


READERS = {
    "account": _read_account,
    "organization": lambda s, r: s.update(organization={"visibility": _int(r[2])}),
    "owned_repository": lambda s, r: s["owned_repositories"].append(r[1]),
    "membership": lambda s, r: s["memberships"].append(r[1]),
    "team_membership": lambda s, r: s["team_memberships"].append(f"{r[1]}/{r[2]}"),
    "team": _read_team,
    "team_unit": _read_team_unit,
    "team_member": lambda s, r: _team(s, r[1])["members"].append(r[2]),
    "repository": lambda s, r: _repository(s, r[1]),
    "deploy_key": _read_deploy_key,
    "collaborator": lambda s, r: _repository(s, r[1])["collaborators"].append(r[2]),
}


def gitea_workspaces_snapshot(rows: Any) -> dict[str, Any]:
    """
    Args:
        rows: the parsed rows of ``files/sql/workspaces-snapshot.sql``, each a
            list of seven strings whose first one names the kind of object.

    Returns:
        The store account, the workspace organization, the account's own
        repositories, organizations and teams, and the organization's teams
        and repositories with their grants, deploy keys and collaborators.
    """
    snapshot = _empty_snapshot()
    for row in rows or []:
        cells = [str(cell) for cell in row]
        if len(cells) != ROW_WIDTH or cells[0] not in READERS:
            raise AnsibleFilterError(
                f"gitea_workspaces_snapshot: unexpected row {cells!r}"
            )
        READERS[cells[0]](snapshot, cells)
    return snapshot


def _account_origin_findings(account: dict[str, Any], store: str) -> list[str]:
    findings = []
    if account["type"] != USER_TYPE_BOT:
        findings.append(f"account '{store}' is not the bot account the deploy creates")
    if account["login_source"] != 0 or account["external_logins"] > 0:
        findings.append(f"account '{store}' signs in through an external source")
    return findings


def _account_findings(
    snapshot: dict[str, Any], store: str, organization: str
) -> list[str]:
    account = snapshot["account"]
    if account is None:
        return [f"account '{store}' is missing"]
    findings = _account_origin_findings(account, store)
    if account["is_admin"]:
        findings.append(f"account '{store}' is a site admin")
    if account["max_repo_creation"] != 0:
        findings.append(
            f"account '{store}' may create {account['max_repo_creation']} repositories of its own"
        )
    findings += [
        f"account '{store}' owns repository '{store}/{name}'"
        for name in snapshot["owned_repositories"]
    ]
    findings += [
        f"account '{store}' belongs to organization '{name}'"
        for name in snapshot["memberships"]
        if name != organization
    ]
    findings += [
        f"account '{store}' belongs to team '{name}'"
        for name in snapshot["team_memberships"]
        if name != f"{organization}/{OWNERS_TEAM}"
    ]
    return findings


def _owners_findings(
    snapshot: dict[str, Any], store: str, organization: str
) -> list[str]:
    owners = snapshot["teams"].get(OWNERS_TEAM)
    members = owners["members"] if owners else []
    findings = [
        f"team '{organization}/{OWNERS_TEAM}' holds member '{member}'"
        for member in members
        if member != store
    ]
    if store not in members:
        findings.append(f"account '{store}' is not an owner of '{organization}'")
    return findings


def _team_findings(name: str, team: dict[str, Any], organization: str) -> list[str]:
    label = f"team '{organization}/{name}'"
    findings = []
    if team["authorize"] > ACCESS_READ:
        findings.append(
            f"{label} holds '{ACCESS_MODES.get(team['authorize'], team['authorize'])}'"
        )
    if team["includes_all_repositories"]:
        findings.append(f"{label} reaches all repositories")
    if team["can_create_org_repo"]:
        findings.append(f"{label} may create repositories")
    for unit, mode in sorted(team["units"].items()):
        if unit != CODE_UNIT and mode > 0:
            findings.append(f"{label} holds unit '{unit}'")
        if unit == CODE_UNIT and mode > ACCESS_READ:
            findings.append(
                f"{label} holds '{ACCESS_MODES.get(mode, mode)}' on '{unit}'"
            )
    return findings


def _repository_findings(
    name: str, repository: dict[str, Any], organization: str
) -> list[str]:
    label = f"repository '{organization}/{name}'"
    keys = repository["deploy_keys"]
    writing = [key for key in keys if key["mode"] >= DEPLOY_KEY_WRITE]
    findings = []
    if len(keys) > MAX_DEPLOY_KEYS:
        findings.append(f"{label} holds {len(keys)} deploy keys")
    if len(writing) > MAX_WRITING_KEYS:
        findings.append(f"{label} holds {len(writing)} writing deploy keys")
    findings += [
        f"{label} has collaborator '{collaborator}'"
        for collaborator in repository["collaborators"]
    ]
    return findings


def gitea_workspaces_findings(
    snapshot: dict[str, Any], store: str, organization: str
) -> list[str]:
    """
    Args:
        snapshot: the document ``gitea_workspaces_snapshot`` folded.
        store: the name of the store account.
        organization: the name of the workspace organization.

    Returns:
        One sentence per grant wider than the workspace organization allows,
        each naming the object it found on; an empty list for a private
        organization owned by the store bot alone whose teams read code only.
    """
    findings = _account_findings(snapshot, store, organization)
    if snapshot["organization"] is None:
        return [*findings, f"organization '{organization}' is missing"]
    if snapshot["organization"]["visibility"] != VISIBILITY_PRIVATE:
        findings.append(f"organization '{organization}' is not private")
    findings += _owners_findings(snapshot, store, organization)
    for name, team in sorted(snapshot["teams"].items()):
        if name != OWNERS_TEAM:
            findings += _team_findings(name, team, organization)
    for name, repository in sorted(snapshot["repositories"].items()):
        findings += _repository_findings(name, repository, organization)
    return findings


def gitea_workspaces_plan(snapshot: dict[str, Any], store: str) -> dict[str, Any]:
    """
    Args:
        snapshot: the document ``gitea_workspaces_snapshot`` folded.
        store: the name of the store account.

    Returns:
        What the deploy changes to reach the workspace organization:
        ``create_account``, ``align_account``, ``create_organization`` and
        ``privatize_organization`` as booleans, and ``refuse``, the reasons an
        existing account of that name is not the one the deploy created.
    """
    account = snapshot["account"]
    organization = snapshot["organization"]
    return {
        "create_account": account is None,
        "refuse": [] if account is None else _account_origin_findings(account, store),
        "align_account": account is not None
        and (account["is_admin"] or account["max_repo_creation"] != 0),
        "create_organization": organization is None,
        "privatize_organization": organization is not None
        and organization["visibility"] != VISIBILITY_PRIVATE,
    }


def _rfc3339(value: str) -> datetime | None:
    if not RFC3339_NUMERIC_OFFSET.fullmatch(str(value)):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def gitea_store_token_name(prefix: str, expires_at: str) -> str:
    """
    Args:
        prefix: the name prefix every store token shares.
        expires_at: the moment the rotation revokes the token, RFC 3339 with
            a numeric offset.

    Returns:
        The name of the store token: the prefix followed by ``expires_at``.
    """
    if _rfc3339(expires_at) is None:
        raise AnsibleFilterError(
            f"gitea_store_token_name: {expires_at!r} is no RFC 3339 time with a numeric offset"
        )
    return f"{prefix}{expires_at}"


def gitea_store_tokens_expired(tokens: Any, prefix: str, now: str) -> list[int]:
    """
    Args:
        tokens: the token list of ``GET /users/<store>/tokens``.
        prefix: the name prefix every store token shares.
        now: the moment of the run, RFC 3339 with a numeric offset.

    Returns:
        The ids of the tokens named after an ``expires_at`` before ``now``;
        a token of any other name is never listed.
    """
    moment = _rfc3339(now)
    if moment is None:
        raise AnsibleFilterError(
            f"gitea_store_tokens_expired: {now!r} is no RFC 3339 time with a numeric offset"
        )
    expired = []
    for token in tokens or []:
        name = str(token.get("name", ""))
        if not name.startswith(prefix):
            continue
        expires_at = _rfc3339(name[len(prefix) :])
        if expires_at is not None and expires_at < moment:
            expired.append(int(token["id"]))
    return expired


def gitea_api_response(output: str) -> dict[str, Any]:
    """
    Args:
        output: stdout of curl run with ``-w '\\n%{http_code}'``.

    Returns:
        ``status`` as an int and ``json`` as the parsed body, None for an
        empty one.
    """
    body, _, status = str(output).rpartition("\n")
    if not status.strip().isdigit():
        raise AnsibleFilterError(f"gitea_api_response: no HTTP status in {status!r}")
    return {
        "status": int(status),
        "json": json.loads(body) if body.strip() else None,
    }


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "gitea_api_response": gitea_api_response,
            "gitea_store_token_name": gitea_store_token_name,
            "gitea_store_tokens_expired": gitea_store_tokens_expired,
            "gitea_workspaces_findings": gitea_workspaces_findings,
            "gitea_workspaces_plan": gitea_workspaces_plan,
            "gitea_workspaces_snapshot": gitea_workspaces_snapshot,
        }
