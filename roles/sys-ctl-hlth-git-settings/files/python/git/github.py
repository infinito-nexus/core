import hashlib
import hmac
import urllib.parse

from git.core import (
    Api,
    flag,
    push_record,
    repository_path,
    signature_matches,
    workflows_on_pull_request_target,
)
from git.core import pushed_commits as core_pushed_commits

NAME = "github"
API_VERSION = "2022-11-28"
GIT_HOST = "github.com"
WORKFLOW_DIRS = (".github/workflows",)
WORKFLOW_PREFIXES = (".github/workflows/",)
UNSUPPORTED_WEBHOOK_FIELDS = ()


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


def webhook_delivery(headers):
    return headers.get("X-GitHub-Delivery") or ""


def webhook_event(headers, payload):
    return headers.get("X-GitHub-Event") or ""


def webhook_verify(headers, body, secret, now):
    """Return why a delivery's X-Hub-Signature-256 does not hold, None when it does.

    Args:
        headers: the request headers.
        body: the raw request body.
        secret: the shared webhook secret.
        now: the current time; unused, GitHub signs no timestamp.
    """
    header = headers.get("X-Hub-Signature-256")
    if not header:
        return "unsigned"
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not header.startswith("sha256=") or not signature_matches(expected, header):
        return "signature"
    return None


def payload_default_branch(payload):
    return str((payload.get("repository") or {}).get("default_branch") or "")


def webhook_record(event, payload):
    """Reduce a GitHub webhook payload to the shared, allowlisted fields.

    Args:
        event: the X-GitHub-Event header.
        payload: the decoded JSON body; for an organization webhook it can come from any repository of the organization.

    Returns:
        A flat dict of strings; keys start with ``gh_`` so they never collide with Wazuh's static fields.
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
                flag(payload.get("forced")),
                payload.get("commits"),
                WORKFLOW_PREFIXES,
            ),
            gh_deleted=flag(payload.get("deleted")),
            gh_created=flag(payload.get("created")),
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
    elif event == "branch_protection_rule":
        record.update(gh_rule_name=str((payload.get("rule") or {}).get("name") or ""))
    elif event == "repository_ruleset":
        ruleset = payload.get("repository_ruleset") or {}
        record.update(
            gh_rule_name=str(ruleset.get("name") or ""),
            gh_enforcement=str(ruleset.get("enforcement") or ""),
        )
    elif event == "member":
        permission = ((payload.get("changes") or {}).get("permission") or {}).get(
            "to"
        ) or ""
        record.update(
            gh_member=str((payload.get("member") or {}).get("login") or ""),
            gh_permission=str(permission),
        )
    elif event == "organization":
        membership = payload.get("membership") or {}
        record.update(
            gh_member=str((membership.get("user") or {}).get("login") or ""),
            gh_permission=str(membership.get("role") or ""),
        )
    elif event == "deploy_key":
        key = payload.get("key") or {}
        record.update(
            gh_key_title=str(key.get("title") or ""),
            gh_key_read_only=flag(key.get("read_only")),
        )
    elif event == "secret_scanning_alert":
        alert = payload.get("alert") or {}
        record.update(
            gh_alert_number=str(alert.get("number") or ""),
            gh_secret_type=str(alert.get("secret_type") or ""),
            gh_url=str(alert.get("html_url") or ""),
        )
    elif event == "dependabot_alert":
        alert = payload.get("alert") or {}
        advisory = alert.get("security_advisory") or {}
        record.update(
            gh_alert_number=str(alert.get("number") or ""),
            gh_severity=str(advisory.get("severity") or "").lower(),
            gh_package=str(
                ((alert.get("dependency") or {}).get("package") or {}).get("name") or ""
            ),
            gh_url=str(alert.get("html_url") or ""),
        )
    return record


def pushed_commits(payload):
    return core_pushed_commits(payload.get("commits"), payload.get("after"))


def merged_into(api, repo, sha, branch):
    """Return whether a merged pull request into the branch lists the commit.

    Args:
        api: the client.
        repo: ``owner/name``.
        sha: the commit.
        branch: the repository's default branch.
    """
    return any(
        pull.get("merged_at") and (pull.get("base") or {}).get("ref") == branch
        for pull in api.get(f"/repos/{repo}/commits/{sha}/pulls") or []
    )
