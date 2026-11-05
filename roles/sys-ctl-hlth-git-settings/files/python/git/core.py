import base64
import hmac
import importlib
import ipaddress
import json
import re
import syslog
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROVIDERS = ("github", "gitea", "gitlab")
NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')
PRT_KEY = re.compile(r"""^\s*(?:-\s*)?["']?pull_request_target["']?\s*:?\s*$""")
PRT_INLINE = re.compile(r"""^\s*["']?on["']?\s*:.*\bpull_request_target\b""")
UNSUPPORTED = object()
MAX_COMMITS = 50
ZERO_SHA = "0" * 40


class CheckError(Exception):
    pass


def provider(name):
    """Return the adapter module of a git provider.

    Args:
        name: one of PROVIDERS.

    Raises:
        CheckError: the name is not a known provider.
    """
    if name not in PROVIDERS:
        raise CheckError(f"unknown git provider {name!r}")
    return importlib.import_module(f"git.{name}")


def allowed_url(url):
    """Return whether a URL may be opened: https, or plain http only to a loopback or dotless container-internal host, where the tests run their API stub.

    Args:
        url: the URL, configured or taken from a Link header.
    """
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    try:
        internal = ipaddress.ip_address(host).is_loopback
    except ValueError:
        internal = host == "localhost" or (host != "" and "." not in host)
    return parts.scheme == "https" or (parts.scheme == "http" and internal)


def failure_reason(status, body, headers):
    """Return why an API call failed, naming the rate limit when it is the cause.

    Args:
        status: the HTTP status.
        body: the response body.
        headers: the response headers, None when there were none.
    """
    try:
        message = str(json.loads(body).get("message", ""))
    except (ValueError, AttributeError):
        message = ""
    headers = headers or {}
    remaining = headers.get("X-RateLimit-Remaining") or headers.get(
        "RateLimit-Remaining"
    )
    if status == 429 or (
        status == 403 and (remaining == "0" or "rate limit" in message.lower())
    ):
        reset = (
            headers.get("X-RateLimit-Reset")
            or headers.get("RateLimit-Reset")
            or "unknown"
        )
        return f"HTTP {status}: rate limit exceeded, resets at epoch {reset}"
    return f"HTTP {status}: {message or 'no message'}"


def read_token(path):
    """Return the token stored in a file, without surrounding whitespace.

    Args:
        path: the token file.
    """
    return Path(path).read_text(encoding="utf-8").strip()


def emit(tag, events, kind_key):
    """Log each event as one JSON line to syslog under the tag, and print it.

    Args:
        tag: the syslog identifier the Wazuh agent collects.
        events: the event dicts, in order.
        kind_key: the key whose value ``run`` marks the run summary, logged as info; every other event is a warning.
    """
    syslog.openlog(ident=tag, facility=syslog.LOG_DAEMON)
    for event in events:
        line = json.dumps(event)
        syslog.syslog(
            syslog.LOG_INFO if event[kind_key] == "run" else syslog.LOG_WARNING, line
        )
        print(line)


class Api:
    """A read-only JSON client of one provider's REST API.

    Args:
        base_url: the API base URL.
        token: the read-only token; empty when none is configured.
        timeout: seconds per request.
        headers: the request headers the provider's adapter builds, including its authorization.
    """

    def __init__(self, base_url, token, timeout, headers):
        if not allowed_url(base_url):
            raise ValueError(
                f"refusing API URL {base_url}: https is required outside loopback and container-internal hosts"
            )
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.headers = headers

    def _open(self, url):
        if not allowed_url(url):
            raise CheckError(f"refusing to open {url}: not https")
        request = urllib.request.Request(url, headers=self.headers)  # noqa: S310 - allowed_url admits only https, or http to a loopback or container-internal stub
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - scheme checked by allowed_url
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers
        except (urllib.error.URLError, OSError) as error:
            raise CheckError(
                f"API unreachable: {getattr(error, 'reason', error)}"
            ) from error

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


