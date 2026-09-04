"""Trigger the manual CI run (entry-manual-steer.yml) for the current branch.

entry-manual-steer.yml reads the "__ALL__" whitelist sentinel as "force a full
deploy across all roles".

A retrigger differs from its source run in the selection and in nothing else:
every other dispatch input is carried over (:func:`runs.carried_inputs`, read
off the workflow itself), and the priority line names the exact selections that
failed -- role, variant, deploy mode, onion state and distro -- rather than the
roles they belong to. The filesystem is left to the rotation
(:mod:`cli.administration.deploy.ci.selections` says why). ``--chunk-gate`` is
the one deliberate exception: it overrides the carried value so a retrigger can
keep deploying past a failed chunk.
"""

from __future__ import annotations

import argparse
import sys

from cli.administration.deploy.ci import gh, runs, selections
from cli.meta.ci import matrix, query
from utils.github import run_name
from utils.github.variant import pools, selection, tor

_WORKFLOW = "entry-manual-steer.yml"
_ALL = "__ALL__"


def _fetch(run: str, repo: str) -> dict:
    """The jobs and title of *run*, given as a URL or a bare id (which
    resolves against *repo*, the current branch's own)."""
    if run.isdigit():
        return gh.fetch_run(run, repo=repo)
    return gh.fetch_run(gh.run_id_from_url(run), repo=gh.slug_from_url(run))


def _ranking(whitelist: str, config: dict[str, str]) -> list[dict[str, str]]:
    """The regular line the retrigger's own discovery would walk.

    The priority line is deliberately left out of that computation: it only
    blacklists rows from the regular query, and a token in it that no longer
    resolves would abort here, in a helper whose job is to save runner time.
    """
    return matrix.entries_of(
        modes=query.resolve_modes(config.get("mode") or query.ALL_MODES),
        whitelist="" if whitelist == _ALL else whitelist,
        priority="",
        lifecycles=config.get("lifecycles", ""),
        sweep=0,
        tor_mode=tor.resolve_tor_mode(config.get("tor")),
        distros=pools.resolve_distros(config.get("distros")),
        filesystems=pools.resolve_filesystems(config.get("filesystem")),
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
            "at all; the remaining roles follow once they succeed, starting "
            "behind the green stretch the run added to the offset it was "
            "given. Every mode is read, and each failed job comes back as the "
            "exact selection that failed -- variant, deploy mode and onion "
            "state included. A leftover scope argument is accepted and "
            "ignored."
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
            "not cancelled/aborted (🚫) or still-running (⏳). Those two never "
            "reached a verdict, so the regular line owes them their turn "
            "rather than the priority line owing them a place."
        ),
    )
    p.add_argument(
        "--roles-only",
        action="store_true",
        help=(
            "With --failed: put the failed roles on the priority line by name, "
            "letting the rotation assign the axes, instead of replaying the "
            "exact combination each job failed in. Useful when so much is red "
            "that covering the role matters more than reproducing the row. "
            "Priority entries the source run never deployed keep their pins "
            "either way -- that run holds no evidence against the axes they "
            "named."
        ),
    )
    p.add_argument(
        "--chunk-gate",
        choices=("true", "false"),
        default=None,
        help=(
            "Override the carried chunk_gate input. 'false' keeps deploying "
            "the remaining chunks after a failed one instead of stopping the "
            "chain; 'true' stops at the first failed chunk. Omitted: the "
            "source run's value, else the workflow default."
        ),
    )
    args = p.parse_args(argv)
    if args.strict and args.failed is None:
        p.error("--strict only applies with --failed")
    if args.roles_only and args.failed is None:
        p.error("--roles-only only applies with --failed")

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
    priority_entries: set[str] = set()
    if args.apps is not None:
        apps = " ".join(args.apps.split())
        if not apps:
            p.error("--apps was empty")
        whitelist = apps
    elif args.failed is not None:
        statuses = runs.parse_role_statuses(source["jobs"])
        failed = selections.failed_selections(source["jobs"], strict=args.strict)
        if args.roles_only:
            failed = selections.collapse_to_roles(failed)
        untriggered = runs.untriggered_priority(
            runs.dispatched_priority(source, repo), statuses
        )
        if not failed and not untriggered:
            print("Nothing failed in that run; not triggering.")
            return 0
        if untriggered:
            print(f"Priority roles that never deployed: {' '.join(untriggered)}")
        priority_entries = set(failed) | set(untriggered)
    else:
        whitelist = _ALL

    config: dict[str, str] = {}
    carried_offset = ""
    if source is not None:
        logged = runs.inputs_from_jobs(source["jobs"], repo)
        config = runs.config_from_run(
            source["displayTitle"], logged, jobs=source["jobs"]
        )
        carried_offset = logged.get("offset") or run_name.value_from_title(
            source["displayTitle"], "offset"
        )
    carried_whitelist = config.pop("whitelist", "")
    if not whitelist and carried_whitelist:
        whitelist = carried_whitelist
    if args.chunk_gate is not None:
        config["chunk_gate"] = args.chunk_gate

    if args.failed is not None:
        ranking = _ranking(whitelist, config)
        priority = " ".join(sorted(priority_entries))
        config["offset"] = selections.resume_offset(
            ranking,
            selections.proven_rows(source["jobs"]),
            selection.parse_list(priority),
            carried=carried_offset,
        )
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
