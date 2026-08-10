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
nothing). What follows the glyph is the role's display name
(``utils.roles.display``), decoded back to the role id; a bare role id from a
run that predates the display names decodes just as well. The orchestrator
prepends a "caller / " prefix and the shard suffix (e.g. " 0,1") rides along
in the display name; both are tolerated.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

from utils.distros import distro_names
from utils.github import run_name
from utils.roles.display import display_names
from utils.symbol_glossary import to_emoji

PASS = "✅"  # noqa: S105  emoji glyph, not a credential
FAIL = "❌"
ABORT = "🚫"
RUNNING = "⏳"
MISSING = "➖"

MODES = ("docker", "swarm", "host")

CONFIG_INPUTS = (
    "distros",
    "modes",
    "lifecycles",
    "filesystem",
    "sequencing",
    "mode_fail_fast",
    "workspace",
    "instructions",
)

MODE_GLYPHS = {
    "docker": to_emoji("compose"),
    "swarm": to_emoji("swarm"),
    "host": to_emoji("host"),
}
_GLYPH_MODE = {glyph: mode for mode, glyph in MODE_GLYPHS.items()}

_JOB_RE = re.compile(rf"({'|'.join(map(re.escape, MODE_GLYPHS.values()))})\s*(.+?)\s*$")


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
    codec = display_names()
    for job in jobs:
        match = _JOB_RE.search(str(job.get("name", "")))
        if not match:
            continue
        app = codec.decode(match.group(2))
        if app is not None:
            yield app, _GLYPH_MODE[match.group(1)], job


def app_of_job(name: str) -> str | None:
    """The role id a deploy job ``name`` encodes, or None if it is not one."""
    match = _JOB_RE.search(name)
    return display_names().decode(match.group(2)) if match else None


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
    statuses: dict[str, dict[str, str]], scope: str = "total", *, strict: bool = False
) -> list[str]:
    """Roles that are not green for the given scope: ``total`` (a mode that ran
    is not green), ``swarm``, or ``docker`` (compose). A role with no job in the
    requested mode is skipped, not failed: a host driver that never deploys in
    swarm is not a swarm failure, only roles whose swarm job ran and did not pass
    are.

    With ``strict``, only a hard ``failure`` (❌) selects a role; cancelled,
    timed-out, skipped (🚫) and still-running (⏳) modes do not.
    """

    def fails(modes: dict[str, str]) -> bool:
        if strict:
            if scope == "total":
                return any(state == "failure" for state in modes.values())
            return modes.get(scope) == "failure"
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


def fetch_run(run_id: str, repo: str | None = None) -> dict:
    """Jobs plus the run title, in one ``gh`` call.

    The REST API answers ``inputs: null`` for a finished workflow_dispatch, so
    the inputs are recovered from the run itself: short ones from the title
    (:func:`config_from_title`), the long ones from a called job's log
    (:func:`inputs_from_jobs`), which the title truncates.
    """
    return json.loads(
        _gh(["run", "view", run_id, "--json", "jobs,displayTitle"], repo=repo)
    )


_INPUT_RE = re.compile(r"^\S+\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*): ?(?P<value>.*)$")


def inputs_from_jobs(jobs: list[dict], repo: str) -> dict[str, str]:
    """The dispatch inputs a called job's log records verbatim.

    GitHub cuts ``display_title`` at 512 UTF-8 bytes (measured on two runs,
    both exactly 512) and closes it with a literal ``...``. The run-name
    template renders ``priority`` second-to-last and ``whitelist`` last, and
    on the ``--failed`` path the whitelist is empty, so the cut always lands
    inside the priority list: measured 21 of 69 roles survived, the 21st a
    half-token. A CJK display name costs 3 bytes per character, so the budget
    is ~22 display names against ~28 bare role ids. Every job of the *called*
    workflow opens its log with an ``##[group] Inputs`` block holding the full
    values, so that is the SPOT for anything the title cannot hold.

    Args:
        jobs: the run's jobs. Only depth-1 jobs are read: a deeper one echoes
            its own workflow's inputs, which carry no ``priority``.
        repo: ``owner/repo`` the run lives in.

    Returns:
        input name -> value, empty when the run has no called job.
    """
    called = next(
        (
            job
            for job in jobs
            if str(job.get("name", "")).count(" / ") == 1 and job.get("databaseId")
        ),
        None,
    )
    if called is None:
        return {}
    log = _gh(["api", f"repos/{repo}/actions/jobs/{called['databaseId']}/logs"])
    inputs: dict[str, str] = {}
    inside = False
    for line in log.splitlines():
        if line.endswith("##[group] Inputs"):
            inside = True
            continue
        if inside:
            if line.endswith("##[endgroup]"):
                break
            match = _INPUT_RE.match(line)
            if match:
                inputs[match["name"]] = match["value"].strip()
    return inputs