def workflows_on_pull_request_target(api, scope, branch, directories):
    """Return the workflow files on a branch that run on pull_request_target, through a GitHub-style contents API.

    Args:
        api: the client; GitHub and Gitea serve the same contents API shape.
        scope: ``owner/repo``.
        branch: the default branch.
        directories: the workflow directories the provider reads, in order.
    """
    ref = urllib.parse.quote(branch, safe="")
    paths = []
    for directory in directories:
        entries = (
            api.get(f"/repos/{scope}/contents/{directory}?ref={ref}", missing_ok=True)
            or []
        )
        for entry in entries:
            if entry.get("type") != "file" or not entry["name"].endswith(
                (".yml", ".yaml")
            ):
                continue
            content = api.get(
                f"/repos/{scope}/contents/{urllib.parse.quote(entry['path'])}?ref={ref}"
            )
            if uses_pull_request_target(
                base64.b64decode(content.get("content") or "").decode(
                    "utf-8", "replace"
                )
            ):
                paths.append(entry["path"])
    return paths


def flag(value):
    return "true" if value else "false"


def signature_matches(expected, received):
    return hmac.compare_digest(expected.encode(), received.encode())


def workflow_paths(commits, prefixes):
    """Return the CI workflow files a push added, changed or removed, comma-joined and sorted.

    Args:
        commits: the push payload's commits, each with added, modified and removed path lists.
        prefixes: the paths, or path prefixes, the provider runs CI workflows from.
    """
    paths = set()
    for commit in commits or []:
        for key in ("added", "modified", "removed"):
            paths.update(
                path for path in commit.get(key) or [] if path.startswith(prefixes)
            )
    return ",".join(sorted(paths))


def pushed_commits(commits, after):
    """Return the SHAs a push brought to the branch, or None when the payload lists too many to check.

    Args:
        commits: the push payload's commits; a commit marked ``distinct: false`` was already on another branch.
        after: the branch head after the push, checked when the payload lists no commit.
    """
    shas = [
        str(commit["id"])
        for commit in commits or []
        if commit.get("distinct", True) and commit.get("id")
    ]
    if len(shas) > MAX_COMMITS:
        return None
    if not shas and after and after != ZERO_SHA:
        shas = [str(after)]
    return shas


def push_record(event, ref, before, after, default_branch, forced, commits, prefixes):
    """Return the shared fields of a push, whichever provider sent it.

    Args:
        event: the shared event name, ``push``.
        ref: the pushed ref, e.g. ``refs/heads/main``.
        before: the branch head before the push.
        after: the branch head after the push; all zeros for a deleted branch.
        default_branch: the repository's default branch, empty when the payload has none.
        forced: ``true``, ``false``, or ``unsupported`` when the provider does not report force pushes.
        commits: the payload's commits.
        prefixes: the provider's workflow paths.
    """
    default_ref = "refs/heads/" + default_branch if default_branch else ""
    return {
        "gh_ref": ref,
        "gh_default_branch": default_branch,
        "gh_on_default_branch": flag(bool(default_ref) and ref == default_ref),
        "gh_forced": forced,
        "gh_deleted": flag(after == ZERO_SHA),
        "gh_created": flag(before == ZERO_SHA),
        "gh_before": before,
        "gh_after": after,
        "gh_workflow_paths": workflow_paths(commits, prefixes),
        "gh_event": event,
    }


def repository_path(url, host):
    """Return the ``owner/name`` path of a git remote on the given host, None when the remote is elsewhere.

    Args:
        url: the remote URL, https, scp-like or ssh.
        host: the provider's git host, e.g. ``github.com``.
    """
    pattern = re.compile(
        rf"^(?:https://(?:[^@/]+@)?{re.escape(host)}/|git@{re.escape(host)}:|ssh://git@{re.escape(host)}(?::\d+)?/)(.+?)(?:\.git)?/?$"
    )
    match = pattern.match(url.strip())
    return match.group(1) if match and "/" in match.group(1) else None
