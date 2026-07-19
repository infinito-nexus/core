"""Single source of truth for the CI app-discovery query.

Usage:
  python -m cli.meta.ci.query --mode compose|swarm|host [--matrix] [--format json]

Both the production discovery (scripts/meta/resolve/apps.sh) and the
plan table (cli.meta.ci.plan) resolve role lists through this
module, so the plan shows exactly the query the run executes. One query
per mode, sharing filter (mode + INFINITO_WHITELIST + INFINITO_BLACKLIST),
INFINITO_DISCOVERY_SORT order, lifecycle envelope and the
INFINITO_MAX_JOBS cap ('auto' resolves per mode via cli.meta.ci.slots):

  compose  whole-role rows, clones sorted last, variants packed into
           size/storage bundles for the job count
  host     whole-role rows, clones and tested-elsewhere roles sorted
           last, bundled like compose
  swarm    one row per variant (``role#variant`` tokens), ranked and
           budget-cut on per-variant metrics; the cut can select a
           subset of a role's variants

``--matrix`` renders exactly the row basis the mode's selection runs
on, so the matrix order IS the selection priority. ``capped=False``
returns the full ordered candidate list so callers can show what fell
behind the budget cut.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from cli.meta.ci import slots
from utils.cache.files import PROJECT_ROOT, read_text

MODES = ("compose", "swarm", "host")


def expands_variants(mode: str) -> bool:
    """Whether *mode* queries, ranks and triggers one CI job per variant.
    Swarm does (``role#variant`` tokens through the whole chain); compose
    and host bundle every variant into whole-role jobs (variant_bundles
    SPOT), so their query rows stay whole-role too."""
    return mode == "swarm"


def build_filter(mode: str, whitelist: str = "", blacklist: str = "") -> str:
    parts = [f"test_{mode} == true"]
    include = ",".join(whitelist.split())
    if include:
        parts.append(f"name %% {{{include}}}")
    exclude = ",".join(blacklist.split())
    if exclude:
        parts.append(f"not (name %% {{{exclude}}})")
    return " and ".join(parts)


def _sort_spec(mode: str) -> str:
    """The discovery sort for *mode*. Compose and host prepend clones-last
    (one representative per dna cluster stays ahead of the budget cut);
    host additionally sorts tested-elsewhere roles down so its slots go
    to roles no compose or swarm matrix already covers."""
    spec = os.environ["INFINITO_DISCOVERY_SORT"]
    if not spec.strip():
        for line in read_text(str(PROJECT_ROOT / "default.env")).splitlines():
            if line.startswith("INFINITO_DISCOVERY_SORT="):
                spec = line.split("=", 1)[1].strip().strip('"')
                break
    prefixes = {
        "compose": "asc clone",
        "host": "asc clone,asc tested_elsewhere",
    }
    prefix = prefixes.get(mode)
    if prefix:
        return f"{prefix},{spec}" if spec.strip() else prefix
    return spec


def max_jobs(mode: str) -> int:
    raw = os.environ["INFINITO_MAX_JOBS"].strip()
    if raw in ("", "auto"):
        return slots.mode_slots()[mode]
    return int(raw)


def _query_argv(
    mode: str,
    *,
    whitelist: str,
    blacklist: str,
    lifecycles: str,
    capped: bool,
    fmt: list[str],
) -> list[str]:
    args = [
        sys.executable,
        "-m",
        "cli.meta.roles.applications.complexity",
        "--deploy-mode",
        mode,
        "--filter",
        build_filter(mode, whitelist, blacklist),
        "--sort",
        _sort_spec(mode),
        *fmt,
    ]
    if expands_variants(mode):
        args.append("--variant")
    envelope = lifecycles or os.environ["INFINITO_LIFECYCLES"]
    if envelope.strip():
        args += ["--lifecycles", envelope]
    if capped:
        args += ["--max-jobs", str(max_jobs(mode))]
    return args


def discover(
    mode: str,
    *,
    whitelist: str = "",
    blacklist: str = "",
    lifecycles: str = "",
    capped: bool = True,
) -> list[str]:
    """The ordered selection the discovery query yields for *mode*:
    role names for compose and host, ``role#variant`` tokens for swarm."""
    out = subprocess.run(
        _query_argv(
            mode,
            whitelist=whitelist,
            blacklist=blacklist,
            lifecycles=lifecycles,
            capped=capped,
            fmt=["--format", "string"],
        ),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the CI app-discovery query for one deploy mode."
    )
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument(
        "--matrix",
        action="store_true",
        help=(
            "Render the full complexity matrix in query order (uncapped) "
            "on the mode's own row basis: per-variant rows for swarm, "
            "whole-role rows for compose and host. The matrix order is "
            "the selection priority."
        ),
    )
    parser.add_argument("--format", choices=("json",), dest="fmt")
    args = parser.parse_args(argv)

    whitelist = os.environ["INFINITO_WHITELIST"]
    blacklist = os.environ["INFINITO_BLACKLIST"]

    if args.matrix:
        return subprocess.run(
            _query_argv(
                args.mode,
                whitelist=whitelist,
                blacklist=blacklist,
                lifecycles="",
                capped=False,
                fmt=["-s"],
            ),
            cwd=PROJECT_ROOT,
            check=False,
        ).returncode

    roles = discover(args.mode, whitelist=whitelist, blacklist=blacklist)
    if args.fmt == "json":
        print(json.dumps(roles))
    else:
        print("\n".join(roles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
