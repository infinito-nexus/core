"""Shared helpers for the CI deploy-run status/trigger commands.

Reads GitHub Actions runs via the ``gh`` CLI and maps the per-app
compose ("docker") and swarm deploy jobs to pass/fail/abort states.
A job that did not finish successfully (cancelled, timed out, skipped,
still running) counts as a failure in the aggregated ``all`` column.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

PASS = "✅"  # noqa: S105  emoji glyph, not a credential
FAIL = "❌"
ABORT = "🚫"
RUNNING = "⏳"
MISSING = "➖"

# Display order of the two deploy modes. "docker" is the compose mode.
MODES = ("docker", "swarm")

# Match a deploy job display name and pull out (mode, app id). Tolerates a
# leading emoji and an optional reusable-workflow "caller / " prefix; the app
# id is the trailing hyphenated token (every role id contains a hyphen).
_JOB_RE = re.compile(r"(Compose|Swarm)\s+([a-z0-9]+(?:-[a-z0-9]+)+)\s*$")


def _effective(job: dict) -> str:
    """The job's outcome: its conclusion when completed, else 'running'."""
    if job.get("status") != "completed":
        return "running"
    return job.get("conclusion") or "running"


def cell(state: str) -> str:
    if state == "success":
        return PASS
    if state == "failure":
        return FAIL
    if state == "running":
        return RUNNING
    if state == "missing":
        return MISSING
    return ABORT


def _iter_deploy_jobs(jobs: list[dict]):
    """Yield ``(app, mode, job)`` for every compose/swarm deploy job."""
    for job in jobs:
        match = _JOB_RE.search(str(job.get("name", "")))
        if not match:
            continue
        mode = "docker" if match.group(1) == "Compose" else "swarm"
        yield match.group(2), mode, job


def parse_role_statuses(jobs: list[dict]) -> dict[str, dict[str, str]]:
    """Map ``app id -> {"docker": state, "swarm": state}`` from gh job dicts.

    ``state`` is the raw effective outcome ('success' / 'failure' /
    'running' / 'cancelled' / ...). Modes without a job are simply absent.
    """
    out: dict[str, dict[str, str]] = {}
    for app, mode, job in _iter_deploy_jobs(jobs):
        out.setdefault(app, {})[mode] = _effective(job)
    return out


def parse_role_urls(jobs: list[dict]) -> dict[str, dict[str, str]]:
    """Map ``app id -> {"docker": url, "swarm": url}`` of the job html URLs."""
    out: dict[str, dict[str, str]] = {}
    for app, mode, job in _iter_deploy_jobs(jobs):
        url = job.get("url")
        if url:
            out.setdefault(app, {})[mode] = url
    return out


def total_state(modes: dict[str, str]) -> str:
    """Aggregate per-mode states into the ``total`` column: a pass only when
    BOTH modes are green; anything else (failure, abort, still-running,
    never-ran) is a failure."""
    if all(modes.get(m) == "success" for m in MODES):
        return "success"
    return "failure"


def failed_roles(
    statuses: dict[str, dict[str, str]], scope: str = "total"
) -> list[str]:
    """Roles that are not green for the given scope: ``total`` (either mode not
    green), ``swarm``, or ``docker`` (compose)."""

    def fails(modes: dict[str, str]) -> bool:
        if scope == "total":
            return total_state(modes) != "success"
        return modes.get(scope) != "success"

    return sorted(app for app, modes in statuses.items() if fails(modes))


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
    'origin' or the only configured remote."""
    try:
        upstream = _run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
        )
        if "/" in upstream:
            return upstream.split("/", 1)[0]
    except subprocess.CalledProcessError:
        pass
    remotes = _run(["git", "remote"]).split()
    if "origin" in remotes:
        return "origin"
    if not remotes:
        raise RuntimeError("no git remote configured")
    return remotes[0]


def resolve_repo() -> str:
    """The ``owner/repo`` the current branch lives on, derived from its
    tracking remote (not gh's default repo, which may be the upstream)."""
    return slug_from_url(_run(["git", "remote", "get-url", _branch_remote()]))


def _gh(args: list[str], repo: str | None = None) -> str:
    cmd = ["gh", *args]
    if repo:
        cmd += ["--repo", repo]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
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


def find_last_deploy_run(
    branch: str, repo: str | None = None, limit: int = 15
) -> dict | None:
    """Newest run on ``branch`` (in ``repo``) that actually contains compose/
    swarm deploy jobs. Returns the run dict (with a cached ``_jobs`` key) or
    None.

    Walks up to ``limit`` recent runs because the very latest run on a branch
    is often a lint-only or skipped event with no deploy matrix.
    """
    listed = _gh(
        [
            "run",
            "list",
            "--branch",
            branch,
            "-L",
            str(limit),
            "--json",
            "databaseId,url,workflowName,createdAt,status",
        ],
        repo=repo,
    )
    for run in json.loads(listed):
        jobs = fetch_jobs(str(run["databaseId"]), repo=repo)
        if parse_role_statuses(jobs):
            run["_jobs"] = jobs
            return run
    return None


def dispatch_workflow(
    workflow: str, ref: str, whitelist: str, repo: str | None = None
) -> None:
    _gh(
        ["workflow", "run", workflow, "--ref", ref, "-f", f"whitelist={whitelist}"],
        repo=repo,
    )