def dispatched_priority(source: dict, repo: str) -> str:
    """The source run's ``priority`` input, whole.

    The title's priority segment is the cross-check, not the source: it proves
    a priority line existed even when truncation mangled it, so an empty log
    read is a broken reader -- expired logs, a moved Inputs block, an inlined
    orchestrator -- rather than a run dispatched without one.

    Args:
        source: the run as :func:`fetch_run` returns it.
        repo: ``owner/repo`` the run lives in.
    """
    priority = inputs_from_jobs(source["jobs"], repo).get("priority", "")
    if not priority and run_name.value_from_title(source["displayTitle"], "priority"):
        raise SystemExit(
            "Source run has a priority line but its job log records no inputs; "
            "the Inputs block moved or the log expired. Retriggering now would "
            "silently drop every priority role."
        )
    return priority


def untriggered_priority(
    priority: str, statuses: dict[str, dict[str, str]]
) -> list[str]:
    """Roles the source run's priority line named but never deployed at all.

    A priority role can fall behind the discovery budget cut in every mode, so
    the run holds no job for it and :func:`failed_roles` cannot see it — it is
    neither green nor red, it simply never ran. Carrying it into the retrigger
    is the only way it ever gets deployed.

    Args:
        priority: the raw ``priority`` input, as :func:`inputs_from_jobs` reads
            it back. A truncated value would smuggle a half-token into the
            retrigger's role set, so an undecodable name raises instead.
        statuses: role -> mode -> state, from :func:`parse_role_statuses`.
    """
    codec = display_names()
    named = []
    for name in priority.split():
        role = codec.decode(name)
        if role is None:
            raise SystemExit(
                f"Cannot resolve priority entry {name!r} to a role. The source "
                f"run's priority input is corrupt or truncated; retriggering "
                f"with it would deploy a role set that is silently incomplete."
            )
        named.append(role)
    return sorted(role for role in named if role not in statuses)


def distros_from_jobs(jobs: list[dict]) -> str:
    """Distros the run actually swept, read back from its discover job names.

    A manual run dispatched with no distro list resolves one at random, so its
    title records nothing and only the discover jobs — which name the distros
    they discovered for — still carry the answer. Matched by content, not by
    job-name format: the parenthesised group whose every token is a declared
    distro (meta/distros.yml SPOT) is the list.
    """
    known = set(distro_names())
    for job in jobs:
        for group in re.findall(r"\(([^()]*)\)", str(job.get("name", ""))):
            tokens = group.split()
            if tokens and set(tokens) <= known:
                return " ".join(tokens)
    return ""


def config_from_title(title: str) -> dict[str, str]:
    """Configuration inputs a manual run was dispatched with, keyed by input
    name. An input left on its workflow default renders no title segment and
    is absent here, so the retrigger leaves it on that same default.

    Only the configuration is recovered, never the selection: ``whitelist``
    and ``priority`` say which roles ran, and a retrigger computes those
    itself. Runs from any other entry point carry an unrelated title and
    yield nothing at all.
    """
    recorded = run_name.values_from_title(title)
    return {name: recorded[name] for name in CONFIG_INPUTS if name in recorded}


def config_from_run(title: str, jobs: list[dict]) -> dict[str, str]:
    """The source run's configuration, with the distros the title does not
    record recovered from its jobs (:func:`distros_from_jobs`)."""
    config = config_from_title(title)
    if not config.get("distros"):
        config = {**config, "distros": distros_from_jobs(jobs)}
    return {name: value for name, value in config.items() if value}


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
            "databaseId,url,workflowName,createdAt,status,displayTitle",
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
    config: dict[str, str] | None = None,
    repo: str | None = None,
) -> None:
    """Dispatch *workflow*, carrying *config* (see :func:`config_from_title`)
    over verbatim. An input left out keeps the workflow's own default.

    The role selections go out as display names (``utils.roles.display``), so
    the run title reads them back the way the deploy jobs are titled. The
    workflow decodes them again before any consumer sees a role id.
    """
    codec = display_names()
    args = ["workflow", "run", workflow, "--ref", ref]
    if whitelist:
        args += ["-f", f"whitelist={codec.encode_list(whitelist)}"]
    if priority:
        args += ["-f", f"priority={codec.encode_list(priority)}"]
    args += [
        arg
        for name, value in (config or {}).items()
        if value
        for arg in ("-f", f"{name}={value}")
    ]
    _gh(args, repo=repo)
