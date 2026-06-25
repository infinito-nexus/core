"""Trigger the manual CI run (entry-manual.yml) for the current branch."""

from __future__ import annotations

import argparse
import sys

from cli.administration.deploy.ci import runs

_WORKFLOW = "entry-manual.yml"
# entry-manual.yml reads "__ALL__" as "force a full deploy across all roles".
_ALL = "__ALL__"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="infinito administration deploy ci trigger",
        description=(
            "Dispatch the manual CI workflow for the branch you are on. "
            "Default: trigger every role. With --failed: only the roles that "
            "failed in the last run. With --apps: an explicit role list."
        ),
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--failed",
        nargs="?",
        const="total",
        default=None,
        choices=("total", "swarm", "compose", "docker"),
        metavar="{total,swarm,compose}",
        help=(
            "Only re-trigger roles that were not green in the last run. "
            "Optional scope: 'total' (default; failed in either mode), "
            "'swarm', or 'compose'."
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
        metavar="URL",
        help=(
            "Run URL whose results determine the --failed apps. Default: the "
            "latest deploy run on the current branch."
        ),
    )
    args = p.parse_args(argv)

    branch = runs.current_branch()
    repo = runs.resolve_repo()

    if args.apps is not None:
        apps = " ".join(args.apps.split())
        if not apps:
            p.error("--apps was empty")
        whitelist = apps
    elif args.failed is not None:
        scope = "docker" if args.failed == "compose" else args.failed
        if args.run:
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
        whitelist = " ".join(failed)
    else:
        whitelist = _ALL

    label = "all roles" if whitelist == _ALL else whitelist
    print(f"Triggering {_WORKFLOW} on {repo}@{branch} for: {label}")
    runs.dispatch_workflow(_WORKFLOW, branch, whitelist, repo=repo)
    print("Dispatched. Watch with: infinito administration deploy ci status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
