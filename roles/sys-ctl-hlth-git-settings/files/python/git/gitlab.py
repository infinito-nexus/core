import base64
import binascii
import hashlib
import hmac
import urllib.parse

from git.core import (
    UNSUPPORTED,
    Api,
    push_record,
    repository_path,
    signature_matches,
)
from git.core import pushed_commits as core_pushed_commits

NAME = "gitlab"
SIGNING_PREFIX = "whsec_"
MAX_SKEW_SECONDS = 300
WORKFLOW_PREFIXES = (".gitlab-ci.yml", ".gitlab/ci/")
EVENTS = {"Push Hook": "push", "Member Hook": "organization"}
MEMBER_ACTIONS = {
    "user_add_to_group": "member_added",
    "user_update_for_group": "member_added",
}
UNSUPPORTED_WEBHOOK_FIELDS = (
    "push.forced",
    "branch_protection_rule",
    "repository_ruleset",
    "member",
    "deploy_key",
    "secret_scanning_alert",
    "dependabot_alert",
)
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


def webhook_delivery(headers):
    return headers.get("webhook-id") or headers.get("Idempotency-Key") or ""


def webhook_event(headers, payload):
    name = headers.get("X-Gitlab-Event") or ""
    return EVENTS.get(name, name.lower().replace(" hook", "").replace(" ", "_"))


def signing_key(secret):
    """Return the HMAC key of a GitLab signing token, which is base64 behind the ``whsec_`` prefix.

    Args:
        secret: the signing token as GitLab shows it.
    """
    try:
        return base64.b64decode(secret.removeprefix(SIGNING_PREFIX), validate=True)
    except (binascii.Error, ValueError):
        return b""


def webhook_verify(headers, body, secret, now):
    """Return why a delivery's webhook-signature does not hold, None when it does.

    Args:
        headers: the request headers.
        body: the raw request body.
        secret: the webhook's signing token; a delivery with only the plain X-Gitlab-Token is refused.
        now: the current time, so a delivery signed too long ago counts as a replay.
    """
    header = headers.get("webhook-signature") or ""
    message_id = headers.get("webhook-id") or ""
    timestamp = headers.get("webhook-timestamp") or ""
    if not header:
        return "unsigned"
    key = signing_key(secret)
    if not key or not message_id or not timestamp.isdigit():
        return "signature"
    signed = f"{message_id}.{timestamp}.".encode() + body
    expected = (
        "v1,"
        + base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    )
    if not any(signature_matches(expected, part) for part in header.split()):
        return "signature"
    if abs(now - int(timestamp)) > MAX_SKEW_SECONDS:
        return "replay"
    return None


def payload_default_branch(payload):
    return str((payload.get("project") or {}).get("default_branch") or "")


def webhook_record(event, payload):
    """Reduce a GitLab webhook payload to the shared, allowlisted fields.

    Args:
        event: the shared event name derived from X-Gitlab-Event.
        payload: the decoded JSON body.
    """
    project = payload.get("project") or {}
    record = {
        "gh_provider": NAME,
        "gh_event": event,
        "gh_action": "",
        "gh_repo": str(project.get("path_with_namespace") or ""),
        "gh_sender": str(payload.get("user_username") or ""),
    }
    if event == "push":
        record.update(
            push_record(
                event,
                str(payload.get("ref") or ""),
                str(payload.get("before") or ""),
                str(payload.get("after") or ""),
                payload_default_branch(payload),
                "unsupported",
                payload.get("commits"),
                WORKFLOW_PREFIXES,
            )
        )
    elif event == "organization":
        record.update(
            gh_action=MEMBER_ACTIONS.get(
                str(payload.get("event_name") or ""),
                str(payload.get("event_name") or ""),
            ),
            gh_repo=str(payload.get("group_path") or ""),
            gh_member=str(payload.get("user_username") or ""),
            gh_permission=str(payload.get("group_access") or "").lower(),
        )
    return record


def pushed_commits(payload):
    return core_pushed_commits(payload.get("commits"), payload.get("after"))


def merged_into(api, repo, sha, branch):
    """Return whether a merged merge request into the branch contains the commit.

    Args:
        api: the client.
        repo: ``group/project``.
        sha: the commit.
        branch: the project's default branch.
    """
    return any(
        request.get("state") == "merged" and request.get("target_branch") == branch
        for request in api.get_all(
            f"/projects/{project(repo)}/repository/commits/{sha}/merge_requests"
        )
    )
