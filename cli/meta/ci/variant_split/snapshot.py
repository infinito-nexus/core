"""Record the CI matrix the current tree plans, through the real pipeline.

A snapshot holds what a variant split can change: the candidate rows and
their coverage credits, every row's settled round and edges, the axes and the
budget head of each sweep, and every variant pin. Two snapshots, one taken
before the split and one after, are what :mod:`.compare` diffs.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.roles.mapping import ROLE_FILE_META_VARIANTS

from .rounds import pin_findings, resolve_row, token

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

SEED_ENV = "INFINITO_DISCOVERY_SEED"

ENTRY_KEYS = (
    "apps",
    "variant",
    "mode",
    "network",
    "vpn",
    "distro",
    "filesystem",
    "architecture",
    "priority",
    "covered",
    "clone",
    "id",
)


def variants_digest(roles_dir: str) -> str:
    """A digest over the path, mtime and size of every ``meta/variants.yml``.

    ``read_text`` caches per process, so a digest over content would miss an
    edit made after the first read; the file stat cannot.

    Args:
        roles_dir: the roles tree.
    """
    digest = hashlib.sha256()
    for path in sorted(Path(roles_dir).glob(f"*/{ROLE_FILE_META_VARIANTS}")):
        stat = path.stat()
        digest.update(
            f"{path.relative_to(roles_dir)}:{stat.st_mtime_ns}:{stat.st_size};".encode()
        )
    return digest.hexdigest()


def check_seeds(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """The discovery seed both snapshots share.

    Rows that tie in the ranking are ordered by a draw the seed fixes, so two
    snapshots with different or missing seeds differ by noise the split never
    caused, such as a credit that moves to another coverer.

    Args:
        before: the snapshot without the split.
        after: the snapshot with it.

    Raises:
        ValueError: a snapshot carries no seed, or the two differ.
    """
    seeds = (before.get("seed"), after.get("seed"))
    if not all(seeds) or seeds[0] != seeds[1]:
        raise ValueError(
            f"snapshot seeds {seeds[0]!r} and {seeds[1]!r} must be one run id: "
            f"take both with the same --seed, as CI sets {SEED_ENV}"
        )
    return str(seeds[0])


def compact(entry: Mapping[str, Any]) -> dict[str, str]:
    """The axis fields of one matrix entry.

    Args:
        entry: an entry :func:`utils.github.variant.axes.assign` produced.
    """
    return {key: str(entry.get(key, "")) for key in ENTRY_KEYS}


def row_of(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """The ranking fields of one candidate row.

    Args:
        candidate: a row :func:`cli.meta.ci.matrix.candidates` produced.
    """
    return {
        "token": token(candidate["name"], candidate.get("variant")),
        "name": candidate["name"],
        "variant": candidate.get("variant"),
        "id": int(candidate.get("id", 0)),
        "covered_by": int(candidate.get("covered_by", 0)),
        "clone": bool(candidate.get("clone")),
        "priority": bool(candidate.get("priority")),
    }


def assemble(
    *,
    candidates: list[Mapping[str, Any]],
    sweeps: Iterable[int],
    assign: Callable[[list, int], list[dict]],
    head_of: Callable[[list[dict]], list[dict]],
    is_regular: Callable[[Mapping[str, str]], bool],
    resolve: Callable[[str, int | None], dict[str, Any]],
    budget: Mapping[str, int],
    variant_counts: Mapping[str, int],
    pins: list[dict[str, Any]],
    digest: str,
    seed: str,
) -> dict[str, Any]:
    """Build a snapshot from the pipeline's pieces.

    Args:
        candidates: the sweep's ordered candidate rows.
        sweeps: the sweep numbers to assign axes for.
        assign: ``(candidates, sweep) -> entries``, the real axis assignment.
        head_of: ``entries -> the entries the sweep deploys``, the real chunker.
        is_regular: whether an entry stays in the job list.
        resolve: ``(role, variant) -> round record`` (:func:`.rounds.resolve_row`).
        budget: :func:`cli.meta.ci.slots.budget`.
        variant_counts: role -> how many variants it declares.
        pins: every pin of the tree (:func:`.rounds.pin_findings`).
        digest: :func:`variants_digest` of the tree.
        seed: the discovery seed the ranking ran under.
    """
    rows = [row_of(candidate) for candidate in candidates]
    rounds = {row["token"]: resolve(row["name"], row["variant"]) for row in rows}
    per_sweep = {}
    for sweep in sweeps:
        entries = assign(list(candidates), sweep)
        per_sweep[str(sweep)] = {
            "entries": [compact(entry) for entry in entries],
            "jobs": [
                token(entry["apps"], int(entry["variant"] or 0))
                for entry in entries
                if is_regular(entry)
            ],
            "head": [compact(entry) for entry in head_of(entries)],
        }
    return {
        "digest": digest,
        "seed": seed,
        "budget": dict(budget),
        "rows": rows,
        "rounds": rounds,
        "sweeps": per_sweep,
        "variant_counts": dict(variant_counts),
        "pins": pins,
    }


def pipeline() -> dict[str, Any]:
    """The repository's own matrix pipeline for the current tree.

    Returns:
        ``roles_dir``, ``variants_per_app``, ``candidates`` and the
        ``assign``, ``head_of`` and ``is_regular`` callables of
        :func:`assemble`.
    """
    from cli.meta.ci import matrix, query
    from utils.cache.applications import get_variants
    from utils.cache.files import PROJECT_ROOT
    from utils.github.variant import instructions, network, pools, vpn

    roles_dir = str(PROJECT_ROOT / "roles")
    axes_args = {
        "network_input": network.resolve_network_input(None),
        "vpn_mode": vpn.resolve_vpn_mode(None),
        "distros": pools.resolve_distros(""),
        "filesystems": pools.resolve_filesystems(""),
        "architectures": pools.resolve_architectures(""),
    }
    return {
        "roles_dir": roles_dir,
        "variants_per_app": get_variants(roles_dir=roles_dir, readonly=True),
        "candidates": matrix.candidates(
            modes=query.resolve_modes(query.ALL_MODES),
            whitelist="",
            priority="",
            lifecycles="",
        ),
        "assign": lambda rows, sweep: matrix.assigned(rows, sweep=sweep, **axes_args),
        "head_of": lambda entries: [
            e for chunk in matrix.chunks_of(entries, 0) for e in chunk
        ],
        "is_regular": lambda e: (
            e["priority"] != "true" and not instructions.redundant(e)
        ),
    }


def row_axes(tok: str, sweeps: Iterable[int]) -> dict[str, Any]:
    """The axes, job-list position and budget fate one row gets per sweep.

    Args:
        tok: the row's ``role#variant`` token.
        sweeps: the sweep numbers to assign axes for.
    """
    pipe = pipeline()
    out: dict[str, Any] = {}
    for sweep in sweeps:
        entries = pipe["assign"](list(pipe["candidates"]), sweep)
        jobs = [
            token(e["apps"], int(e["variant"] or 0))
            for e in entries
            if pipe["is_regular"](e)
        ]
        head = {
            token(e["apps"], int(e["variant"] or 0)) for e in pipe["head_of"](entries)
        }
        mine = [
            {
                key: e[key]
                for key in ("mode", "network", "distro", "filesystem", "architecture")
            }
            for e in entries
            if token(e["apps"], int(e["variant"] or 0)) == tok
        ]
        out[str(sweep)] = {
            "entries": mine,
            "job_position": jobs.index(tok) if tok in jobs else None,
            "in_budget_head": tok in head,
            "covered": next(
                (
                    e["covered"]
                    for e in entries
                    if token(e["apps"], int(e["variant"] or 0)) == tok
                ),
                None,
            ),
        }
    return out


def take(sweeps: Iterable[int], *, seed: str) -> dict[str, Any]:
    """Snapshot the current tree with the repository's own pipeline.

    Args:
        sweeps: the sweep numbers to assign axes for.
        seed: the discovery seed, the CI run id; it is exported as
            :data:`SEED_ENV` for this process, as CI exports it for a run.

    Raises:
        ValueError: the seed is empty.
    """
    from cli.meta.ci import slots

    if not seed.strip():
        raise ValueError(f"a snapshot needs the CI run id as its seed ({SEED_ENV})")
    os.environ[SEED_ENV] = seed
    pipe = pipeline()
    roles_dir, variants_per_app = pipe["roles_dir"], pipe["variants_per_app"]
    pins = [
        finding
        for role in sorted(variants_per_app)
        for finding in pin_findings(
            role, roles_dir=roles_dir, variants_per_app=variants_per_app
        )
    ]
    return assemble(
        candidates=pipe["candidates"],
        sweeps=sweeps,
        assign=pipe["assign"],
        head_of=pipe["head_of"],
        is_regular=pipe["is_regular"],
        resolve=lambda name, variant: resolve_row(
            name, variant, roles_dir=roles_dir, variants_per_app=variants_per_app
        ),
        budget=slots.budget(),
        variant_counts={
            role: max(1, len(entries or [{}]))
            for role, entries in variants_per_app.items()
        },
        pins=pins,
        digest=variants_digest(roles_dir),
        seed=seed,
    )
