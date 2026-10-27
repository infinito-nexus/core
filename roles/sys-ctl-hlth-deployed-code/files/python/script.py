#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import re
import subprocess
import syslog
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_VERSION = "2022-11-28"
MAX_VALUE = 300
MAX_MODIFIED = 50
GITHUB_SLUG = re.compile(
    r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$"
)
URL_CREDENTIALS = re.compile(r"//[^/@\s]+@")


class CheckError(Exception):
    pass


def clean(text):
    return URL_CREDENTIALS.sub("//***@", " ".join(str(text).split()))[:MAX_VALUE]


def internal_host(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost" or (host != "" and "." not in host)


def api_base_url(url):
    """Return the GitHub API base URL without its trailing slash, refusing any scheme but https.

    Plain http is accepted only for a loopback or dotless container-internal host, where the tests run their API stub.

    Args:
        url: the configured base URL.

    Raises:
        ValueError: the scheme is neither https nor http to such a host.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" or (
        parts.scheme == "http" and internal_host(parts.hostname or "")
    ):
        return url.rstrip("/")
    raise ValueError(
        f"refusing GitHub API URL {url}: https is required outside loopback and container-internal hosts"
    )


class Api:
    def __init__(self, base_url, token, timeout):
        self.base_url = api_base_url(base_url)
        self.token = token
        self.timeout = timeout

    def get(self, path):
        request = urllib.request.Request(  # noqa: S310 - api_base_url allows only https, or http to a loopback or container-internal stub
            self.base_url + path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "infinito-deployed-code",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - scheme checked by api_base_url
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise CheckError(
                failure_reason(error.code, error.read(), error.headers)
            ) from error
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise CheckError(
                f"GitHub API unreachable: {getattr(error, 'reason', error)}"
            ) from error


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
    if status == 429 or (
        status == 403 and (remaining == "0" or "rate limit" in message.lower())
    ):
        return f"HTTP {status}: rate limit exceeded"
    return f"HTTP {status}: {message or 'no message'}"


class Git:
    def __init__(self, checkout, timeout):
        self.checkout = checkout
        self.timeout = timeout
        stat = Path(checkout).stat()
        self.owner = None if stat.st_uid == os.geteuid() else (stat.st_uid, stat.st_gid)

    def run(self, *args):
        """Run git in the checkout as the checkout's owner, so root never writes into a user's repository.

        Args:
            args: the git arguments.
        """
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": "/nonexistent",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
        switch = (
            {"user": self.owner[0], "group": self.owner[1], "extra_groups": []}
            if self.owner
            else {}
        )
        try:
            return subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={self.checkout}",
                    "-C",
                    self.checkout,
                    *args,
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=self.timeout,
                check=False,
                **switch,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CheckError(f"git {args[0]}: {error}") from error

    def out(self, *args):
        result = self.run(*args)
        if result.returncode != 0:
            raise CheckError(
                f"git {args[0]} failed: {(result.stderr.strip().splitlines() or ['exit ' + str(result.returncode)])[-1]}"
            )
        return result.stdout


def finding(kind, checkout, **fields):
    return {
        "dc_kind": kind,
        "dc_checkout": checkout,
        **{f"dc_{key}": clean(value) for key, value in fields.items()},
    }


def parse_porcelain(output):
    """Return (status, path) of every changed tracked file in ``git status --porcelain=v1 -z`` output.

    Args:
        output: the NUL-separated status output.
    """
    tokens = output.split("\0")
    entries = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        status, path = token[:2], token[3:]
        if status[0] in "RC":
            index += 1
        entries.append((status.strip(), path))
    return entries


def github_slug(url):
    match = GITHUB_SLUG.match(url.strip())
    return match.group(1) if match else None


def check_branch(git, checkout, commit):
    symref = git.out("ls-remote", "--symref", "origin", "HEAD")
    match = re.search(r"^ref: refs/heads/(\S+)\s+HEAD$", symref, re.MULTILINE)
    if not match:
        raise CheckError("origin reports no default branch")
    branch = match.group(1)
    git.out(
        "fetch",
        "--quiet",
        "--no-tags",
        "origin",
        f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
    )
    result = git.run(
        "merge-base", "--is-ancestor", commit, f"refs/remotes/origin/{branch}"
    )
    if result.returncode == 1:
        return [finding("unmerged", checkout, commit=commit, branch=branch)]
    if result.returncode != 0:
        raise CheckError(f"git merge-base failed: {result.stderr.strip()}")
    return []


def check_tree(git, checkout, commit):
    entries = parse_porcelain(
        git.out("status", "--porcelain=v1", "-z", "--untracked-files=no")
    )
    events = [
        finding("modified", checkout, commit=commit, path=path, status=status)
        for status, path in entries[:MAX_MODIFIED]
    ]
    if len(entries) > MAX_MODIFIED:
        events.append(
            finding(
                "modified",
                checkout,
                commit=commit,
                path=f"{len(entries) - MAX_MODIFIED} more files",
                status="+",
            )
        )
    return events


def check_signature(git, checkout, commit, api):
    if not api.token:
        raise CheckError("the token file is empty")
    url = git.out("config", "--get", "remote.origin.url")
    slug = github_slug(url)
    if not slug:
        raise CheckError(f"origin {url.strip()} is not a GitHub repository")
    verification = (api.get(f"/repos/{slug}/commits/{commit}") or {}).get(
        "commit", {}
    ).get("verification") or {}
    if verification.get("verified") is True:
        return []
    return [
        finding(
            "unverified",
            checkout,
            commit=commit,
            reason=verification.get("reason", "no verification data"),
        )
    ]


def check_checkout(checkout, api, timeout):
    """Return the findings and failed checks of one checkout.

    Args:
        checkout: the checkout's path.
        api: the GitHub API client.
        timeout: seconds per git command.
    """
    try:
        git = Git(checkout, timeout)
        commit = git.out("rev-parse", "--verify", "HEAD").strip()
    except (CheckError, OSError) as failure:
        return [finding("error", checkout, check="checkout", reason=failure)]
    events = []
    for name, check in (("fetch", check_branch), ("status", check_tree)):
        try:
            events += check(git, checkout, commit)
        except CheckError as failure:
            events.append(
                finding("error", checkout, check=name, commit=commit, reason=failure)
            )
    try:
        events += check_signature(git, checkout, commit, api)
    except CheckError as failure:
        events.append(
            finding(
                "error", checkout, check="verification", commit=commit, reason=failure
            )
        )
    return events


def run(checkouts, api, timeout):
    """Return every finding and failed check of every checkout, then the run summary.

    Args:
        checkouts: the checkout paths.
        api: the GitHub API client.
        timeout: seconds per git command.
    """
    events = [
        event
        for checkout in checkouts
        for event in check_checkout(checkout, api, timeout)
    ]
    errors = sum(event["dc_kind"] == "error" for event in events)
    events.append(
        {
            "dc_kind": "run",
            "dc_checkouts": str(len(checkouts)),
            "dc_findings": str(len(events) - errors),
            "dc_errors": str(errors),
        }
    )
    return events


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Check that every deployed checkout is a clean, signed commit on its default branch."
    )
    parser.add_argument(
        "--checkout",
        required=True,
        action="append",
        help="a deployed checkout; repeat for several",
    )
    parser.add_argument("--api-url", required=True, help="GitHub API base URL")
    parser.add_argument(
        "--token-file", required=True, help="file holding the read-only GitHub token"
    )
    parser.add_argument(
        "--tag", required=True, help="journald tag every event is logged under"
    )
    parser.add_argument(
        "--timeout",
        required=True,
        type=int,
        help="seconds per git command and API request",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    syslog.openlog(ident=args.tag, facility=syslog.LOG_DAEMON)
    for event in run(
        args.checkout, Api(args.api_url, token, args.timeout), args.timeout
    ):
        line = json.dumps(event)
        syslog.syslog(
            syslog.LOG_WARNING if event["dc_kind"] != "run" else syslog.LOG_INFO, line
        )
        print(line)


if __name__ == "__main__":
    main()
