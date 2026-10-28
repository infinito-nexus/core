#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
from pathlib import Path

from github_api import Api, CheckError, emit, read_token

USER_AGENT = "infinito-deployed-code"
MAX_VALUE = 300
MAX_MODIFIED = 50
GITHUB_SLUG = re.compile(
    r"^(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$"
)
URL_CREDENTIALS = re.compile(r"//[^/@\s]+@")


def clean(text):
    return URL_CREDENTIALS.sub("//***@", " ".join(str(text).split()))[:MAX_VALUE]


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
    api = Api(args.api_url, read_token(args.token_file), args.timeout, USER_AGENT)
    emit(args.tag, run(args.checkout, api, args.timeout), "dc_kind")


if __name__ == "__main__":
    main()
