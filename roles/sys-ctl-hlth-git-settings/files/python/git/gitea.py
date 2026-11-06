import hashlib
import hmac
import urllib.parse

from git.core import (
    UNSUPPORTED,
    Api,
    CheckError,
    flag,
    push_record,
    repository_path,
    signature_matches,
    workflows_on_pull_request_target,
)
from git.core import pushed_commits as core_pushed_commits

NAME = "gitea"
OWNERS_TEAM = "Owners"
WORKFLOW_DIRS = (".gitea/workflows", ".github/workflows")
WORKFLOW_PREFIXES = (".gitea/workflows/", ".github/workflows/")
UNSUPPORTED_WEBHOOK_FIELDS = (
    "push.forced",
    "branch_protection_rule",
    "repository_ruleset",
    "member",
    "organization",
    "deploy_key",
    "secret_scanning_alert",
    "dependabot_alert",
)


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


def webhook_delivery(headers):
    return headers.get("X-Gitea-Delivery") or ""


def webhook_event(headers, payload):
    return headers.get("X-Gitea-Event") or ""


def webhook_verify(headers, body, secret, now):
    """Return why a delivery's X-Gitea-Signature does not hold, None when it does.

    Args:
        headers: the request headers.
        body: the raw request body.
        secret: the shared webhook secret.
        now: the current time; unused, Gitea signs no timestamp.
    """
    header = headers.get("X-Gitea-Signature") or ""
    if not header:
        return "unsigned"
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return None if signature_matches(expected, header) else "signature"


def payload_default_branch(payload):
    return str((payload.get("repository") or {}).get("default_branch") or "")


def webhook_record(event, payload):
    """Reduce a Gitea webhook payload to the shared, allowlisted fields.

    Args:
        event: the X-Gitea-Event header.
        payload: the decoded JSON body.
    """
    branch = payload_default_branch(payload)
    default_ref = "refs/heads/" + branch if branch else ""
    record = {
        "gh_provider": NAME,
        "gh_event": event,
        "gh_action": str(payload.get("action") or ""),
        "gh_repo": str((payload.get("repository") or {}).get("full_name") or ""),
        "gh_sender": str((payload.get("sender") or {}).get("login") or ""),
    }
    if event == "push":
        record.update(
            push_record(
                event,
                str(payload.get("ref") or ""),
                str(payload.get("before") or ""),
                str(payload.get("after") or ""),
                branch,
                "unsupported",
                payload.get("commits"),
                WORKFLOW_PREFIXES,
            )
        )
    elif event == "delete":
        ref = (
            "refs/heads/" + str(payload.get("ref") or "")
            if payload.get("ref_type") == "branch"
            else ""
        )
        record.update(
            gh_ref=ref,
            gh_default_branch=branch,
            gh_on_default_branch=flag(bool(default_ref) and ref == default_ref),
            gh_deleted="true",
        )
    return record


def pushed_commits(payload):
    return core_pushed_commits(payload.get("commits"), payload.get("after"))


def merged_into(api, repo, sha, branch):
    """Return whether the pull request Gitea reports for the commit was merged into the branch.

    Args:
        api: the client.
        repo: ``owner/name``.
        sha: the commit.
        branch: the repository's default branch.
    """
    pull = api.get(f"/repos/{repo}/commits/{sha}/pull", missing_ok=True) or {}
    return bool(pull.get("merged")) and (pull.get("base") or {}).get("ref") == branch
