"""Trigger the manual CI run (entry-manual.yml) for the current branch.

entry-manual.yml reads the "__ALL__" whitelist sentinel as "force a full
deploy across all roles".
"""

from __future__ import annotations

import argparse
import sys

from cli.administration.deploy.ci import runs

_WORKFLOW = "entry-manual.yml"
_ALL = "__ALL__"


def _fetch(run: str, repo: str) -> dict:
    """The jobs and title of *run*, given as a URL or a bare id (which
    resolves against *repo*, the current branch's own)."""
    if run.isdigit():
        return runs.fetch_run(run, repo=repo)
    return runs.fetch_run(runs.run_id_from_url(run), repo=runs.slug_from_url(run))


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
        const="total",
        default=None,
        choices=("total", "swarm", "compose", "docker", "host"),
        metavar="{total,swarm,compose,host}",
        help=(
            "Re-trigger roles that were not green in the source run as the "
            "priority line, together with the priority roles that run never "
            "deployed at all; the remaining roles follow once they succeed. "
            "Optional scope: 'total' (default; failed in any mode), "
            "'swarm', 'compose', or 'host'."
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
            "modes, lifecycles, filesystem, sequencing, mode_fail_fast, "
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

    branch = runs.current_branch()
    repo = runs.resolve_repo()

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
        scope = "docker" if args.failed == "compose" else args.failed
        statuses = runs.parse_role_statuses(source["jobs"])
        failed = runs.failed_roles(statuses, scope, strict=args.strict)
        untriggered = runs.untriggered_priority(source["displayTitle"], statuses)
        if not failed and not untriggered:
            print(f"Nothing failed ({args.failed}) in that run; not triggering.")
            return 0
        if untriggered:
            print(f"Priority roles that never deployed: {' '.join(untriggered)}")
        priority = " ".join(sorted(set(failed) | set(untriggered)))
    else:
        whitelist = _ALL

    config: dict[str, str] = {}
    if source is not None:
        config = runs.config_from_run(source["displayTitle"], source["jobs"])

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
