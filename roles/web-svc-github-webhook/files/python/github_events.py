"""Reduce GitHub webhook payloads to the flat, allowlisted fields the receiver logs."""

MAX_COMMITS = 50
WORKFLOW_PREFIX = ".github/workflows/"


def flag(value):
    return "true" if value else "false"


def workflow_paths(payload):
    paths = set()
    for commit in payload.get("commits") or []:
        for key in ("added", "modified", "removed"):
            paths.update(
                p for p in commit.get(key) or [] if p.startswith(WORKFLOW_PREFIX)
            )
    return ",".join(sorted(paths))


def default_branch(payload):
    """Return the default branch of the payload's repository, e.g. ``main``; empty when the payload has no repository."""
    return str((payload.get("repository") or {}).get("default_branch") or "")


def event_record(event, payload):
    """Reduce a webhook payload to the logged fields.

    Args:
        event: the X-GitHub-Event header.
        payload: the decoded JSON body; for an organization webhook it can come from any repository of the organization.

    Returns:
        A flat dict of strings; keys start with ``gh_`` so they never collide with Wazuh's static fields.
        Branch events carry the repository's default branch and whether the event hit it.
    """
    branch = default_branch(payload)
    default_ref = "refs/heads/" + branch if branch else ""
    record = {
        "gh_event": event,
        "gh_action": str(payload.get("action") or ""),
        "gh_repo": str((payload.get("repository") or {}).get("full_name") or ""),
        "gh_sender": str((payload.get("sender") or {}).get("login") or ""),
    }
    if event == "push":
        ref = str(payload.get("ref") or "")
        record.update(
            gh_ref=ref,
            gh_default_branch=branch,
            gh_on_default_branch=flag(bool(default_ref) and ref == default_ref),
            gh_forced=flag(payload.get("forced")),
            gh_deleted=flag(payload.get("deleted")),
            gh_created=flag(payload.get("created")),
            gh_before=str(payload.get("before") or ""),
            gh_after=str(payload.get("after") or ""),
            gh_workflow_paths=workflow_paths(payload),
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
    """Return the SHAs a push brought to the branch, or None when the payload lists too many to check."""
    shas = [
        str(c["id"])
        for c in payload.get("commits") or []
        if c.get("distinct", True) and c.get("id")
    ]
    if len(shas) > MAX_COMMITS:
        return None
    if not shas and payload.get("after"):
        shas = [str(payload["after"])]
    return shas
