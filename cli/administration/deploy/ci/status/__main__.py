"""Per-role compose ("docker") and swarm deploy status of a CI run."""

from __future__ import annotations

import argparse
import sys

from cli.administration.deploy.ci import runs


def _build_rows(
    statuses: dict[str, dict[str, str]], urls: dict[str, dict[str, str]]
) -> list[tuple[str, str, str, str, str]]:
    rows = []
    for app, modes in sorted(statuses.items()):
        url = urls.get(app, {})
        run = " ".join(u for u in (url.get("docker"), url.get("swarm")) if u)
        rows.append(
            (
                app,
                runs.cell(modes.get("docker", "missing")),
                runs.cell(modes.get("swarm", "missing")),
                runs.cell(runs.total_state(modes)),
                run,
            )
        )
    return rows


def _render_table(rows: list[tuple[str, str, str, str, str]]) -> str:
    if not rows:
        return ""
    name_w = max(len("role"), max(len(r[0]) for r in rows))
    lines = [
        f"{'role':<{name_w}}  docker  swarm  total  run",
        f"{'-' * name_w}  ------  -----  -----  ---",
    ]
    for app, docker, swarm, totalc, run in rows:
        lines.append(f"{app:<{name_w}}    {docker}      {swarm}      {totalc}    {run}")
    return "\n".join(lines)


def _render_string(rows: list[tuple[str, str, str, str, str]]) -> str:
    return "\n".join(
        f"{app} {docker} {swarm} {totalc} {run}"
        for app, docker, swarm, totalc, run in rows
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="infinito administration deploy ci status",
        description=(
            "Show every role's compose (docker) and swarm deploy result from a "
            "CI run, plus an aggregated 'total' column (green when every mode "
            "that ran is green; a mode the role skips is N/A)."
        ),
    )
    p.add_argument(
        "--url",
        default=None,
        help=(
            "GitHub Actions run URL to read. Default: the most recent run on "
            "the current branch that has deploy jobs."
        ),
    )
    p.add_argument(
        "--failed",
        nargs="?",
        const="total",
        default=None,
        choices=("total", "swarm", "compose", "docker", "host"),
        metavar="{total,swarm,compose,host}",
        help=(
            "Show only roles that were not green. Optional scope: 'total' "
            "(default; failed in any mode), 'swarm', 'compose', or 'host'."
        ),
    )
    p.add_argument(
        "--format",
        choices=("table", "string"),
        default="table",
        help="Output format. 'table' (default) is aligned; 'string' is "
        "whitespace-separated 'role docker swarm total' per line.",
    )
    args = p.parse_args(argv)

    if args.url:
        jobs = runs.fetch_jobs(
            runs.run_id_from_url(args.url), repo=runs.slug_from_url(args.url)
        )
        source = args.url
    else:
        branch = runs.current_branch()
        repo = runs.resolve_repo()
        run = runs.find_last_deploy_run(branch, repo=repo)
        if run is None:
            print(
                f"No CI run with deploy jobs found on {repo}@{branch}.",
                file=sys.stderr,
            )
            return 1
        jobs = run["_jobs"]
        source = run["url"]

    statuses = runs.parse_role_statuses(jobs)
    if not statuses:
        print("No compose/swarm deploy jobs in that run.", file=sys.stderr)
        return 1

    if args.failed is not None:
        scope = "docker" if args.failed == "compose" else args.failed
        keep = set(runs.failed_roles(statuses, scope))
        statuses = {app: modes for app, modes in statuses.items() if app in keep}
        if not statuses:
            print(f"No roles failed ({args.failed}).", file=sys.stderr)
            return 0

    rows = _build_rows(statuses, runs.parse_role_urls(jobs))
    rendered = _render_table(rows) if args.format == "table" else _render_string(rows)
    print(rendered)
    if args.format == "table":
        print(f"\nsource: {source}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
