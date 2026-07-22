"""Shared helpers for the CI deploy-run status/trigger commands.

Reads GitHub Actions runs via the ``gh`` CLI and maps the per-app
compose ("docker") and swarm deploy jobs to pass/fail/abort states.
A mode job that ran but did not finish successfully (cancelled, timed out,
still running) counts as a failure; a mode the role has no job for is N/A
and never fails the aggregated ``total`` column.

Deploy jobs are matched by the compose/swarm/host glyph (from the symbol
glossary, the single source of truth) their test-deploy-{compose,swarm,host}.yml
matrix titles them with -- NOT the words "Compose"/"Swarm"/"Host", which no
real job carries (matching those made ``--failed swarm`` silently find
nothing). The orchestrator prepends a
"caller / " prefix and GitHub appends a " <variant>" shard suffix (e.g.
" 0,1"); both are tolerated.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

from utils.symbol_glossary import to_emoji

PASS = "✅"  # noqa: S105  emoji glyph, not a credential
FAIL = "❌"
ABORT = "🚫"
RUNNING = "⏳"
MISSING = "➖"

MODES = ("docker", "swarm", "host")

MODE_GLYPHS = {
    "docker": to_emoji("compose"),
    "swarm": to_emoji("swarm"),
    "host": to_emoji("host"),
}
_GLYPH_MODE = {glyph: mode for mode, glyph in MODE_GLYPHS.items()}

_JOB_RE = re.compile(
    rf"({'|'.join(map(re.escape, MODE_GLYPHS.values()))})"
    r"\s+([a-z0-9]+(?:-[a-z0-9]+)+)(?:\s+[\d,]+)?\s*$"
)


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
        yield match.group(2), _GLYPH_MODE[match.group(1)], job


def app_of_job(name: str) -> str | None:
    """The role id a deploy job ``name`` encodes, or None if it is not one."""
    match = _JOB_RE.search(name)
    return match.group(2) if match else None


_SEVERITY = {"success": 0, "running": 1, "failure": 3}


def _severity(state: str) -> int:
    return _SEVERITY.get(state, 2)


def parse_role_statuses(jobs: list[dict]) -> dict[str, dict[str, str]]:
    """Map ``app id -> {"docker": state, "swarm": state}`` from gh job dicts.

    ``state`` is the raw effective outcome ('success' / 'failure' /
    'running' / 'cancelled' / ...). Modes without a job are simply absent.
    A role's variant shards run as separate jobs per mode; the mode state
    aggregates them worst-first, so one green shard can never mask a failed
    sibling (gitlab swarm variant 1 red, variant 0 green -> swarm failure).
    """
    out: dict[str, dict[str, str]] = {}
    for app, mode, job in _iter_deploy_jobs(jobs):
        state = _effective(job)
        modes = out.setdefault(app, {})
        if mode not in modes or _severity(state) > _severity(modes[mode]):
            modes[mode] = state
    return out


def parse_role_urls(jobs: list[dict]) -> dict[str, dict[str, str]]:
    """Map ``app id -> {"docker": url, "swarm": url}`` of the job html URLs,
    keeping the URL of the worst shard so links point at the failing job."""
    out: dict[str, dict[str, str]] = {}
    worst: dict[tuple[str, str], int] = {}
    for app, mode, job in _iter_deploy_jobs(jobs):
        url = job.get("url")
        if not url:
            continue
        severity = _severity(_effective(job))
        if (app, mode) not in worst or severity > worst[(app, mode)]:
            worst[(app, mode)] = severity
            out.setdefault(app, {})[mode] = url
    return out


def total_state(modes: dict[str, str]) -> str:
    """Aggregate the per-mode states into the ``total`` column: green only when
    every mode that actually ran is green. A mode the role has no job for is N/A
    (a host driver never deploys in swarm) and does NOT fail the total;
    ``parse_role_statuses`` only lists roles with at least one deploy job, so
    there is always a present mode to judge."""
    present = [modes[m] for m in MODES if m in modes]
    return "success" if present and all(s == "success" for s in present) else "failure"


def failed_roles(
    statuses: dict[str, dict[str, str]], scope: str = "total"
) -> list[str]:
    """Roles that are not green for the given scope: ``total`` (a mode that ran
    is not green), ``swarm``, or ``docker`` (compose). A role with no job in the
    requested mode is skipped, not failed: a host driver that never deploys in
    swarm is not a swarm failure, only roles whose swarm job ran and did not pass
    are."""

    def fails(modes: dict[str, str]) -> bool:
        if scope == "total":
            return total_state(modes) != "success"
        return scope in modes and modes[scope] != "success"

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
    workflow: str,
    ref: str,
    whitelist: str = "",
    *,
    priority: str = "",
    repo: str | None = None,
) -> None:
    args = ["workflow", "run", workflow, "--ref", ref]
    if whitelist:
        args += ["-f", f"whitelist={whitelist}"]
    if priority:
        args += ["-f", f"priority={priority}"]
    _gh(args, repo=repo)
