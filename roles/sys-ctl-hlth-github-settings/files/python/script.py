#!/usr/bin/env python3
import argparse
import base64
import json
import re
import syslog
import urllib.error
import urllib.parse
import urllib.request

API_VERSION = "2022-11-28"
ABSENT = "absent"
MAX_VALUE = 300
NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')
WORKFLOW_DIR = ".github/workflows"
PRT_KEY = re.compile(r"""^\s*(?:-\s*)?["']?pull_request_target["']?\s*:?\s*$""")
PRT_INLINE = re.compile(r"""^\s*["']?on["']?\s*:.*\bpull_request_target\b""")


class CheckError(Exception):
    pass


class Api:
    def __init__(self, base_url, token, timeout):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _open(self, url):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "infinito-github-settings",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers
        except (urllib.error.URLError, OSError) as error:
            raise CheckError(f"GitHub API unreachable: {getattr(error, 'reason', error)}") from error

    def _get(self, url, missing_ok):
        status, body, headers = self._open(url)
        if status == 404 and missing_ok:
            return None, headers
        if status != 200:
            raise CheckError(failure_reason(status, body, headers))
        try:
            return json.loads(body or b"null"), headers
        except ValueError as error:
            raise CheckError(f"HTTP {status}: not JSON") from error

    def get(self, path, missing_ok=False):
        return self._get(self.base_url + path, missing_ok)[0]

    def get_all(self, path):
        items = []
        url = self.base_url + path
        while url:
            page, headers = self._get(url, False)
            if not isinstance(page, list):
                raise CheckError(f"{path}: expected a list")
            items.extend(page)
            match = NEXT_LINK.search(headers.get("Link", "") if headers else "")
            url = match.group(1) if match else None
        return items


def failure_reason(status, body, headers):
    """Return why a GitHub API call failed, naming the rate limit when it is the cause.

    Args:
        status: the HTTP status.
        body: the response body.
        headers: the response headers, None when there were none.
    """
    try:
        message = str(json.loads(body).get("message", ""))
    except (ValueError, AttributeError):
        message = ""
    remaining = headers.get("X-RateLimit-Remaining") if headers else None
    if status == 429 or (status == 403 and (remaining == "0" or "rate limit" in message.lower())):
        reset = headers.get("X-RateLimit-Reset", "unknown") if headers else "unknown"
        return f"HTTP {status}: rate limit exceeded, resets at epoch {reset}"
    return f"HTTP {status}: {message or 'no message'}"


def text(value):
    if value is None:
        return ABSENT
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)[:MAX_VALUE]


def drift(scope, check, expected, actual, extra=False):
    """Return one drift event per field whose actual value differs from the expected one.

    Args:
        scope: ``org`` or ``org/repo`` the fields belong to.
        check: the check's name.
        expected: field to expected value.
        actual: field to actual value; a missing field is ``absent``.
        extra: also report fields that are only in ``actual``.
    """
    fields = sorted(set(expected) | (set(actual) if extra else set()))
    events = []
    for field in fields:
        want, have = text(expected.get(field)), text(actual.get(field))
        if want != have:
            events.append(
                {"gs_kind": "drift", "gs_scope": scope, "gs_check": check, "gs_field": str(field), "gs_expected": want, "gs_actual": have}
            )
    return events


def error(scope, check, reason):
    return {"gs_kind": "error", "gs_scope": scope, "gs_check": check, "gs_reason": str(reason)[:MAX_VALUE]}


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
        "required_signatures": enabled("required_signatures") or "required_signatures" in by_type,
        "required_approving_review_count": max(
            int(reviews.get("required_approving_review_count") or 0),
            int(ruleset_reviews.get("required_approving_review_count") or 0),
        ),
        "require_code_owner_review": bool(reviews.get("require_code_owner_reviews"))
        or bool(ruleset_reviews.get("require_code_owner_review")),
        "dismiss_stale_reviews": bool(reviews.get("dismiss_stale_reviews"))
        or bool(ruleset_reviews.get("dismiss_stale_reviews_on_push")),
        "force_push_blocked": (bool(classic) and not enabled("allow_force_pushes")) or "non_fast_forward" in by_type,
        "deletion_blocked": (bool(classic) and not enabled("allow_deletions")) or "deletion" in by_type,
    }


