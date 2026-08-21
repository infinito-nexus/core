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

from cli.administration.deploy.ci.gh import (
    _gh,
    fetch_jobs,
)
from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.github import run_name
from utils.github.variant import axes
from utils.roles.display import display_names, split_axes
from utils.symbol_glossary import to_emoji

PASS = "✅"  # noqa: S105  emoji glyph, not a credential
FAIL = "❌"
ABORT = "🚫"
RUNNING = "⏳"
MISSING = "➖"

MODES = ("docker", "swarm", "host")

ENTRY_WORKFLOW = ".github/workflows/entry-manual-steer.yml"

SELECTION_INPUTS = ("priority", "offset")
"""The two inputs a retrigger decides itself rather than carrying over.

``priority`` IS the retrigger: it names what failed. ``offset`` follows from
it -- the source run already has a verdict for everything up to where its
budget ran out, so the regular line resumes behind that window
(:func:`resume_offset`) instead of repeating it. Everything else is carried
verbatim, including ``whitelist``, so a retrigger of a scoped run stays inside
that scope instead of quietly widening to the whole repository."""


def dispatch_inputs() -> tuple[str, ...]:
    """Every ``workflow_dispatch`` input the manual entry declares.

    Read from the workflow rather than listed here, so an input added to the
    form is carried over without anyone remembering to teach this module about
    it -- the failure mode otherwise is silent: the retrigger runs with that
    input on its default and nothing says so.
    """
    data = (
        load_yaml_any(str(PROJECT_ROOT / ENTRY_WORKFLOW), default_if_missing={}) or {}
    )
    triggers = data.get("on") if isinstance(data.get("on"), dict) else data.get(True)
    dispatch = triggers.get("workflow_dispatch") if isinstance(triggers, dict) else None
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    return tuple(inputs or ())


def carried_inputs() -> tuple[str, ...]:
    """The inputs a retrigger reproduces: every dispatch input except the
    selection it computes itself."""
    return tuple(name for name in dispatch_inputs() if name not in SELECTION_INPUTS)


CONFIG_INPUTS = (
    "distros",
    "mode",
    "lifecycles",
    "filesystem",
    "chunk_gate",
    "workspace",
    "instructions",
)

LOG_INPUTS = ("tor",)
"""Inputs the retrigger reads from the job log rather than the run title.

The title renders these as glyphs, so recovering one means translating a
symbol back into a value; the log holds the word the operator picked. Reading
it there keeps the retrigger honest even if the title's marker changes shape.
"""

MODE_GLYPHS = {
    "docker": to_emoji("compose"),
    "swarm": to_emoji("swarm"),
    "host": to_emoji("host"),
}

_STATUS_MODE = {"compose": "docker", "swarm": "swarm", "host": "host"}
"""The status table keeps calling compose 'docker'; the deploy axis calls it
'compose'. Translate at the boundary instead of renaming either vocabulary."""


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
    """Yield ``(app, mode, job)`` for every deploy job."""
    codec = display_names()
    for job in jobs:
        label = axes.parse_label(str(job.get("name", "")))
        if label is None:
            continue
        app = codec.decode(label.name)
        if app is not None:
            yield app, _STATUS_MODE[label.mode], job


def app_of_job(name: str) -> str | None:
    """The role id a deploy job ``name`` encodes, or None if it is not one."""
    label = axes.parse_label(name)
    return display_names().decode(label.name) if label else None


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


_INPUT_RE = re.compile(r"^\S+\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*): ?(?P<value>.*)$")


def _parse_inputs(log: str) -> dict[str, str]:
    """The ``##[group] Inputs`` block of a job log, as name -> value."""
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

    Candidates are read shallowest first, because a depth-1 job records the
    orchestrator's own inputs while a deeper one records what its caller
    forwarded. Skipped jobs are passed over: they never upload a log blob, so
    their log endpoint answers ``BlobNotFound`` as a bare HTTP 404 -- and a
    force-cancelled run can leave every depth-1 job skipped, which is why the
    deeper jobs are read at all rather than treated as inputs-free.

    Args:
        jobs: the run's jobs, as ``gh run view --json jobs`` returns them.
        repo: ``owner/repo`` the run lives in.

    Returns:
        input name -> value, empty when no job of the run records an ``Inputs``
        block -- including when the logs have expired.
    """
    candidates = sorted(
        (
            job
            for job in jobs
            if str(job.get("name", "")).count(" / ") >= 1
            and job.get("databaseId")
            and job.get("conclusion") != "skipped"
        ),
        key=lambda job: str(job["name"]).count(" / "),
    )
    for job in candidates:
        inputs = _parse_inputs(
            _gh(
                [
                    "api",
                    "--allow-escape-sequences",
                    f"repos/{repo}/actions/jobs/{job['databaseId']}/logs",
                ],
                check=False,
            )
        )
        if inputs:
            return inputs
    return {}


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

    A priority entry may pin axes (``web-app-zammad#1@compose+tor``), and the
    pin rides along into the retrigger: the entry never ran, so the run holds
    no evidence that the axes it named were the wrong ones. Only the name in
    front of the axis suffix is resolved against the statuses.

    Args:
        priority: the raw ``priority`` input, as :func:`inputs_from_jobs` reads
            it back. A truncated value would smuggle a half-token into the
            retrigger's role set, so an undecodable name raises instead.
        statuses: role -> mode -> state, from :func:`parse_role_statuses`.

    Returns:
        the entries whose role has no job at all in the source run, each with
        its own axis suffix intact.
    """
    codec = display_names()
    untriggered = []
    for token in priority.split():
        name, axes = split_axes(token)
        role = codec.decode(name)
        if role is None:
            raise SystemExit(
                f"Cannot resolve priority entry {token!r} to a role. The source "
                f"run's priority input is corrupt or truncated; retriggering "
                f"with it would deploy a role set that is silently incomplete."
            )
        if role not in statuses:
            untriggered.append(role + axes)
    return sorted(untriggered)


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


def config_from_run(title: str, logged: dict[str, str] | None = None) -> dict[str, str]:
    """Every input the source run was dispatched with, except the selection.

    The job log is the source: it records all inputs verbatim, including the
    ones the title renders as a glyph and the ones it renders not at all. The
    title fills the gaps when a log is unreadable.

    An input the source left on its default resolves to empty and is dropped,
    so the retrigger leaves it on that same default rather than pinning
    today's default into a run that never asked for it.

    Args:
        title: the source run's display title.
        logged: inputs read verbatim from a called job's log
            (:func:`inputs_from_jobs`).
    """
    recorded = run_name.values_from_title(title)
    config = {
        name: (logged or {}).get(name) or recorded.get(name, "")
        for name in carried_inputs()
    }
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
