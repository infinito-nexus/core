"""Trigger the manual CI run (entry-manual-steer.yml) for the current branch.

entry-manual-steer.yml reads the "__ALL__" whitelist sentinel as "force a full
deploy across all roles".

A retrigger differs from its source run in the selection and in nothing else:
every other dispatch input is carried over (:func:`runs.carried_inputs`, read
off the workflow itself), and the priority line names the exact selections that
failed -- role, variant, deploy mode, onion state and distro -- rather than the
roles they belong to. The filesystem is left to the rotation
(:mod:`cli.administration.deploy.ci.selections` says why).
"""

from __future__ import annotations

import argparse
import sys

from cli.administration.deploy.ci import gh, runs, selections
from cli.meta.ci import matrix, query
from utils.github.variant import pools, tor

_WORKFLOW = "entry-manual-steer.yml"
_ALL = "__ALL__"


def _fetch(run: str, repo: str) -> dict:
    """The jobs and title of *run*, given as a URL or a bare id (which
    resolves against *repo*, the current branch's own)."""
    if run.isdigit():
        return gh.fetch_run(run, repo=repo)
    return gh.fetch_run(gh.run_id_from_url(run), repo=gh.slug_from_url(run))


def _resume_offset(source: dict, whitelist: str, config: dict[str, str]) -> str:
    """Where the retrigger's regular line should start.

    The source run walked the ranking until its budget ran out. Those rows
    have a verdict already -- and the red ones return on the priority line --
    so the regular line resumes behind them instead of redeploying the same
    window. The ranking is recomputed under the retrigger's own configuration,
    because that is the list the offset will be resolved against.

    The priority line is deliberately left out of that computation: it only
    blacklists rows from the regular query, and a token in it that no longer
    resolves would abort here, in a helper whose job is to save runner time.
    """
    entries = matrix.entries_of(
        modes=query.resolve_modes(config.get("mode") or query.ALL_MODES),
        whitelist="" if whitelist == _ALL else whitelist,
        priority="",
        lifecycles=config.get("lifecycles", ""),
        sweep=0,
        tor_mode=tor.resolve_tor_mode(config.get("tor")),
        distros=pools.resolve_distros(config.get("distros")),
        filesystems=pools.resolve_filesystems(config.get("filesystem")),
    )
    return selections.resume_offset(
        entries, selections.deployed_selections(source["jobs"])
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="infinito administration deploy ci trigger",
        description=(
            "Dispatch the manual CI workflow for the branch you are on. "
            "Default: trigger every role. With --failed: the roles that "
            "failed in the last run form the priority line and the full "
            "run follows once they are green. With --apps: an explicit "
            "role list as whitelist. Whenever a source run is read, its "
            "configuration is carried over so the retrigger reproduces it."
        ),
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--failed",
        nargs="?",
        const=True,
        default=None,
        metavar="(ignored)",
        help=(
            "Re-trigger what was not green in the source run as the priority "
            "line, together with the priority entries that run never deployed "
            "at all; the remaining roles follow once they succeed. Every mode "
            "is read, and each failed job comes back as the exact selection "
            "that failed -- variant, deploy mode and onion state included. A "
            "leftover scope argument is accepted and ignored."
        ),
    )
    group.add_argument(
        "--apps",
        default=None,
        metavar='"app1 app2 ..."',
        help="Explicit space-separated role ids to trigger.",
    )
    p.add_argument(
        "--run",
        default=None,
        metavar="URL|ID",
        help=(
            "Run URL or bare run id to reproduce: its configuration (distros, "
            "mode, lifecycles, filesystem, chunk_gate, "
            "workspace, instructions) is carried over, and with --failed its "
            "results also pick the apps. A bare id resolves against the current "
            "branch's repo. With --failed and no --run: the latest deploy run "
            "on the current branch."
        ),
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help=(
            "With --failed: re-trigger only roles with a hard failure (❌), "
            "not cancelled/aborted (🚫) or still-running (⏳)."
        ),
    )
    args = p.parse_args(argv)
    if args.strict and args.failed is None:
        p.error("--strict only applies with --failed")

    branch = gh.current_branch()
    repo = gh.resolve_repo()

    source = None
    if args.run:
        source = _fetch(args.run, repo)
    elif args.failed is not None:
        run = runs.find_last_deploy_run(branch, repo=repo)
        if run is None:
            print(
                f"No CI run with deploy jobs found on {repo}@{branch}.",
                file=sys.stderr,
            )
            return 1
        source = {"jobs": run["_jobs"], "displayTitle": run.get("displayTitle", "")}

    whitelist = ""
    priority = ""
    if args.apps is not None:
        apps = " ".join(args.apps.split())
        if not apps:
            p.error("--apps was empty")
        whitelist = apps
    elif args.failed is not None:
        statuses = runs.parse_role_statuses(source["jobs"])
        failed = selections.failed_selections(source["jobs"], strict=args.strict)
        untriggered = runs.untriggered_priority(
            runs.dispatched_priority(source, repo), statuses
        )
        if not failed and not untriggered:
            print("Nothing failed in that run; not triggering.")
            return 0
        if untriggered:
            print(f"Priority roles that never deployed: {' '.join(untriggered)}")
        priority = " ".join(sorted(set(failed) | set(untriggered)))
    else:
        whitelist = _ALL

    config: dict[str, str] = {}
    if source is not None:
        config = runs.config_from_run(
            source["displayTitle"],
            runs.inputs_from_jobs(source["jobs"], repo),
        )
    carried_whitelist = config.pop("whitelist", "")
    if not whitelist and carried_whitelist:
        whitelist = carried_whitelist

    if args.failed is not None:
        config["offset"] = _resume_offset(source, whitelist, config)
        if config["offset"]:
            print(f"Regular line resumes at: {config['offset']}")
        else:
            config.pop("offset")

    if priority:
        label = f"priority {priority}, then the remaining roles"
    elif whitelist == _ALL:
        label = "all roles"
    else:
        label = whitelist
    carried = ", ".join(f"{name}={value}" for name, value in config.items())
    print(f"Triggering {_WORKFLOW} on {repo}@{branch} for: {label}")
    if carried:
        print(f"Carrying over from the source run: {carried}")
    runs.dispatch_workflow(
        _WORKFLOW, branch, whitelist, priority=priority, config=config, repo=repo
    )
    print("Dispatched. Watch with: infinito administration deploy ci status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
