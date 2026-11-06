#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from git.core import CheckError, emit, provider, read_token

USER_AGENT = "infinito-deployed-code"
MAX_VALUE = 300
MAX_MODIFIED = 50
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


class Forge:
    """One provider's adapter and API client, as a checkout's signature check uses them.

    Args:
        name: the provider, one of git_core.PROVIDERS.
        settings: its ``api_url`` and ``token_file``; an empty API URL means the provider is not configured on this host.
        timeout: seconds per API request.
    """

    def __init__(self, name, settings, timeout):
        self.name = name
        self.adapter = provider(name)
        self.api_url = settings.get("api_url") or ""
        token_file = settings.get("token_file") or ""
        token = (
            read_token(token_file) if token_file and Path(token_file).exists() else ""
        )
        self.api = (
            self.adapter.client(self.api_url, token, timeout, USER_AGENT)
            if self.api_url
            else None
        )


def check_signature(git, checkout, commit, forge):
    if forge.api is None:
        raise CheckError(f"no {forge.name} API URL is configured")
    if not forge.api.token:
        raise CheckError(f"the {forge.name} token file is empty")
    url = git.out("config", "--get", "remote.origin.url")
    repo = forge.adapter.repository(url, forge.api_url)
    if not repo:
        raise CheckError(f"origin {url.strip()} is not a {forge.name} repository")
    verified, reason = forge.adapter.commit_verification(forge.api, repo, commit)
    if verified:
        return []
    return [finding("unverified", checkout, commit=commit, reason=reason)]


def check_checkout(checkout, forge, timeout):
    """Return the findings and failed checks of one checkout.

    Args:
        checkout: the checkout's path.
        forge: the provider the checkout's origin lives on.
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
        events += check_signature(git, checkout, commit, forge)
    except CheckError as failure:
        events.append(
            finding(
                "error", checkout, check="verification", commit=commit, reason=failure
            )
        )
    return events


def run(config, timeout):
    """Return every finding and failed check of every checkout, then the run summary.

    Args:
        config: ``checkouts`` (each a ``path`` and its ``provider``) and ``providers`` (each an ``api_url`` and ``token_file``).
        timeout: seconds per git command and API request.
    """
    checkouts = config["checkouts"]
    forges = {}
    events = []
    for checkout in checkouts:
        name = checkout.get("provider") or ""
        try:
            if name not in forges:
                forges[name] = Forge(name, config["providers"].get(name) or {}, timeout)
        except (CheckError, ValueError) as failure:
            events.append(
                finding("error", checkout["path"], check="provider", reason=failure)
            )
            continue
        events += check_checkout(checkout["path"], forges[name], timeout)
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
        "--config",
        required=True,
        help="JSON file with the checkouts (path, provider) and the providers (api_url, token_file)",
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
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    emit(args.tag, run(config, args.timeout), "dc_kind")


if __name__ == "__main__":
    main()
