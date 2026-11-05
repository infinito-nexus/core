import urllib.parse

from git.core import UNSUPPORTED, Api, repository_path

NAME = "gitlab"
OWNER_ACCESS = 50
ACCESS_LEVELS = {
    10: "guest",
    20: "reporter",
    30: "developer",
    40: "maintainer",
    OWNER_ACCESS: "owner",
}


def client(api_url, token, timeout, user_agent):
    return Api(
        api_url,
        token,
        timeout,
        {
            "Accept": "application/json",
            "PRIVATE-TOKEN": token,
            "User-Agent": user_agent,
        },
    )


def project(repo):
    return urllib.parse.quote(repo, safe="")


def repository(remote, api_url):
    """Return the ``group/name`` path of a remote on the GitLab host that serves the API, None for any other host.

    Args:
        remote: the checkout's origin URL.
        api_url: the API base URL, e.g. ``https://gitlab.example.org/api/v4``; its host is the git host.
    """
    return repository_path(remote, urllib.parse.urlsplit(api_url).hostname or "")


def commit_verification(api, repo, sha):
    """Return whether GitLab verified the commit's signature, and why not.

    Args:
        api: the client.
        repo: ``group/name``.
        sha: the commit.
    """
    # Exception: GitLab answers 404 for a commit that carries no signature at all, so a missing signature is a finding, not a failed check.
    signature = api.get(
        f"/projects/{project(repo)}/repository/commits/{sha}/signature",
        missing_ok=True,
    )
    if signature is None:
        return False, "unsigned"
    status = str(signature.get("verification_status") or "unknown")
    return status == "verified", status


def default_branch(api, scope):
    return api.get(f"/projects/{project(scope)}")["default_branch"]


def owners(api, org):
    return sorted(
        member["username"]
        for member in api.get_all(f"/groups/{project(org)}/members?per_page=100")
        if member.get("access_level") == OWNER_ACCESS
    )


def protection(protected, approvals):
    """Return the default branch's protection in the shared field names.

    Args:
        protected: the default branch's protected-branch entry, None when it is unprotected.
        approvals: the project's merge request approval settings, None where the edition has none.
    """
    return {
        "required_signatures": UNSUPPORTED,
        "required_approving_review_count": int(
            approvals.get("approvals_before_merge") or 0
        )
        if approvals
        else UNSUPPORTED,
        "require_code_owner_review": bool(
            (protected or {}).get("code_owner_approval_required")
        ),
        "dismiss_stale_reviews": bool(approvals.get("reset_approvals_on_push"))
        if approvals
        else UNSUPPORTED,
        "force_push_blocked": bool(protected) and not protected.get("allow_force_push"),
        "deletion_blocked": bool(protected),
    }


def collectors(api, scope, branch):
    """Return the expected-file key to a function reading its current value, or UNSUPPORTED where GitLab has no such setting.

    Args:
        api: the client.
        scope: ``group/project``.
        branch: the project's default branch.
    """
    project_id = project(scope)
    return {
        "branch_protection": lambda: protection(
            api.get(
                f"/projects/{project_id}/protected_branches/{urllib.parse.quote(branch, safe='')}",
                missing_ok=True,
            ),
            api.get(f"/projects/{project_id}/approvals", missing_ok=True),
        ),
        "collaborators": lambda: {
            member["username"]: ACCESS_LEVELS.get(
                member["access_level"], str(member["access_level"])
            )
            for member in api.get_all(f"/projects/{project_id}/members?per_page=100")
        },
        "deploy_keys": lambda: [
            {
                "id": key["id"],
                "title": key["title"],
                "read_only": not key.get("can_push"),
            }
            for key in api.get_all(f"/projects/{project_id}/deploy_keys?per_page=100")
        ],
        "actions": UNSUPPORTED,
        "pull_request_target": UNSUPPORTED,
        "open_secret_scanning_alerts": UNSUPPORTED,
        "open_dependabot_alerts": UNSUPPORTED,
    }
