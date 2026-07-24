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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="infinito administration deploy ci trigger",
        description=(
            "Dispatch the manual CI workflow for the branch you are on. "
            "Default: trigger every role. With --failed: the roles that "
            "failed in the last run form the priority line and the full "
            "run follows once they are green. With --apps: an explicit "
            "role list as whitelist."
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
            "Re-trigger roles that were not green in the last run as the "
            "priority line; the remaining roles run after they succeed. "
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
            "Run URL or bare run id whose results determine the --failed apps "
            "(a bare id resolves against the current branch's repo). Default: "
            "the latest deploy run on the current branch."
        ),
    )
    args = p.parse_args(argv)

    branch = runs.current_branch()
    repo = runs.resolve_repo()

    whitelist = ""
    priority = ""
    if args.apps is not None:
        apps = " ".join(args.apps.split())
        if not apps:
            p.error("--apps was empty")
        whitelist = apps
    elif args.failed is not None:
        scope = "docker" if args.failed == "compose" else args.failed
        if args.run:
            if args.run.isdigit():
                jobs = runs.fetch_jobs(args.run, repo=repo)
            else:
                jobs = runs.fetch_jobs(
                    runs.run_id_from_url(args.run), repo=runs.slug_from_url(args.run)
                )
        else:
            run = runs.find_last_deploy_run(branch, repo=repo)
            if run is None:
                print(
                    f"No CI run with deploy jobs found on {repo}@{branch}.",
                    file=sys.stderr,
                )
                return 1
            jobs = run["_jobs"]
        failed = runs.failed_roles(runs.parse_role_statuses(jobs), scope)
        if not failed:
            print(f"Nothing failed ({args.failed}) in that run; not triggering.")
            return 0
        priority = " ".join(failed)
    else:
        whitelist = _ALL

    if priority:
        label = f"priority {priority}, then the remaining roles"
    elif whitelist == _ALL:
        label = "all roles"
    else:
        label = whitelist
    print(f"Triggering {_WORKFLOW} on {repo}@{branch} for: {label}")
    runs.dispatch_workflow(_WORKFLOW, branch, whitelist, priority=priority, repo=repo)
    print("Dispatched. Watch with: infinito administration deploy ci status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
