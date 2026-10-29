"""Print the priority line a retrigger of a CI run dispatches, on one line."""

from __future__ import annotations

import argparse
import sys

from cli.administration.deploy.ci import gh, runs, selections


def _source(run: str | None) -> tuple[dict, str] | None:
    """The run to read and the repository it lives in.

    Args:
        run: a run URL or a bare run id; ``None`` reads the latest deploy run
            of the current branch.

    Returns:
        The run as ``gh.fetch_run`` returns it and its ``owner/repo``, or
        ``None`` when the current branch has no deploy run.
    """
    repo = gh.resolve_repo()
    if run:
        owner_repo = repo if run.isdigit() else gh.slug_from_url(run)
        return gh.fetch_run_ref(run, repo), owner_repo
    found = runs.find_last_deploy_run(gh.current_branch(), repo=repo)
    if found is None:
        return None
    return {"jobs": found["_jobs"], "displayTitle": found.get("displayTitle", "")}, repo


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="infinito meta ci priority",
        description=(
            "Print the priority line that 'infinito administration deploy ci "
            "trigger --failed' dispatches for a run: every selection that was not "
            "green, with its variant, deploy mode, network and distro, plus the "
            "priority entries the run never deployed. The entries come out "
            "space-separated on a single line, ready to paste into the priority "
            "input of the manual CI workflow. Nothing is dispatched."
        ),
    )
    p.add_argument(
        "run",
        nargs="?",
        default=None,
        metavar="URL|ID",
        help="Run URL or bare run id. Default: the latest deploy run on the current branch.",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Only hard failures (❌), not cancelled or still-running jobs.",
    )
    p.add_argument(
        "--roles-only",
        action="store_true",
        help="Hard failures come back as role names instead of their exact axes.",
    )
    args = p.parse_args(argv)

    resolved = _source(args.run)
    if resolved is None:
        print(
            "No CI run with deploy jobs found on the current branch.", file=sys.stderr
        )
        return 1
    source, repo = resolved
    failed, untriggered = selections.retrigger_entries(
        source, repo, strict=args.strict, roles_only=args.roles_only
    )
    entries = sorted(set(failed) | set(untriggered))
    if not entries:
        print("Nothing failed in that run.", file=sys.stderr)
        return 0
    print(" ".join(entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
