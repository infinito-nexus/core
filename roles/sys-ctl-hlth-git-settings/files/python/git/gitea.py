import urllib.parse

from git.core import (
    UNSUPPORTED,
    Api,
    CheckError,
    repository_path,
    workflows_on_pull_request_target,
)

NAME = "gitea"
OWNERS_TEAM = "Owners"
WORKFLOW_DIRS = (".gitea/workflows", ".github/workflows")


def client(api_url, token, timeout, user_agent):
    return Api(
        api_url,
        token,
        timeout,
        {
            "Accept": "application/json",
            "Authorization": f"token {token}",
            "User-Agent": user_agent,
        },
    )


def repository(remote, api_url):
    """Return ``owner/name`` of a remote on the Gitea host that serves the API, None for any other host.

    Args:
        remote: the checkout's origin URL.
        api_url: the API base URL, e.g. ``https://git.example.org/api/v1``; its host is the git host.
    """
    return repository_path(remote, urllib.parse.urlsplit(api_url).hostname or "")


def commit_verification(api, repo, sha):
    """Return whether Gitea verified the commit's signature, and why not.

    Args:
        api: the client.
        repo: ``owner/name``.
        sha: the commit.
    """
    verification = (api.get(f"/repos/{repo}/git/commits/{sha}") or {}).get(
        "commit", {}
    ).get("verification") or {}
    return verification.get("verified") is True, verification.get(
        "reason", "no verification data"
    ) or "no verification data"


def default_branch(api, scope):
    return api.get(f"/repos/{scope}")["default_branch"]


def owners(api, org):
    """Return the members of the organization's Owners team, Gitea's equivalent of organization admins.

    Args:
        api: the client.
        org: the organization.
    """
    team = next(
        (
            team
            for team in api.get_all(f"/orgs/{org}/teams?limit=50")
            if team.get("name") == OWNERS_TEAM
        ),
        None,
    )
    if team is None:
        raise CheckError(f"{org} has no {OWNERS_TEAM} team")
    return sorted(
        member["login"]
        for member in api.get_all(f"/teams/{team['id']}/members?limit=50")
    )


def protection(rules, branch):
    """Return the default branch's protection in the shared field names.

    Args:
        rules: Gitea's branch protection rules of the repository.
        branch: the default branch.
    """
    rule = next(
        (r for r in rules if (r.get("rule_name") or r.get("branch_name")) == branch),
        None,
    )
    if rule is None:
        return {
            "required_signatures": False,
            "required_approving_review_count": 0,
            "require_code_owner_review": UNSUPPORTED,
            "dismiss_stale_reviews": False,
            "force_push_blocked": False,
            "deletion_blocked": False,
        }
    return {
        "required_signatures": bool(rule.get("require_signed_commits")),
        "required_approving_review_count": int(rule.get("required_approvals") or 0),
        "require_code_owner_review": UNSUPPORTED,
        "dismiss_stale_reviews": bool(rule.get("dismiss_stale_approvals")),
        "force_push_blocked": not rule.get("enable_force_push"),
        "deletion_blocked": True,
    }


def collaborators(api, scope):
    return {
        user["login"]: api.get(
            f"/repos/{scope}/collaborators/{urllib.parse.quote(user['login'])}/permission"
        )["permission"]
        for user in api.get_all(f"/repos/{scope}/collaborators?limit=50")
    }


def collectors(api, scope, branch):
    """Return the expected-file key to a function reading its current value, or UNSUPPORTED where Gitea has no such setting.

    Args:
        api: the client.
        scope: ``org/repo``.
        branch: the repository's default branch.
    """
    return {
        "branch_protection": lambda: protection(
            api.get_all(f"/repos/{scope}/branch_protections"), branch
        ),
        "collaborators": lambda: collaborators(api, scope),
        "deploy_keys": lambda: [
            {"id": key["id"], "title": key["title"], "read_only": key["read_only"]}
            for key in api.get_all(f"/repos/{scope}/keys?limit=50")
        ],
        "actions": UNSUPPORTED,
        "pull_request_target": lambda: workflows_on_pull_request_target(
            api, scope, branch, WORKFLOW_DIRS
        ),
        "open_secret_scanning_alerts": UNSUPPORTED,
        "open_dependabot_alerts": UNSUPPORTED,
    }
