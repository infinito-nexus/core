import urllib.parse

from git.core import Api, repository_path, workflows_on_pull_request_target

NAME = "github"
API_VERSION = "2022-11-28"
GIT_HOST = "github.com"
WORKFLOW_DIRS = (".github/workflows",)


def client(api_url, token, timeout, user_agent):
    return Api(
        api_url,
        token,
        timeout,
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent,
            "X-GitHub-Api-Version": API_VERSION,
        },
    )


def repository(remote, api_url):
    """Return ``owner/name`` of a github.com remote, None for any other host.

    Args:
        remote: the checkout's origin URL.
        api_url: unused; GitHub's git host is fixed.
    """
    return repository_path(remote, GIT_HOST)


def commit_verification(api, repo, sha):
    """Return whether GitHub verified the commit's signature, and why not.

    Args:
        api: the client.
        repo: ``owner/name``.
        sha: the commit.
    """
    verification = (api.get(f"/repos/{repo}/commits/{sha}") or {}).get(
        "commit", {}
    ).get("verification") or {}
    return verification.get("verified") is True, verification.get(
        "reason", "no verification data"
    )


def default_branch(api, scope):
    return api.get(f"/repos/{scope}")["default_branch"]


def owners(api, org):
    return sorted(
        member["login"]
        for member in api.get_all(f"/orgs/{org}/members?role=admin&per_page=100")
    )


def effective_protection(classic, rules):
    """Return the default branch's protection as classic protection and rulesets enforce it together.

    Args:
        classic: the classic branch protection, None when the branch has none.
        rules: the rules every active ruleset applies to the branch.
    """
    classic = classic or {}
    by_type = {rule.get("type"): rule.get("parameters") or {} for rule in rules}
    reviews = classic.get("required_pull_request_reviews") or {}
    ruleset_reviews = by_type.get("pull_request", {})

    def enabled(key):
        return bool((classic.get(key) or {}).get("enabled"))

    return {
        "required_signatures": enabled("required_signatures")
        or "required_signatures" in by_type,
        "required_approving_review_count": max(
            int(reviews.get("required_approving_review_count") or 0),
            int(ruleset_reviews.get("required_approving_review_count") or 0),
        ),
        "require_code_owner_review": bool(reviews.get("require_code_owner_reviews"))
        or bool(ruleset_reviews.get("require_code_owner_review")),
        "dismiss_stale_reviews": bool(reviews.get("dismiss_stale_reviews"))
        or bool(ruleset_reviews.get("dismiss_stale_reviews_on_push")),
        "force_push_blocked": (bool(classic) and not enabled("allow_force_pushes"))
        or "non_fast_forward" in by_type,
        "deletion_blocked": (bool(classic) and not enabled("allow_deletions"))
        or "deletion" in by_type,
    }


def collectors(api, scope, branch):
    """Return the expected-file key to a function reading its current value, in expected-file order.

    Args:
        api: the client.
        scope: ``org/repo``.
        branch: the repository's default branch.
    """
    quoted = urllib.parse.quote(branch, safe="")
    return {
        "branch_protection": lambda: effective_protection(
            api.get(f"/repos/{scope}/branches/{quoted}/protection", missing_ok=True),
            api.get_all(f"/repos/{scope}/rules/branches/{quoted}?per_page=100"),
        ),
        "collaborators": lambda: {
            user["login"]: user["role_name"]
            for user in api.get_all(
                f"/repos/{scope}/collaborators?affiliation=direct&per_page=100"
            )
        },
        "deploy_keys": lambda: [
            {"id": key["id"], "title": key["title"], "read_only": key["read_only"]}
            for key in api.get_all(f"/repos/{scope}/keys?per_page=100")
        ],
        "actions": lambda: {
            key: value
            for key, value in {
                **api.get(f"/repos/{scope}/actions/permissions"),
                **api.get(f"/repos/{scope}/actions/permissions/workflow"),
            }.items()
            if not key.endswith("_url")
        },
        "pull_request_target": lambda: workflows_on_pull_request_target(
            api, scope, branch, WORKFLOW_DIRS
        ),
        "open_secret_scanning_alerts": lambda: len(
            api.get_all(
                f"/repos/{scope}/secret-scanning/alerts?state=open&per_page=100"
            )
        ),
        "open_dependabot_alerts": lambda: len(
            api.get_all(f"/repos/{scope}/dependabot/alerts?state=open&per_page=100")
        ),
    }
