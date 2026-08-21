"""Single source of truth for the CI app-discovery query.

Usage:
  python -m cli.meta.ci.query [--modes "swarm compose host"] [--matrix]
      [--format json]

One query per run, not one per deploy mode. Every row is a ``role#variant``
selection, so the row basis, the ranking and the budget cut all speak the
same unit and the cut can select a subset of a role's variants. Which deploy
mode a row actually runs in is decided afterwards by the rotation in
``utils.github.variant.bundles``; the query only decides which rows exist.

The mode selection is a *filter*, not an axis: ``--modes swarm`` keeps the
rows whose role can be deployed as a swarm stack, ``--modes "compose swarm"``
keeps the rows at least one of the two can take. The shared filter is
mode-clause + INFINITO_WHITELIST + INFINITO_BLACKLIST, the order is
INFINITO_DISCOVERY_SORT, whose first key sorts clones last (one representative
per dna cluster stays ahead of the budget cut, so redundant same-service-set
variants fall behind it first), and the lifecycle envelope is
INFINITO_LIFECYCLES.

``--matrix`` renders the full ordered candidate list, so the matrix order IS
the selection priority. Every human-facing view of that list goes through here
rather than re-deriving the sort and the filter: hand-rolling
``--sort "$INFINITO_DISCOVERY_SORT" --filter "compose == true"`` reads the
wrong column (``compose`` is what a role can do, ``test_compose`` is what CI
tests), which silently shows an order no run will ever take.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from utils.cache.files import PROJECT_ROOT
from utils.env.parser import env_setting
from utils.github.variant.axes import MODES
from utils.roles.display import display_names

ALL_MODES = "auto"


def resolve_modes(raw: str) -> tuple[str, ...]:
    """The deploy modes a run may draw from. ``auto`` (or empty) means every
    mode; anything else is the listed subset, in :data:`MODES` order.

    Raises:
        SystemExit: a token that names no known mode -- a typo must not
            silently narrow the run to nothing.
    """
    tokens = raw.replace(",", " ").split()
    if not tokens or tokens == [ALL_MODES]:
        return MODES
    unknown = [token for token in tokens if token not in MODES]
    if unknown:
        raise SystemExit(
            f"unknown deploy mode(s): {' '.join(unknown)}; expected "
            f"{', '.join(MODES)} or {ALL_MODES!r}"
        )
    return tuple(mode for mode in MODES if mode in tokens)


def build_filter(
    modes: tuple[str, ...], whitelist: str = "", blacklist: str = ""
) -> str:
    """The complexity ``--filter`` expression for one run."""
    clause = " or ".join(f"test_{mode} == true" for mode in modes)
    parts = [f"({clause})" if len(modes) > 1 else clause]
    include = ",".join(whitelist.split())
    if include:
        parts.append(f"name %% {{{include}}}")
    exclude = ",".join(blacklist.split())
    if exclude:
        parts.append(f"not (name %% {{{exclude}}})")
    return " and ".join(parts)


def sort_spec() -> str:
    """The discovery sort as declared in default.env."""
    return env_setting("INFINITO_DISCOVERY_SORT").strip()


def _query_argv(
    modes: tuple[str, ...],
    *,
    whitelist: str,
    blacklist: str,
    lifecycles: str,
    fmt: list[str],
    variant: bool = True,
) -> list[str]:
    """The complexity call this run discovers through.

    Args:
        variant: ``False`` collapses the rows to whole roles. Only ``--matrix``
            renders that view; discovery itself is always per ``role#variant``,
            because that is the unit the budget cut and the deploy speak.
    """
    args = [
        sys.executable,
        "-m",
        "cli.meta.roles.applications.complexity",
        *(["--variant"] if variant else []),
        "--filter",
        build_filter(modes, whitelist, blacklist),
        "--sort",
        sort_spec(),
        *fmt,
    ]
    envelope = lifecycles or env_setting("INFINITO_LIFECYCLES")
    if envelope.strip():
        args += ["--lifecycles", envelope]
    return args


def discover_rows(
    modes: tuple[str, ...] = MODES,
    *,
    whitelist: str = "",
    blacklist: str = "",
    lifecycles: str = "",
) -> list[dict]:
    """The ordered candidate rows, each the complexity payload of one
    ``role#variant``. Uncapped: the chunker decides what a sweep spends."""
    out = subprocess.run(
        _query_argv(
            modes,
            whitelist=whitelist,
            blacklist=blacklist,
            lifecycles=lifecycles,
            fmt=["--format", "json"],
        ),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out) if out.strip() else []


def token(row: dict) -> str:
    """The ``role#variant`` selection token of one query row."""
    return f"{row['name']}#{row['variant']}"


def row_modes(row: dict, modes: tuple[str, ...] = MODES) -> tuple[str, ...]:
    """The selected deploy modes this row can actually run in. Never empty
    for a row the query returned -- the filter kept it precisely because at
    least one selected mode claims it."""
    return tuple(mode for mode in modes if row.get(f"test_{mode}"))


def discover(
    modes: tuple[str, ...] = MODES,
    *,
    whitelist: str = "",
    blacklist: str = "",
    lifecycles: str = "",
) -> list[str]:
    """The ordered ``role#variant`` tokens the query yields."""
    return [
        token(row)
        for row in discover_rows(
            modes, whitelist=whitelist, blacklist=blacklist, lifecycles=lifecycles
        )
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the CI app-discovery query for one workflow run."
    )
    parser.add_argument("--modes", default=ALL_MODES)
    parser.add_argument(
        "--matrix",
        action="store_true",
        help=(
            "Render the full complexity matrix in query order: one row per "
            "role#variant. The matrix order is the selection priority."
        ),
    )
    parser.add_argument(
        "--roles",
        action="store_true",
        help=(
            "With --matrix: one row per role instead of per role#variant, in "
            "the same query order."
        ),
    )
    parser.add_argument("--format", choices=("json",), dest="fmt")
    args = parser.parse_args(argv)

    codec = display_names()
    whitelist = codec.decode_list(env_setting("INFINITO_WHITELIST"))
    blacklist = codec.decode_list(env_setting("INFINITO_BLACKLIST"))
    modes = resolve_modes(args.modes)

    if args.matrix:
        return subprocess.run(
            _query_argv(
                modes,
                whitelist=whitelist,
                blacklist=blacklist,
                lifecycles="",
                fmt=["-s"],
                variant=not args.roles,
            ),
            cwd=PROJECT_ROOT,
            check=False,
        ).returncode

    tokens = discover(modes, whitelist=whitelist, blacklist=blacklist)
    if args.fmt == "json":
        print(json.dumps(tokens))
    else:
        print("\n".join(tokens))
    return 0


if __name__ == "__main__":
    sys.exit(main())