def uses_pull_request_target(workflow):
    """Return whether a workflow file is triggered by pull_request_target.

    Args:
        workflow: the workflow file's text.
    """
    for line in workflow.splitlines():
        code = line.split("#", 1)[0].rstrip()
        if PRT_KEY.match(code) or PRT_INLINE.match(code):
            return True
    return False


def current_owners(api, org):
    return sorted(member["login"] for member in api.get_all(f"/orgs/{org}/members?role=admin&per_page=100"))


def collectors(api, scope, branch):
    """Return the expected-file key to a function reading its current value, in expected-file order.

    Args:
        api: the GitHub API client.
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
            user["login"]: user["role_name"] for user in api.get_all(f"/repos/{scope}/collaborators?affiliation=direct&per_page=100")
        },
        "deploy_keys": lambda: [
            {"id": key["id"], "title": key["title"], "read_only": key["read_only"]} for key in api.get_all(f"/repos/{scope}/keys?per_page=100")
        ],
        "actions": lambda: {
            key: value
            for key, value in {**api.get(f"/repos/{scope}/actions/permissions"), **api.get(f"/repos/{scope}/actions/permissions/workflow")}.items()
            if not key.endswith("_url")
        },
        "pull_request_target": lambda: workflows_on_pull_request_target(api, scope, branch),
        "open_secret_scanning_alerts": lambda: len(api.get_all(f"/repos/{scope}/secret-scanning/alerts?state=open&per_page=100")),
        "open_dependabot_alerts": lambda: len(api.get_all(f"/repos/{scope}/dependabot/alerts?state=open&per_page=100")),
    }


CHECK_NAMES = {"open_secret_scanning_alerts": "secret_scanning", "open_dependabot_alerts": "dependabot"}
EXTRA_FIELDS = ("collaborators", "deploy_keys", "pull_request_target")


def fields(key, value):
    """Return an expected-file value as the field to value mapping drift compares.

    Args:
        key: the expected-file key.
        value: its expected or current value.
    """
    if key == "deploy_keys":
        return {str(item["id"]): f"{item['title']} ({'read-only' if item['read_only'] else 'read-write'})" for item in value}
    if key == "pull_request_target":
        return {path: "present" for path in value}
    if key in CHECK_NAMES:
        return {"open_alerts": value}
    return value


def check_org(api, org, expected):
    return drift(org, "owners", {login: "owner" for login in expected["owners"]}, {login: "owner" for login in current_owners(api, org)}, extra=True)


def check_repo(api, scope, expected, branch):
    events = []
    for key, collect in collectors(api, scope, branch).items():
        check = CHECK_NAMES.get(key, key)
        try:
            current = collect()
        except CheckError as failure:
            events.append(error(scope, check, failure))
            continue
        events += drift(scope, check, fields(key, expected[key]), fields(key, current), extra=key in EXTRA_FIELDS)
    return events


def workflows_on_pull_request_target(api, scope, branch):
    ref = urllib.parse.quote(branch, safe="")
    entries = api.get(f"/repos/{scope}/contents/{WORKFLOW_DIR}?ref={ref}", missing_ok=True) or []
    paths = []
    for entry in entries:
        if entry.get("type") != "file" or not entry["name"].endswith((".yml", ".yaml")):
            continue
        content = api.get(f"/repos/{scope}/contents/{urllib.parse.quote(entry['path'])}?ref={ref}")
        if uses_pull_request_target(base64.b64decode(content.get("content", "")).decode("utf-8", "replace")):
            paths.append(entry["path"])
    return paths


def run(api, expected):
    """Return every drift and failure event of one check run, then the run summary.

    Args:
        api: the GitHub API client.
        expected: the parsed expected state.
    """
    org = expected["organization"]
    events = []
    if not api.token:
        events.append(error(org, "token", "the token file is empty"))
    else:
        try:
            events += check_org(api, org, expected)
        except CheckError as failure:
            events.append(error(org, "owners", failure))
        for name, repo_expected in sorted(expected["repositories"].items()):
            scope = f"{org}/{name}"
            try:
                branch = api.get(f"/repos/{scope}")["default_branch"]
            except CheckError as failure:
                events.append(error(scope, "repository", failure))
                continue
            events += check_repo(api, scope, repo_expected, branch)
    count = {kind: sum(event["gs_kind"] == kind for event in events) for kind in ("drift", "error")}
    events.append({"gs_kind": "run", "gs_scope": org, "gs_drift": str(count["drift"]), "gs_errors": str(count["error"])})
    return events


def current_state(api, expected):
    """Return the current settings in the expected file's format, for the organization and repositories it lists.

    Args:
        api: the GitHub API client.
        expected: the parsed expected state; only its organization and repository names are read.

    Raises:
        CheckError: any value could not be read, naming every failed check, so no partial state is printed.
    """
    org = expected["organization"]
    if not api.token:
        raise CheckError("token: the token file is empty")
    failures = []
    state = {"organization": org, "owners": [], "repositories": {}}
    try:
        state["owners"] = current_owners(api, org)
    except CheckError as failure:
        failures.append(f"{org} owners: {failure}")
    for name in sorted(expected["repositories"]):
        scope = f"{org}/{name}"
        try:
            branch = api.get(f"/repos/{scope}")["default_branch"]
        except CheckError as failure:
            failures.append(f"{scope} repository: {failure}")
            continue
        repo = state["repositories"][name] = {}
        for key, collect in collectors(api, scope, branch).items():
            try:
                repo[key] = collect()
            except CheckError as failure:
                failures.append(f"{scope} {key}: {failure}")
    if failures:
        raise CheckError("; ".join(failures))
    return state


YAML_PLAIN = re.compile(r"^[A-Za-z_./][A-Za-z0-9_./-]*$")
YAML_WORDS = {"true", "false", "null", "yes", "no", "on", "off", "y", "n", ".inf", ".nan"}


def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value == {}:
        return "{}"
    if value == []:
        return "[]"
    value = str(value)
    return value if YAML_PLAIN.match(value) and value.lower() not in YAML_WORDS else json.dumps(value)


def to_yaml(value, indent=0):
    """Return the lines of a block-style YAML rendering of nested dicts, lists and scalars.

    Args:
        value: a dict or list.
        indent: the nesting level, two spaces each.
    """
    pad = "  " * indent
    lines = []
    for key, item in value.items() if isinstance(value, dict) else enumerate(value):
        nested = isinstance(item, (dict, list)) and item
        if isinstance(value, dict):
            lines.append(f"{pad}{yaml_scalar(key)}:" + ("" if nested else f" {yaml_scalar(item)}"))
            lines += to_yaml(item, indent + 1) if nested else []
        elif isinstance(item, dict) and item:
            first, *rest = to_yaml(item, indent + 1)
            lines += [f"{pad}- {first.strip()}", *rest]
        else:
            lines.append(f"{pad}- {yaml_scalar(item)}")
    return lines


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Compare the GitHub organization and repository settings with their expected state.")
    parser.add_argument("--api-url", required=True, help="GitHub API base URL")
    parser.add_argument("--token-file", required=True, help="file holding the read-only GitHub token")
    parser.add_argument("--expected", required=True, help="the expected state as JSON; --print-current reads only its organization and repository names")
    parser.add_argument("--tag", help="journald tag every event is logged under; required unless --print-current")
    parser.add_argument("--timeout", required=True, type=int, help="seconds per API request")
    parser.add_argument("--print-current", action="store_true", help="print the current settings as expected-file YAML instead of checking")
    args = parser.parse_args(argv)
    if not args.print_current and not args.tag:
        parser.error("--tag is required unless --print-current is set")
    return args


def main():
    args = parse_args()
    with open(args.token_file, encoding="utf-8") as token_file:
        token = token_file.read().strip()
    with open(args.expected, encoding="utf-8") as expected_file:
        expected = json.load(expected_file)
    if args.print_current:
        try:
            state = current_state(Api(args.api_url, token, args.timeout), expected)
        except CheckError as failure:
            raise SystemExit(f"cannot read the current GitHub settings: {failure}") from failure
        print("\n".join(["---", *to_yaml(state)]))
        return
    syslog.openlog(ident=args.tag, facility=syslog.LOG_DAEMON)
    for event in run(Api(args.api_url, token, args.timeout), expected):
        line = json.dumps(event)
        syslog.syslog(syslog.LOG_WARNING if event["gs_kind"] != "run" else syslog.LOG_INFO, line)
        print(line)


if __name__ == "__main__":
    main()
