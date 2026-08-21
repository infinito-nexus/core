"""Git and ``gh`` plumbing for the CI deploy-run status/trigger commands."""

from __future__ import annotations

import json
import re
import subprocess
import sys


def run_id_from_url(url: str) -> str:
    match = re.search(r"/runs/(\d+)", url)
    if not match:
        raise ValueError(f"no run id found in URL: {url}")
    return match.group(1)


def slug_from_url(url: str) -> str:
    """Extract the ``owner/repo`` slug from a github.com URL (https or ssh)."""
    match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?(?:/|$)", url)
    if not match:
        raise ValueError(f"no owner/repo found in URL: {url}")
    return f"{match.group(1)}/{match.group(2)}"


def _run(args: list[str]) -> str:
    return subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout.strip()


def _branch_remote() -> str:
    """The remote the current branch tracks (e.g. a fork), falling back to
    ``remote.pushDefault``, then 'origin' or the only configured remote."""
    try:
        upstream = _run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
        )
        if "/" in upstream:
            return upstream.split("/", 1)[0]
    except subprocess.CalledProcessError:
        pass
    remotes = _run(["git", "remote"]).split()
    try:
        push_default = _run(["git", "config", "--get", "remote.pushDefault"])
        if push_default in remotes:
            return push_default
    except subprocess.CalledProcessError:
        pass
    if "origin" in remotes:
        return "origin"
    if not remotes:
        raise RuntimeError("no git remote configured")
    return remotes[0]


def resolve_repo() -> str:
    """The ``owner/repo`` the current branch lives on, derived from its
    tracking remote (not gh's default repo, which may be the upstream)."""
    return slug_from_url(_run(["git", "remote", "get-url", _branch_remote()]))


def _gh(args: list[str], repo: str | None = None, check: bool = True) -> str:
    """Run ``gh`` and return its stdout.

    Args:
        args: the ``gh`` arguments, without the ``gh`` itself.
        repo: appended as ``--repo`` when given.
        check: abort the command on a non-zero exit. Pass ``False`` for calls
            whose failure the caller handles, which then yields ``""``.
    """
    cmd = ["gh", *args]
    if repo:
        cmd += ["--repo", repo]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        if not check:
            return ""
        sys.stderr.write(
            proc.stderr or f"gh exited {proc.returncode}: {' '.join(cmd)}\n"
        )
        raise SystemExit(proc.returncode)
    return proc.stdout


def current_branch() -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def fetch_jobs(run_id: str, repo: str | None = None) -> list[dict]:
    return json.loads(_gh(["run", "view", run_id, "--json", "jobs"], repo=repo)).get(
        "jobs", []
    )


def fetch_run(run_id: str, repo: str | None = None) -> dict:
    """Jobs plus the run title, in one ``gh`` call.

    The REST API answers ``inputs: null`` for a finished workflow_dispatch, so
    the inputs are recovered from the run itself: short ones from the title
    (``config_from_title``), the long ones from a called job's log
    (``inputs_from_jobs``), which the title truncates.
    """
    return json.loads(
        _gh(["run", "view", run_id, "--json", "jobs,displayTitle"], repo=repo)
    )
